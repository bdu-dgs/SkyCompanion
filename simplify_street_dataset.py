"""Export the authorized common-street subset without rewriting historical labels."""
import argparse
import copy
import json
from collections import Counter
from pathlib import Path

from assemble_reviewed_dataset import export_rows
from video_training import ROOT, digest, save, to_label_line

SCHEMA = ROOT/'street_classes_core18.json'
BASE = ROOT/'local_training/collection_20260926/reviewed_v1'
COVERAGE = ROOT/'local_training/coverage_completion_20260926'


def read_rows(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def mapped_complete(classes, schema):
    confirmed = set(classes)
    return [c['name'] for c in schema['classes'] if set(c['from']) <= confirmed]


def reduce_row(original, schema):
    row = copy.deepcopy(original)
    mapping = {old:c['name'] for c in schema['classes'] for old in c['from']}
    names = [c['name'] for c in schema['classes']]
    kept, excluded, seen = [], [], set()
    for box in row['boxes']:
        if box.get('status') != 'assistant_reviewed':
            raise ValueError(('Unreviewed box', row['sample_id'], box))
        old = box['label']
        if old not in mapping:
            excluded.append(box)
            row['unknown_regions'].append(dict(xyxy=box['xyxy'], original_label=old,
                reason='Out of current core18 scope; omitted label does not establish empty background.'))
            continue
        box['original_label'] = old
        box['label'] = mapping[old]
        box['class_id'] = names.index(box['label'])
        to_label_line(box, row['width'], row['height'], names)
        key = (box['label'], tuple(box['xyxy']))
        if key not in seen:
            kept.append(box)
            seen.add(key)
    row['boxes'] = kept
    row['complete_classes_outside_unknown'] = mapped_complete(row['complete_classes_outside_unknown'], schema)
    negatives = []
    for region in row['explicit_negative_regions']:
        classes = mapped_complete(region['classes'], schema)
        if classes:
            negatives.append(dict(region, classes=classes))
    row['explicit_negative_regions'] = negatives
    for region in row['unknown_regions']:
        if 'classes' in region:
            region['original_classes'] = region.pop('classes')
            # The partial-label loss ignores unknown regions for all classes.
    row['class_schema'] = schema['version']
    row['all_instances_verified'] = False
    return row, excluded


def delete_exact(row, spec):
    matches = [i for i,b in enumerate(row['boxes'])
        if b['label'] == spec['label'] and b['xyxy'] == spec['xyxy']
        and ('track_id' not in spec or b.get('track_id') == spec['track_id'])]
    if len(matches) != 1:
        raise ValueError(('Replacement must match exactly once', row['sample_id'], spec, matches))
    return row['boxes'].pop(matches[0])


def load_integrated_rows():
    """Load reviewed supplements in the original 72-class vocabulary."""
    baseline_audit = json.loads((BASE/'dataset_audit.json').read_text())
    if digest(BASE/'annotations.jsonl') != baseline_audit['annotation_sha256']:
        raise ValueError('Baseline annotation hash changed')
    rows = read_rows(BASE/'annotations.jsonl')
    by_id = {(r['video_id'], r['frame_id']):r for r in rows}
    inputs = []
    integration = Counter()

    def record(path):
        inputs.append(dict(path=str(path), sha256=digest(path)))

    replacement = COVERAGE/'remaining_videos/video03/pass2/replacement_manifest.json'
    spec = json.loads(replacement.read_text()); record(replacement)
    if digest(spec['base_annotations']) != spec['base_sha256']:
        raise ValueError('video03 replacement source changed')
    for deletion in spec['box_deletions']:
        delete_exact(by_id['video03', deletion['frame_id']], deletion)
        integration['obsolete_video03_boxes_removed'] += 1
    increments = [
        ('video01', COVERAGE/'video01/frozen_stage_20260926_common_scope/incremental_annotations.jsonl',
         'b8d53cc136c029e8cd4ba18b3262789972e0309f6a48754c2ea9d68e5f442030'),
        ('video03', Path(spec['combined_incremental_file']), spec['combined_sha256']),
        ('video04', COVERAGE/'remaining_videos/video04/incremental_annotations.jsonl',
         'a7de73c2ceb1d3298fe02b2fc526dceb9f2afd63ff1146dc27571f92ecd5a8cf')]
    for vid,path,expected in increments:
        if digest(path) != expected:
            raise ValueError(('Frozen increment changed', path))
        record(path)
        for patch in read_rows(path):
            row = by_id[vid, patch['frame_id']]
            for old in patch.get('replace_old_boxes', []):
                delete_exact(row, old)
                integration['replaced_old_boxes'] += 1
            for box in patch['boxes']:
                box['increment_source'] = str(path)
                box['increment_review_evidence'] = patch.get('review_evidence', patch.get('evidence'))
                row['boxes'].append(box)
            row['explicit_negative_regions'].extend(patch.get('explicit_negative_regions', []))
            # Conservatively retain old broad ignore masks; a confirmed box
            # does not establish completeness of surrounding occluded targets.
            row.setdefault('supplemental_review_inputs', []).append(str(path))
            integration['increment_boxes_before_scope_filter'] += len(patch['boxes'])
    dispositions = COVERAGE/'video05/unknown_dispositions.jsonl'; record(dispositions)
    for decision in read_rows(dispositions):
        if decision['disposition'] != 'replace_conservative_unknown_geometry':
            continue
        row = by_id['video05', decision['frame_id']]
        idx = decision['unknown_index']
        if row['unknown_regions'][idx] != decision['original_region']:
            raise ValueError('Unknown-region replacement source changed')
        row['unknown_regions'][idx:idx+1] = decision['replacement_regions']
        integration['unknown_geometry_corrected'] += 1

    return rows, baseline_audit, inputs, integration


def build(output):
    if output.exists():
        raise ValueError('Choose a new output; preserve existing versions')
    schema = json.loads(SCHEMA.read_text())
    rows, baseline_audit, inputs, integration = load_integrated_rows()
    reduced,excluded_rows = [],[]
    for row in rows:
        current,excluded = reduce_row(row, schema)
        reduced.append(current)
        if excluded:
            excluded_rows.append(dict(sample_id=row['sample_id'], boxes=excluded))
    export_rows(reduced, output, baseline_audit['sources'], SCHEMA)
    (output/'excluded_from_training.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in excluded_rows))
    counts = Counter(b['label'] for r in reduced for b in r['boxes'])
    excluded_counts = Counter(b['label'] for r in excluded_rows for b in r['boxes'])
    names = [c['name'] for c in schema['classes']]
    old_names = [c['name'] for c in json.loads((ROOT/'street_classes.json').read_text())['classes']]
    mapping = {old:c['name'] for c in schema['classes'] for old in c['from']}
    report = dict(status='exported_not_trained', class_count=len(names), video_frame_count=len(rows),
        box_count=sum(counts.values()), counts=dict(counts), zero_positive_classes=[n for n in names if not counts[n]],
        original_to_core={n:mapping.get(n) for n in old_names}, excluded_counts=dict(excluded_counts),
        exclusion_means='Outside current training scope, not verified obstacle absence.',
        integration=dict(integration), increment_inputs=inputs,
        baseline_annotations_sha256=digest(BASE/'annotations.jsonl'),
        public_supplements='112 visually reviewed common-class photos kept separate pending grouped split; not silently added to train.',
        independent_validation=False, independent_test=False, training_started=False,
        unknown_policy='Original broad unknown regions retained; removed-class boxes also ignored. No completeness claim.')
    save(output/'scope_change.json', report)
    common = COVERAGE/'public_sources/commons_common_reviewed_annotations.jsonl'
    candidates = [reduce_row(r, schema)[0] for r in read_rows(common)]
    (output/'public_candidates_core18.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in candidates))
    save(output/'public_candidates_audit.json', dict(source=str(common), source_sha256=digest(common),
        image_count=len(candidates), counts=dict(Counter(b['label'] for r in candidates for b in r['boxes'])),
        split='unassigned_pending_group_audit', included_in_training=False))
    save(ROOT/'active_training.json', dict(profile='core18', schema=str(SCHEMA), dataset=str(output),
        class_count=18, model='YOLOv8s YOLO-World v2', status='dataset_reduced_training_not_started',
        supersedes='72-class collection and training',
        next_gate='Complete common-class review and lock independent grouped validation/test before final training.',
        train_command=f'python video_training.py train --data {output} --device mps --imgsz 640 --batch 16 --epochs 20 --name core18_v1'))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'local_training/collection_20260926/reviewed_core18_v1')
    build(parser.parse_args().output.resolve())
