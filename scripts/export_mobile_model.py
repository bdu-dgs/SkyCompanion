#!/usr/bin/env python3
"""Reproducible YOLOE v7 segmentation exports; never overwrites source weights.

Use a dedicated environment (see docs/mobile-model-report.md). Generated packages
are conversion candidates, not accepted phone models. No implicit downloads.
"""
from __future__ import annotations
import argparse, hashlib, importlib.metadata, json, os, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
(ROOT / '.skycompanion-live/mobile-export/ultralytics').mkdir(parents=True, exist_ok=True)
os.environ.setdefault('YOLO_CONFIG_DIR', str(ROOT / '.skycompanion-live/mobile-export/ultralytics'))

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=ROOT/'backend/data/models/skycompanion-yoloe-11s-v7.pt')
    p.add_argument('--sizes', type=int, nargs='+', default=[960, 640, 480])
    p.add_argument('--precisions', nargs='+', choices=['fp16', 'int8'], default=['fp16'])
    p.add_argument('--output', type=Path, default=ROOT/'ios/Models')
    args = p.parse_args()
    import torch, coremltools as ct
    from ultralytics import YOLOE
    torch.set_num_threads(2)
    source = args.source.resolve()
    source_sha = sha(source)
    if source_sha != '5ae9beeb8cdf5a5762a8bacf13ca5647428b1cbb108cfa467900e2fb09c33b91':
        raise SystemExit('Source differs from pinned v7. Review source and manifest before export.')
    args.output.mkdir(parents=True, exist_ok=True)
    versions = {n: importlib.metadata.version(n) for n in ['ultralytics','torch','torchvision','coremltools','numpy','scikit-learn']}
    (args.output/'export-versions.json').write_text(json.dumps(versions, indent=2)+'\n')
    for size in args.sizes:
        for precision in args.precisions:
            name = f'SkyCompanionYOLOE_v7_{size}_{precision.upper()}'
            destination = args.output/f'{name}.mlpackage'
            if destination.exists():
                print(f'Existing export left unchanged: {destination}', flush=True)
                continue
            workspace = ROOT/'.skycompanion-live/mobile-export'/name
            workspace.mkdir(parents=True, exist_ok=True)
            copied = workspace/f'{name}.pt'
            shutil.copy2(source, copied)
            model = YOLOE(str(copied))
            names = [model.names[i] for i in range(len(model.names))]
            assert len(names) == 115 and model.task == 'segment'
            started = time.perf_counter()
            exported = Path(model.export(format='coreml', imgsz=size, half=True,
                                         int8=precision=='int8', nms=False, batch=1, device='cpu', dynamic=False))
            shutil.copytree(exported, destination)
            cm = ct.models.MLModel(str(destination), skip_model_load=True)
            spec = cm.get_spec()
            outputs = [{'name':x.name,'shape':list(x.type.multiArrayType.shape)} for x in spec.description.output]
            manifest = {
                'schemaVersion':1, 'resourceName':name, 'inputName':'image', 'inputSize':size,
                'names':names, 'sourceSHA256':source_sha, 'sourceFile':source.name,
                'task':'segment', 'precision':precision, 'versions':versions,
                'confidenceThreshold':0.25, 'iouThreshold':0.7, 'agnosticNMS':True,
                'outputs':outputs, 'maskChannels':32,
                'preprocessing':'upright ROI; RGB; centered square letterbox 114; bilinear; scale 1/255 in model',
                'coordinateSystem':'normalized top-left upright cropped camera image',
                'predictionLayout':'[1,4+115+32,anchors]: xywh pixels, 115 class probabilities, 32 mask coefficients',
                'prototypeLayout':'[1,32,inputSize/4,inputSize/4]; coefficients dot prototypes > 0; crop by box',
                'status':'conversion_candidate_phone_and_accuracy_acceptance_pending',
                'exportSeconds':time.perf_counter()-started,
                'files':{str(f.relative_to(destination)):sha(f) for f in sorted(destination.rglob('*')) if f.is_file()},
                'packageBytes':sum(f.stat().st_size for f in destination.rglob('*') if f.is_file()),
            }
            (args.output/f'{name}.json').write_text(json.dumps(manifest,indent=2)+'\n')
            print(json.dumps({'export':str(destination),'outputs':outputs,'bytes':manifest['packageBytes']}),flush=True)

if __name__ == '__main__': main()
