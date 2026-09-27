#!/usr/bin/env python3
"""Compare exact registered images; never promotes a model or modifies labels."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.obstacle_eval import evaluate, validate_dataset
from app.obstacle_models import LocalDetector


def main():
    p = argparse.ArgumentParser()
    p.add_argument('dataset', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--models', nargs='+', default=['yolo11n','yoloe-11s','brailleguard-v6'])
    p.add_argument('--candidate', type=Path, help='Trusted local candidate checkpoint; evaluated without changing live configuration')
    p.add_argument('--split', choices=['all','train','val','test'], default='all')
    p.add_argument('--device', default=None)
    p.add_argument('--imgsz', type=int, default=None)
    p.add_argument('--repeat', type=int, default=3)
    p.add_argument('--confidence', type=float, default=None, help='Optional same-threshold sensitivity comparison')
    args = p.parse_args()
    if args.output.exists():
        p.error('Use a new report path; existing comparison evidence is never overwritten')
    if args.repeat < 1:
        p.error('repeat must be positive')
    data = json.loads(args.dataset.read_text())
    validate_dataset(data)
    permitted = {'user_authorized_local_research', 'license_confirmed'}
    excluded = [{'id':im['id'], 'reason':'license_review_required'} for im in data['images']
                if im.get('usage_status') not in permitted and not im.get('annotation_license')]
    data = dict(data, images=[im for im in data['images']
                              if im.get('usage_status') in permitted or im.get('annotation_license')])
    if args.split != 'all':
        data = dict(data, images=[im for im in data['images'] if im['split'] == args.split])
    if not data['images']:
        p.error('Selected split has no images')
    report = {'excluded_images': excluded, 'split': args.split, 'dataset_sha256': hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
              'dataset': str(args.dataset.resolve()), 'models': {},
              'timing_scope': 'Warm serial local inference including postprocessing; excludes network/render; concurrent live load may affect it.'}
    for name in [*args.models, *(['local-candidate'] if args.candidate else [])]:
        detector = LocalDetector('skycompanion-finetuned' if name == 'local-candidate' else name,
                                 confidence=args.confidence, imgsz=args.imgsz, device=args.device)
        if name == 'local-candidate':
            detector.path = args.candidate.resolve()
        detector.load()
        if name == 'local-candidate':
            detector._metadata['checkpoint_path'] = str(detector.path)
            for parent in detector.path.parents:
                provenance = parent/'provenance.json'
                if provenance.is_file():
                    detector._metadata['training_provenance'] = json.loads(provenance.read_text())
                    break
        predictions, timings = {}, []
        for im in data['images']:
            source = cv2.imread(im['path'])
            if source is None:
                raise ValueError('Cannot read the registered image')
            times = []
            for _ in range(args.repeat):
                t = time.perf_counter()
                boxes = detector.predict(source)
                times.append((time.perf_counter()-t)*1000)
            predictions[im['id']] = boxes
            timings.extend(times)
        stats = {'p50_ms': float(np.percentile(timings,50)), 'p95_ms': float(np.percentile(timings,95)),
                 'serial_inference_fps': 1000/float(np.mean(timings)), 'samples': len(timings)}
        report['models'][name] = {'metadata': detector.metadata(), 'timing': stats,
                                'evaluation': evaluate(data,predictions), 'predictions': predictions}
        print(name, stats, flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
