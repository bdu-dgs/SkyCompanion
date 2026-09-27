#!/usr/bin/env python3
"""Export the pinned final Street72 checkpoint with its existing frozen vocabulary.

No training, held-out evaluation, prompt replacement, or runtime downloads.
Run in .venv-mobile-export; selection is a separate, post-verification step.
"""
import argparse
import importlib.metadata
import json
import shutil
import time
from pathlib import Path
from export_mobile_model import ROOT, sha

PINNED_SHA = '8789b4d5be50d1a30d8637fad7548e47d90b068dcedf67894f1883941832cf49'
RESOURCE = 'SkyWorld72_epoch15_640_FP16'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--precision', choices=['fp16', 'fp32'], default='fp16')
    args = parser.parse_args()
    resource = RESOURCE.replace('FP16', args.precision.upper())
    result = json.loads(args.result.read_text())
    source = Path(result['weights'])
    assert sha(source) == result['sha256'] == PINNED_SHA
    assert result['actual_epochs'] == 15 and len(result['class_names']) == 72
    import torch
    import coremltools as ct
    from ultralytics import YOLOWorld
    torch.set_num_threads(2)
    workspace = ROOT / '.skycompanion-live/mobile-export' / resource
    workspace.mkdir(parents=True, exist_ok=True)
    copied = workspace / (resource + '.pt')
    shutil.copy2(source, copied)
    model = YOLOWorld(str(copied))
    names = [model.names[i] for i in range(len(model.names))]
    assert names == result['class_names'] and model.task == 'detect'
    assert list(model.model.txt_feats.shape) == [1, 72, 512]
    # Existing text features are traced into constants by the WorldModel exporter.
    # Do not call set_classes: it would recompute and replace checkpoint embeddings.
    started = time.perf_counter()
    # Ultralytics' mlprogram converter otherwise defaults to FP16 even when
    # half=False. Set the Core ML compute precision explicitly, in this process only.
    original_convert = ct.convert
    def convert_with_precision(*positional, **keywords):
        keywords['compute_precision'] = ct.precision.FLOAT16 if args.precision == 'fp16' else ct.precision.FLOAT32
        return original_convert(*positional, **keywords)
    ct.convert = convert_with_precision
    try:
        exported = Path(model.export(format='coreml', imgsz=640, half=args.precision == 'fp16', nms=False,
                                     batch=1, device='cpu', dynamic=False))
    finally:
        ct.convert = original_convert
    destination = ROOT / 'ios/Models' / (resource + '.mlpackage')
    if destination.exists():
        raise SystemExit('Destination exists; keep immutable exports or remove explicitly after review.')
    shutil.copytree(exported, destination)
    spec = ct.models.MLModel(str(destination), skip_model_load=True).get_spec()
    outputs = [{'name': x.name, 'shape': list(x.type.multiArrayType.shape)} for x in spec.description.output]
    assert len(outputs) == 1 and outputs[0]['shape'] == [1, 76, 8400]
    counts = result['dataset_audit']['counts']
    manifest = dict(schemaVersion=1, resourceName=resource,
        displayName='Street72 · epoch 15', inputName='image', inputSize=640, names=names,
        sourceSHA256=PINNED_SHA, sourceFile=source.name, task='detect', precision=args.precision,
        confidenceThreshold=0.25, iouThreshold=0.7, agnosticNMS=True,
        outputs=outputs, maskChannels=0,
        preprocessing='upright ROI; RGB; centered square letterbox 114; bilinear; scale 1/255 in model',
        coordinateSystem='normalized top-left upright cropped camera image',
        predictionLayout='[1,4+72,8400]: xywh pixels, 72 class probabilities; no segmentation masks',
        frozenTextFeatures=True, runtimeTextEncoder=False,
        versions={n: importlib.metadata.version(n) for n in ['ultralytics', 'torch', 'coremltools', 'numpy']},
        trainingEpochs=15, trainingResultSHA256=sha(args.result),
        independentAccuracyValidated=False, heldOutTestExecuted=False,
        classesWithoutVerifiedTrainingExamples=[n for n in names if counts.get(n, 0) == 0],
        status='conversion_candidate_phone_and_accuracy_acceptance_pending',
        exportSeconds=time.perf_counter()-started,
        files={str(f.relative_to(destination)): sha(f) for f in sorted(destination.rglob('*')) if f.is_file()},
        packageBytes=sum(f.stat().st_size for f in destination.rglob('*') if f.is_file()))
    (destination.parent / (resource + '.json')).write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps({'resource': resource, 'outputs': outputs, 'bytes': manifest['packageBytes']}))

if __name__ == '__main__':
    main()
