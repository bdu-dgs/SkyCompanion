"""Partial-label-aware evaluation. Missing classes remain unknown, never automatic negatives."""
from collections import defaultdict
from pathlib import Path
import hashlib
import math

from .obstacle_risk import iou


def reviewed_for_training(image):
    """Keep review provenance truthful; two independent visual reviews may be assistant reviews."""
    if image.get('review_status') == 'human_verified':
        return True
    if image.get('review_status') != 'assistant_reviewed':
        return False
    reviewers = {p.get('reviewer') for p in image.get('review_passes', [])
                 if isinstance(p, dict) and p.get('method') == 'visual' and p.get('reviewer')}
    return len(reviewers) >= 2


def dataset_readiness(data):
    """Report training blockers without calling assistant or publisher labels human verification."""
    images = data.get('images', [])
    classes = set(data.get('classes', []))
    groups = {kind: sorted({str(im.get(kind, 'unknown')) for im in images})
              for kind in ('video_group', 'location_group')}
    verified = [im for im in images if reviewed_for_training(im)
                and set(im.get('reviewed_classes', [])) == classes]
    blockers = []
    if not classes or len(classes) != len(data.get('classes', [])):
        blockers.append('Dataset needs a nonempty unique class vocabulary.')
    if any(im.get('usage_status') == 'license_review_required' for im in images):
        blockers.append('Some assets require license review before new ML use.')
    if len(verified) != len(images) or not images:
        blockers.append(f'Only {len(verified)}/{len(images)} images have complete reviewed labels (human review or two independent assistant visual passes).')
    splits = {im.get('split') for im in images}
    if splits != {'train', 'val', 'test'}:
        blockers.append('Independent train, val and test splits are not all present.')
    for kind, values in groups.items():
        confirmed = [v for v in values if not v.startswith('unknown')]
        if len(confirmed) < 3:
            blockers.append(f'Only {len(confirmed)} confirmed {kind} groups; at least three are needed.')
    try:
        validate_dataset(data)
    except (ValueError, OSError, KeyError) as exc:
        blockers.append(str(exc))
    return {'ready_for_supervised_training': not blockers, 'images': len(images),
            'complete_reviewed_images': len(verified),
            'complete_human_verified_images': sum(im.get('review_status') == 'human_verified' for im in verified), 'groups': groups,
            'split_counts': {s: sum(im.get('split') == s for im in images)
                             for s in ('unassigned', 'train', 'val', 'test')},
            'blockers': blockers}


def validate_dataset(data, require_training=False):
    if not data.get('classes') or len(set(data['classes'])) != len(data['classes']):
        raise ValueError('Classes must be nonempty and unique')
    seen = {}
    ids = set()
    for image in data['images']:
        if image['id'] in ids:
            raise ValueError('Duplicate image ID')
        ids.add(image['id'])
        if not set(image.get('reviewed_classes', [])) <= set(data['classes']):
            raise ValueError('Reviewed class is not in the dataset vocabulary')
        split = image['split']
        if split not in ('unassigned', 'train', 'val', 'test'):
            raise ValueError('Invalid dataset split')
        for kind in ('video_group', 'location_group', 'sha256'):
            group = image.get(kind)
            if not group or str(group).startswith('unknown'):
                if require_training:
                    raise ValueError('Confirm video, location and image digest before training')
                continue
            key = (kind, group)
            if key in seen and seen[key] != split:
                raise ValueError(f'{kind} leaks across splits: {group}')
            seen[key] = split
        if hashlib.sha256(Path(image['path']).read_bytes()).hexdigest() != image['sha256']:
            raise ValueError('Image content does not match the registered digest')
        for b in image.get('annotations', []):
            if b['label'] not in data['classes'] or not all(type(b[k]) in (float, int) and math.isfinite(b[k]) for k in ('x','y','w','h')):
                raise ValueError('Invalid annotation')
            if not (0 <= b['x'] < 1 and 0 <= b['y'] < 1 and 0 < b['w'] <= 1-b['x']+1e-6 and 0 < b['h'] <= 1-b['y']+1e-6):
                raise ValueError('Annotation box is out of bounds')
        if require_training and image.get('usage_status') == 'license_review_required':
            raise ValueError('Training permission has not been verified; cannot export for training')
        if require_training and (not reviewed_for_training(image) or
                set(image.get('reviewed_classes', [])) != set(data['classes']) or split == 'unassigned'):
            raise ValueError('Training requires traceable review, complete class annotations and fixed splits; predictions cannot serve as ground truth')
    if require_training and {im['split'] for im in data['images']} != {'train','val','test'}:
        raise ValueError('Training requires independent train / val / test scenes')


def evaluate(data, predictions, threshold=.5):
    totals = {c: dict(tp=0, fp=0, fn=0, reviewed_images=0) for c in data['classes']}
    tracks = defaultdict(list)
    for im in data['images']:
        if im.get('review_status') not in ('assistant_reviewed', 'human_verified', 'published_annotations'):
            continue
        aliases = data.get('evaluation_aliases', {})
        pred = [dict(b, label=aliases.get(b['label'], b['label']))
                for b in predictions.get(im['id'], [])]
        for label in im.get('reviewed_classes', []):
            row = totals[label]
            row['reviewed_images'] += 1
            truth = [b for b in im.get('annotations', []) if b['label'] == label]
            guesses = sorted((b for b in pred if b['label'] == label), key=lambda b: -b['confidence'])
            matched = set()
            for b in guesses:
                available = [(iou(b, g), j) for j, g in enumerate(truth) if j not in matched]
                overlap, index = max(available, default=(0, -1))
                if overlap >= threshold:
                    matched.add(index)
                    row['tp'] += 1
                else:
                    row['fp'] += 1
            row['fn'] += len(truth) - len(matched)
            for j, g in enumerate(truth):
                if g.get('track_id'):
                    key = (im['video_group'], im.get('clip_id', im['video_group']), g['track_id'], label)
                    tracks[key].append((im['time_s'], j in matched))
    for row in totals.values():
        tp, fp, fn = (row[k] for k in ('tp','fp','fn'))
        row['precision'] = tp/(tp+fp) if tp+fp else None
        row['recall'] = tp/(tp+fn) if tp+fn else None
        row['false_positives_per_reviewed_image'] = fp/row['reviewed_images'] if row['reviewed_images'] else None
    first = []
    for (video, clip, track, label), observations in tracks.items():
        observations.sort()
        found = [t for t, ok in observations if ok]
        first.append({'video_group': video, 'clip_id': clip, 'track_id': track, 'label': label,
                      'first_annotated_time_s': observations[0][0],
                      'sampled_detection_delay_s': min(found)-observations[0][0] if found else None,
                      'missed_entire_observed_track': not bool(found)})
    return {'evaluation_aliases': data.get('evaluation_aliases', {}), 'iou_threshold': threshold, 'per_class': totals, 'sampled_first_detection': first,
            'time_limit': 'Delay is from first annotated sampled frame, not true object onset or live end-to-end latency.',
            'status': 'pilot_partial_labels_not_acceptance'}
