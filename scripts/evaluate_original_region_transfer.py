#!/usr/bin/env python3
"""Apply frozen ADE settings to original images; score known region recall only."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from evaluate_public_candidate import make_detector, collect, normalize_predictions, filter_predictions, score_split


def original_subset(data, split):
    subset = deepcopy(data)
    subset['images'] = []
    for im in data['images']:
        if im['split'] != split:
            continue
        row = deepcopy(im)
        path = Path(row['original_path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['source_sha256']:
            raise ValueError('Original image differs from saved source hash: ' + row['id'])
        row.update(path=str(path), sha256=row['source_sha256'], reviewed_classes=[],
                   annotation_coverage=dict.fromkeys(data['classes'], 'partial'),
                   coverage_basis='Known published semantic regions only; source void is unknown.',
                   input_transform='none: original JPEG, no ground-truth mask used for input')
        subset['images'].append(row)
    return subset


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('dataset', type=Path)
    p.add_argument('--lock', type=Path, required=True)
    p.add_argument('--configs', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--device', default='mps')
    a = p.parse_args()
    if a.output.exists():
        raise ValueError('Use fresh output; do not overwrite evaluation')
    data = json.loads(a.dataset.read_text())
    lock = json.loads(a.lock.read_text())
    if hashlib.sha256(a.dataset.read_bytes()).hexdigest() != lock['dataset_sha256']:
        raise ValueError('Dataset differs from validation lock')
    cfgs = json.loads(a.configs.read_text())
    a.output.mkdir(parents=True)
    report = {'dataset_sha256': lock['dataset_sha256'], 'lock_sha256': hashlib.sha256(a.lock.read_bytes()).hexdigest(),
              'input': 'Unmodified original JPEGs. No ground-truth mask is supplied to inference.',
              'scope': 'Known semantic-region recall only. Unlabelled targets are unknown. No complete-image precision or false-positive rate.',
              'limitations': ['No retuning on original images; thresholds and image sizes come from the rendered-input validation lock.',
                             'Same source images as rendered public evaluation: a paired input transfer diagnostic, not another independent dataset.',
                             'Connected regions are not verified object instances or physical distance labels.'],
              'deployed': False, 'models': {}}
    for name, cfg in zip(('baseline_v7', 'candidate'), cfgs):
        setting = lock['locked_settings'][name]
        if cfg['thresholds'] != setting['thresholds'] or cfg['imgsz'] != setting['imgsz']:
            raise ValueError('Local config differs from frozen validation settings')
        if hashlib.sha256(Path(cfg['path']).read_bytes()).hexdigest() != lock['model_fingerprints'][name]['sha256']:
            raise ValueError('Model differs from frozen validation weights')
        detector = make_detector(cfg['profile'], cfg['path'], cfg['imgsz'], a.device, lock['confidence_floor'], 'yolo')
        row = {'configuration': cfg, 'metadata': detector.metadata(), 'splits': {}}
        report['models'][name] = row
        for split in ('val', 'test'):
            subset = original_subset(data, split)
            raw, timing = collect(detector, subset['images'])
            predictions = filter_predictions(normalize_predictions(raw, data['classes']), setting['thresholds'])
            score = score_split(subset, predictions, lock['iou_threshold'])
            row['splits'][split] = {'images': len(subset['images']), 'timing': timing,
                                    'known_target_recall': {c: r['partial_known_targets'] for c,r in score['per_class'].items()}}
            (a.output/f'{name}-{split}-predictions.json').write_text(json.dumps({'raw_predictions':raw,'filtered_predictions':predictions})+'\n')
            (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            print(name, split, row['splits'][split]['known_target_recall'], flush=True)

if __name__ == '__main__':
    main()
