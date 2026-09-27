#!/usr/bin/env python3
"""Bounded ADE20K research subset; published semantic regions are not instance truth.

Preserves original masks. Never maps whole-tree masks to tree trunks. No deployment.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.obstacle_eval import validate_dataset

# ADE source pixel IDs are one based (0 is unlabelled).
CLASS_IDS = {'pole': 94, 'column': 43, 'fence': 33, 'rock': 35}
SOURCE = 'https://data.csail.mit.edu/places/ADEchallenge/ADEChallengeData2016.zip'
TERMS = 'https://ade20k.csail.mit.edu/terms/'


def regions(mask, ids=CLASS_IDS):
    """Every positive connected component retained, including tiny regions.

    Adjacent same-class objects can merge; occlusion can split one object.
    Evaluation must retain this limitation rather than call these true instances.
    """
    h, w = mask.shape
    boxes = []
    for label, value in ids.items():
        count, _, stats, _ = cv2.connectedComponentsWithStats((mask == value).astype('uint8'), 8)
        for x, y, bw, bh, area in stats[1:count]:
            boxes.append({'label': label, 'x': float(x/w), 'y': float(y/h),
                          'w': float(bw/w), 'h': float(bh/h), 'mask_area_px': int(area),
                          'geometry_scope': 'visible_component_bbox',
                          'truncated': bool(x == 0 or y == 0 or x+bw == w or y+bh == h),
                          'near_in_image': None, 'distance_m': None})
    return boxes


def phash(raw):
    im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    if im is None:
        raise ValueError('Unreadable image')
    dct = cv2.dct(cv2.resize(im, (32, 32)).astype('float32'))[:8, :8].flatten()
    bits = dct > np.median(dct[1:])
    return sum(int(v) << i for i, v in enumerate(bits))


def validate_source_pair(mask, image_raw=None):
    if mask is None or mask.ndim != 2 or not np.issubdtype(mask.dtype, np.integer):
        raise ValueError('Expected a single-channel integer semantic mask')
    if int(mask.min()) < 0 or int(mask.max()) > 150:
        raise ValueError('ADEChallenge semantic IDs must be in 0..150')
    if image_raw is not None:
        image = cv2.imdecode(np.frombuffer(image_raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape[:2] != mask.shape:
            raise ValueError('Source image and mask dimensions do not match')


def rendered_known_pixels(image_raw, mask):
    """Remove unknown visual content; never train visible unlabelled objects as negatives.

    This changes the input distribution. It is a bounded research transform, NOT
    evidence that full original images have complete annotations.
    """
    validate_source_pair(mask, image_raw)
    image = cv2.imdecode(np.frombuffer(image_raw, np.uint8), cv2.IMREAD_COLOR)
    image[mask == 0] = 114
    ok, encoded = cv2.imencode('.png', image)
    if not ok: raise ValueError('Failed to encode known-pixel image')
    return encoded.tobytes()


def duplicate_groups(rows, distance=4):
    """Exact + 64-bit pHash candidates. Conservative grouping, not asserted duplicates."""
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    def union(a, b):
        a, b = find(a), find(b)
        if a != b: parent[max(a, b)] = min(a, b)
    exact = {}; bands = defaultdict(list); pairs = []
    for i, row in enumerate(rows):
        digest = row['sha256']; value = int(row['phash'], 16)
        if digest in exact: union(i, exact[digest])
        exact[digest] = i
        candidates = set()
        for part in range(5):
            key = (part, (value >> (part*13)) & 8191)
            candidates.update(bands[key])
        for j in candidates:
            delta = (value ^ int(rows[j]['phash'], 16)).bit_count()
            if delta <= distance:
                union(i, j); pairs.append({'a': row['id'], 'b': rows[j]['id'], 'distance': delta})
        for part in range(5): bands[(part, (value >> (part*13)) & 8191)].append(i)
    groups = defaultdict(list)
    for i in range(len(rows)): groups[find(i)].append(i)
    return list(groups.values()), pairs


def assign_splits(rows, groups):
    """Official val reserved as test; train partitioned by duplicate group, not location."""
    excluded = []
    for group in groups:
        ids = sorted(rows[i]['id'] for i in group)
        key = hashlib.sha256('|'.join(ids).encode()).hexdigest()[:20]
        official_val = any(rows[i]['source_split'] == 'validation' for i in group)
        split = 'val' if int(key[:8], 16) % 5 == 0 else 'train'
        for i in group:
            row = rows[i]; row['duplicate_group'] = 'ade-phash-' + key
            if official_val and row['source_split'] == 'training':
                row['split'] = 'excluded'; excluded.append(row['id'])
            else: row['split'] = 'test' if official_val else split
    return excluded


def select(rows, quotas, seed=20260926):
    """Pick rare classes first, bounded per-split counts; fixed before model predictions."""
    selected = []
    for split, quota in quotas.items():
        pool = [r for r in rows if r['split'] == split]
        order = lambda r: hashlib.sha256(f"{seed}|{r['id']}".encode()).hexdigest()
        selected_ids = set()
        availability = {c: sum(c in r['present_classes'] for r in pool) for c in CLASS_IDS}
        for c in sorted(CLASS_IDS, key=lambda c: availability[c]):
            candidates = sorted([r for r in pool if c in r['present_classes']], key=order)
            current = sum(c in r['present_classes'] for r in pool if r['id'] in selected_ids)
            for r in candidates:
                if current >= quota: break
                if r['id'] not in selected_ids:
                    selected_ids.add(r['id']); current += 1
        negatives = sorted([r for r in pool if not r['present_classes']], key=order)
        selected_ids.update(r['id'] for r in negatives[:max(10, quota//2)])
        selected.extend(r for r in pool if r['id'] in selected_ids)
    return selected


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--train-per-class', type=int, default=180)
    p.add_argument('--val-per-class', type=int, default=40)
    p.add_argument('--test-per-class', type=int, default=60)
    p.add_argument('--render-known-pixels', action='store_true',
                   help='Research-only: replace void pixels with neutral fill; preserve original images separately')
    p.add_argument('--max-void-fraction', type=float, default=.2)
    a = p.parse_args(); out = a.output.resolve()
    if (out/'dataset.json').exists(): raise ValueError('Use a fresh dataset version')
    out.mkdir(parents=True, exist_ok=True)
    archive_sha = hashlib.sha256(a.archive.read_bytes()).hexdigest()
    rows = []
    with zipfile.ZipFile(a.archive) as z:
        names = z.namelist()
        for name in sorted(names):
            if '/annotations/' not in name or not name.endswith('.png'): continue
            raw = z.read(name)
            mask = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
            validate_source_pair(mask)
            void_fraction = float(np.mean(mask == 0))
            # A standard YOLO loss cannot ignore unknown visual content. Either
            # require zero void pixels, or explicitly remove that source content.
            if void_fraction > a.max_void_fraction: continue
            if void_fraction and not a.render_known_pixels: continue
            present = [k for k, v in CLASS_IDS.items() if np.any(mask == v)]
            image_name = name.replace('/annotations/', '/images/').removesuffix('.png') + '.jpg'
            # Keep all target positives; deterministic 10% of general background images.
            if not present and int(hashlib.sha256(image_name.encode()).hexdigest()[:8], 16)%10: continue
            image = z.read(image_name)
            validate_source_pair(mask, image)
            rows.append({'id': Path(name).stem, 'source_image': image_name, 'source_mask': name,
                         'source_split': name.split('/')[-2], 'sha256': hashlib.sha256(image).hexdigest(),
                         'source_sha256': hashlib.sha256(image).hexdigest(),
                         'source_void_fraction': void_fraction,
                         'phash': format(phash(image), '016x'), 'present_classes': present})
        groups, pairs = duplicate_groups(rows)
        excluded = assign_splits(rows, groups)
        chosen = select(rows, {'train': a.train_per_class, 'val': a.val_per_class, 'test': a.test_per_class})
        images = []
        for row in chosen:
            raw = z.read(row['source_image']); mask_raw = z.read(row['source_mask'])
            image_path = out/'images'/row['split']/(row['id']+('.png' if a.render_known_pixels else '.jpg'))
            original_path = out/'originals'/row['split']/(row['id']+'.jpg')
            mask_path = out/'masks'/row['split']/(row['id']+'.png')
            image_path.parent.mkdir(parents=True, exist_ok=True); mask_path.parent.mkdir(parents=True, exist_ok=True)
            mask = cv2.imdecode(np.frombuffer(mask_raw, np.uint8), cv2.IMREAD_UNCHANGED)
            original_path.parent.mkdir(parents=True, exist_ok=True); original_path.write_bytes(raw)
            rendered = rendered_known_pixels(raw, mask) if a.render_known_pixels else raw
            image_path.write_bytes(rendered); mask_path.write_bytes(mask_raw)
            row['sha256'] = hashlib.sha256(rendered).hexdigest()
            images.append(dict(row, path=str(image_path), mask_path=str(mask_path),
                original_path=str(original_path),
                mask_sha256=hashlib.sha256(mask_raw).hexdigest(),
                video_group='unknown-public-still', location_group='unknown-ade-location', route_group=None,
                review_status='published_annotations', reviewed_classes=list(CLASS_IDS),
                human_reviewed=False, annotation_source=SOURCE, annotation_license='BSD-3-Clause (annotations)',
                image_license='ADE20K non-commercial research and education terms', usage_status='research_only',
                annotation_coverage={c:'complete' for c in CLASS_IDS},
                coverage_basis='Published dense semantic regions on rendered known pixels only; void source content is removed, not reviewed.',
                source_annotation_coverage='partial: source mask value 0 is unknown',
                input_transform='void pixels filled with RGB 114' if a.render_known_pixels else 'none',
                annotations=regions(mask), time_s=None, time_basis='still_image',
                geometry_scope='visible_component_bbox',
                unlabelled_pixel_fraction=float(np.mean(mask == 0))))
    data = {'version':'public-ade-regions-visible-v2-20260926','classes':list(CLASS_IDS),'images':images,
            'source':SOURCE,'source_archive_sha256':archive_sha,'terms_url':TERMS,
            'purpose':'public_annotation_research_pilot_not_deployment','image_source':'public_dataset',
            'source_label_mapping':CLASS_IDS,'geometry_scope':'visible_component_bbox',
            'split_policy':'Publisher validation kept as research test; train hash-group split; no claimed geography separation.',
            'limitations':['Semantic connected components are NOT object instances; occlusion can split and touching objects can merge.',
                'No tree-trunk or construction-barrier labels in this subset.',
                'Original capture routes and geographic independence are unknown.',
                'Evaluation is the transformed visible-label-region task; it does not establish precision/recall on original full frames.',
                'Neutral filling of unknown source pixels changes appearance and can create artificial edges; transfer to clean original frames must be checked separately.',
                'Whole-image tests cannot measure first discovery, false alerts/minute, mobile FPS or acoustic latency.',
                'Four-class specialist cannot replace the current 115-class model.'],
            'deployed':False}
    if not images: raise ValueError('No usable images: source masks contain void pixels; do not train an empty dataset')
    validate_dataset(data)
    counts={s:{'images':sum(i['split']==s for i in images),
               'regions':dict(Counter(b['label'] for i in images if i['split']==s for b in i['annotations']))}
            for s in ['train','val','test']}
    (out/'dataset.json').write_text(json.dumps(data,indent=2)+'\n')
    (out/'coverage.json').write_text(json.dumps(counts,indent=2)+'\n')
    (out/'split-audit.json').write_text(json.dumps({'phash_candidates':pairs,'excluded_training_ids':excluded,
        'geographic_independence_verified':False,'examined_images':len(rows),'groups':len(groups)},indent=2)+'\n')
    print(json.dumps({'dataset':str(out/'dataset.json'),'counts':counts}), flush=True)


if __name__ == '__main__': main()
