# SkyCompanion YOLOE on-device conversion and validation

Status: **Runnable Core ML models and actual Swift preprocessing/decoding are verified; iPhone extension resources, sustained performance and complete 115-class accuracy acceptance remain pending.** The default is 960 FP16, preserving input scale. 640/480/quantized exports are comparison candidates, not automatic replacements.

## Reproducible inputs and export

- Source: `backend/data/models/skycompanion-yoloe-11s-v7.pt`; SHA256 `b089b9d0d5793814e9690ebfec83e1c02a75712cd213139db676581b5ce69bb8`.
- Pretrained YOLOE-11s **segmentation**, fixed prompts, 115 classes; not a newly trained model from this task. Each manifest includes the complete ordered vocabulary.
- Separate `.venv-mobile-export`; existing backend environment unchanged. Python 3.12.6, Ultralytics 8.4.37, Torch 2.11.0, torchvision 0.26.0, Core ML Tools 9.0, NumPy 2.2.6. Direct dependency versions: `ios/Models/export-versions.json`.
- Prompts are fused into the vision network during export. No text encoder/network request runs on the phone. Input `image` is RGB 0–255; model scale is 1/255.
- FP16 960/640/480 and INT8 640 exported successfully. INT8 means **8-bit k-means weight palettization**, not integer-only activations/computation.
- Retained warnings: Core ML Tools 9.0 officially tested Torch through 2.7, while this environment used 2.11 to match the backend; scikit-learn 1.7.2 exceeds the traditional sklearn converter's supported range. Conversion and real Core ML execution succeeded, but warnings are not erased.

```sh
backend/.venv/bin/python -m venv .venv-mobile-export
.venv-mobile-export/bin/python -m pip install 'ultralytics==8.4.37' 'torch==2.11.0' 'torchvision==0.26.0' 'coremltools==9.0' 'numpy==2.2.6' 'scikit-learn==1.7.2'
.venv-mobile-export/bin/python scripts/export_mobile_model.py
.venv-mobile-export/bin/python scripts/export_mobile_model.py --sizes 640 --precisions int8
.venv-mobile-export/bin/python scripts/verify_mobile_model.py --models SkyCompanionYOLOE_v7_960_FP16 SkyCompanionYOLOE_v7_640_FP16 SkyCompanionYOLOE_v7_480_FP16 SkyCompanionYOLOE_v7_640_INT8
```

The script checks the source digest and copies weights to `.skycompanion-live/mobile-export`, without modifying originals or overwriting existing exports. Manifests include every package file's hash/size, class order and output shape. Xcode compiles `.mlpackage` to `.mlmodelc`; `selectedModel.json` selects the resource.

## Model outputs and Swift interface

- Prediction `var_1347`: `[1,151,N]`, with N = 18900/8400/4725. Four letterbox-pixel coordinates `cx,cy,w,h`, 115 class probabilities and 32 mask coefficients; no extra objectness column.
- Prototype `var_1385`: `[1,32,S/4,S/4]`.
- Confidence .25, class-agnostic NMS IoU .7, maximum 300 detections, matching the backend baseline.
- `CoreMLVisionEngine` handles CVPixelBuffer, CGImagePropertyOrientation and normalized ROI: orient, crop, center-letterbox with RGB114. Output belongs to the **cropped upright camera image**, not body coordinates.
- Core Image uses software rendering; Core ML defaults to `.cpuAndNeuralEngine` to avoid background GPU scheduling. Actual broadcast-extension fit requires device measurement.
- Masks multiply coefficients by prototypes, crop to boxes and threshold at zero. All exterior contours are extracted, at most 96 points each. `polygon` keeps the largest for compatibility; `polygons` preserves disconnected regions for risk union.
- Contours currently come from the prototype grid, without desktop `process_mask(upsample=True)` input-resolution interpolation. Pixel equivalence is not claimed; holes are not encoded, as with the desktop exterior-contour representation. Tensor-mask conversion and mobile polygon fidelity are separate checks.
- `VisionInferenceResult.inferenceMS` includes preprocessing, prediction, NMS and contours, excluding DJI transmission, queue wait and audio.

## Executed Mac regression

Material: ten riverside frames from one scene and five additional street frames, selectively reviewed twice by the assistant. **Not human-reviewed, fully annotated across 115 classes or an independent blind test.** Unlabelled objects are not treated as false positives.

Reports: `ios/Models/parity-report.json`, `parity-street-report.json`. Comparison uses identical fixed square letterboxing. Desktop `rect=True` rectangular padding is different input and needs a separate system regression.

| Candidate | Package bytes | Riverside matches to same-scale PyTorch | Street matches | Mac CPU predict P95, riverside |
|---|---:|---:|---:|---:|
| 960 FP16 | 20,532,367 | 7/7 | 82/82 | 50.7 ms |
| 640 FP16 | 20,469,300 | 18/18 | 58/60 | 25.2 ms |
| 480 FP16 | 20,447,239 | 6/6 | 40/40 | 14.7 ms |
| 640 INT8 | 10,422,751 | 15/18 | 56/60 | 24.5 ms |

A match requires identical class and box IoU ≥.5; it measures conversion preservation, not detection correctness. For 960 FP16, mean matched-box IoU is .988/.982 and prototype-mask IoU .987/.979 for riverside/street respectively.

Of five labelled riverside cones, 960, 640 FP16 and 640 INT8 found three; 480 found two, so 480 was not selected. INT8 lost same-scale baseline predictions and was not selected. Railings, curbs, tree trunks and selectively reviewed street poles had many misses at the tested threshold. Conversion does not establish reliable hazard recognition.

No complete false-positive baseline exists, so the all-class target of ≤3 percentage-point recall loss and ≤10% false-positive growth cannot be signed off. Evidence for 640 remains insufficient. 960 is the **development-test default**, not an accepted safe/accurate baseline.

### Actual Swift pipeline

`scripts/verify_mobile_vision.swift` compiles with the shipped `VisionEngine.swift` and CaptureCore. Actual Mac 960 FP16 runs found 18 objects in a landscape street frame and two in a portrait riverside frame, matching Python Core ML postprocessing. Upright, rotated-then-restored and padded-then-ROI-cropped inputs produced identical detections and polygons. Record: `ios/Models/swift-decoder-report.json`.

That Mac run including sequential tensor decoding took about 87–95 ms/frame. Model-only timings around 47 ms do not establish 10 fps in the app, and Mac data does not establish phone performance. Separate reports cover Xcode, simulator and device evidence.

## Pending acceptance

- iPhone 15 Plus extension loading, physical peak memory, Jetsam and 30-minute thermal/battery behavior.
- Concurrent Core ML/STT/TTS, background transitions and audio interruption.
- Real Neo 2 + DJI Fly, unplugged from computer/internet, ten-minute loop.
- Sufficient human-reviewed data across 115 classes and independent rectangular-desktop versus square-mobile regression.
- Sustained 10 fps and actual acoustic-start P95 ≤750 ms. Short phone measurements exist; see `mobile-device-test.md`, without treating them as full acceptance.

Reference: [Ultralytics YOLOE export](https://docs.ultralytics.com/models/yoloe/). Frozen 8.4.37 source and artifact manifests govern this export, not newer online model behavior.
