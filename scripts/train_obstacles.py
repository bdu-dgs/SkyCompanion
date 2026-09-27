#!/usr/bin/env python3
"""Export independently split reviewed labels and fine-tune a candidate; never deploy it."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.obstacle_eval import validate_dataset, dataset_readiness


def validate_training_data(data, research_published=False):
    """Gate ordinary YOLO export without promoting source annotations to acceptance.

    Existing manifests without annotation_coverage retain their explicit
    reviewed_classes contract. Once coverage is supplied, an empty/missing class
    entry is unknown, not an implicit permission to use it as background.
    """
    validate_dataset(data)
    seen_routes = {}
    for image in data['images']:
        if image.get('usage_status') == 'license_review_required':
            raise ValueError('Image training permission remains unresolved')
        if 'annotation_coverage' in image:
            coverage = image['annotation_coverage']
            if not isinstance(coverage, dict) or any(coverage.get(c) != 'complete' for c in data['classes']):
                raise ValueError('Standard YOLO export requires complete coverage for every trained class')
        if image.get('ignore_regions'):
            raise ValueError('This exporter has no ignore-region loss; do not turn unknown regions into background')
        if any(annotation.get('ignore') or annotation.get('iscrowd')
               for annotation in image.get('annotations', [])):
            raise ValueError('Ignored or crowd annotations require an ignore-aware trainer; do not export them as ordinary positives')
        route = image.get('route_group')
        if route and not str(route).startswith('unknown'):
            if route in seen_routes and seen_routes[route] != image['split']:
                raise ValueError(f'route_group crosses dataset splits: {route}')
            seen_routes[route] = image['split']
    if research_published:
        if {image['split'] for image in data['images']} != {'train', 'val', 'test'}:
            raise ValueError('Publisher train/val/test splits required even for a research pilot')
        for image in data['images']:
            if (image.get('review_status') != 'published_annotations' or
                set(image.get('reviewed_classes', [])) != set(data['classes']) or
                not image.get('annotation_source') or not image.get('annotation_license')):
                raise ValueError('Research mode requires complete attributed published annotations, not predictions')
    else:
        validate_dataset(data, require_training=True)
    # The existing readiness report deliberately rejects publisher-only labels
    # for reviewed deployment acceptance; research mode never overrides it.
    return dataset_readiness(data)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('dataset', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--epochs', type=int, default=50)
    p.add_argument('--device', default='cpu')
    p.add_argument('--imgsz', type=int, default=640)
    p.add_argument('--batch', type=int, default=8)
    p.add_argument('--model', type=Path, default=ROOT/'backend/data/models/yolo11n.pt')
    p.add_argument('--patience', type=int, default=10)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--optimizer', choices=['auto', 'AdamW', 'SGD'], default='auto')
    p.add_argument('--lr0', type=float, default=.01)
    p.add_argument('--mosaic', type=float, default=1.)
    p.add_argument('--scale', type=float, default=.5)
    p.add_argument('--close-mosaic', type=int, default=None)
    p.add_argument('--research-published', action='store_true',
                   help='Train a non-deployable research candidate from attributed published labels; geographic acceptance remains blocked')
    p.add_argument('--run', action='store_true', help='Without this flag only export reviewed data')
    args = p.parse_args()
    if args.close_mosaic is None:
        args.close_mosaic = min(10, args.epochs)
    data = json.loads(args.dataset.read_text())
    if args.epochs < 1 or args.batch < 1 or args.imgsz < 32:
        p.error('epochs/batch/imgsz must be positive valid values')
    if not args.model.is_file() or not 0 < args.lr0 <= 1 or not 0 <= args.mosaic <= 1 or not 0 <= args.scale <= 1:
        p.error('Local model and valid learning rate/augmentation ranges required')
    if args.patience < 0 or not 0 <= args.close_mosaic <= args.epochs:
        p.error('Invalid patience or close-mosaic interval')
    readiness = validate_training_data(data, args.research_published)
    target = args.output.resolve()
    if target.exists():
        raise ValueError('Use a new output directory to preserve existing training evidence')
    for image in data['images']:
        split = image['split']
        for kind in ('images', 'labels'):
            (target/kind/split).mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(image['id'].encode()).hexdigest()[:20]
        shutil.copy2(image['path'], target/'images'/split/(name+Path(image['path']).suffix))
        lines = [f"{data['classes'].index(b['label'])} {b['x']+b['w']/2} {b['y']+b['h']/2} {b['w']} {b['h']}" for b in image['annotations']]
        (target/'labels'/split/(name+'.txt')).write_text('\n'.join(lines)+'\n')
    import yaml
    dataset = target/'dataset.yaml'
    dataset.write_text(yaml.safe_dump({'path': str(target), 'train':'images/train', 'val':'images/val',
                                      'test':'images/test', 'names':dict(enumerate(data['classes']))}))
    config = dict(model=str(args.model.resolve()), data=str(dataset),
                  epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, seed=args.seed, patience=args.patience, device=args.device,
                  optimizer=args.optimizer, lr0=args.lr0, mosaic=args.mosaic, scale=args.scale,
                  close_mosaic=args.close_mosaic,
                  workers=0, project=str(target/'runs'), name='candidate', pretrained=True)
    (target/'provenance.json').write_text(json.dumps({'dataset_sha256':hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                                                   'config':config,'deployed':False,
                                                   'initial_weights_sha256':hashlib.sha256(args.model.read_bytes()).hexdigest(),
                                                   'training_mode': 'published_research_only' if args.research_published else 'reviewed_with_provenance',
                                                   'acceptance_readiness':readiness}, indent=2))
    if args.run:
        from ultralytics import YOLO
        model = YOLO(config.pop('model'))
        try:
            model.train(**config)
            best = target/'runs/candidate/weights/best.pt'
            (target/'result.json').write_text(json.dumps({'status':'trained_not_deployed',
                'weights':str(best),'sha256':hashlib.sha256(best.read_bytes()).hexdigest(),
                'acceptance_ready':readiness['ready_for_supervised_training']},indent=2))
        except Exception as exc:
            (target/'result.json').write_text(json.dumps({'status':'failed','error':str(exc)},indent=2))
            raise
    print(target)


if __name__ == '__main__':
    main()
