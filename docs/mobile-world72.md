# Street72 trained model on iPhone

The native SkyCompanion app and ReplayKit broadcast extension now bundle the same
`SkyWorld72_epoch15_640_FP32` Core ML model. Local videos and DJI screen broadcasts
use the shared Swift vision pipeline. Inference does not contact a computer,
Python service, model download endpoint, or text encoder. Optional Photon
features remain separate from local vision.

## Exact checkpoint

- Family: YOLO-World v2 / YOLOv8s, fixed 72-class detection.
- Selection: final epoch 15, `street72_resume_epoch9_to15_candidate.pt`.
- Source SHA-256: `8789b4d5be50d1a30d8637fad7548e47d90b068dcedf67894f1883941832cf49`.
- Input: RGB 640 × 640, upright ROI, centered 114 letterbox, scale 1/255.
- Output: `[1, 76, 8400]`, four box coordinates followed by 72 class scores.
- Checkpoint text embeddings are frozen inside the exported model.
- Thresholds retain the previous app policy: confidence 0.25, agnostic NMS IoU 0.7,
  maximum 300 boxes. They have not been calibrated for this checkpoint.
- FP32 package: 50,360,185 bytes. FP16 failed conversion parity and is not shipped.
- The original 115-class YOLOE segmentation package is retained on disk for
  rollback, but is no longer linked into either target.

This checkpoint has **no segmentation masks**. Detections explicitly carry nil
mask geometry; existing risk/depth logic uses its bounding-box fallback. Manual
wearer selection, tracking exclusion, freshness gates, voice commands, reminders,
and the optional depth model remain connected. This is a model capability change,
not segmentation-equivalent replacement of the old model.

Raw class names and order remain in `ios/Models/selectedModel.json`.
`MobileModelLabel` maps underscores and aliases into existing risk vocabulary.
Traffic-light colors are summarized as a traffic light; they never authorize
crossing. Newly named surface/overhead hazards use corresponding existing risk
rules. No new urgency or metric-distance claims are introduced.

## Verification and limitations

- 109 CaptureCore tests passed, including detection-only risk semantics,
  traffic-color handling, and new-class scene descriptions.
- Six training frames (one per original video) were used strictly for conversion
  equivalence. The held-out test set was not run.
- FP32 matched all 1,751 PyTorch detections: minimum matched IoU 0.999821;
  maximum confidence difference 0.0000445. This establishes conversion agreement,
  **not recognition accuracy**.
- The actual shipping Swift preprocessor/decoder produced identical results for
  upright, rotated-then-restored, and padded-then-cropped versions of one frame.
  It emitted 257 boxes and no masks. OpenCV/PIL preprocessing used by the Python
  check emitted 251 boxes on that frame. Different image resamplers can affect
  threshold/NMS decisions; cross-preprocessor detection equivalence is not claimed.
- Release Xcode build and compiled app/extension resource audits passed.
- Installed on the connected iPhone 15 Plus and launched successfully.
- The user's local-video run produced 573 analyzed frames over approximately
  50 seconds. Median processing rate was 11.39 fps; inference median/P95 was
  66.12/72.69 ms. Peak sampled app resident memory was 204.80 MB; thermal state
  stayed nominal. Playback was advancing at every recorded sample. Listening and
  optional depth were off. The phone was plugged in, with no debugger attached.
- Sustained phone FPS, broadcast-extension memory, disconnected operation, DJI
  streaming, and long-duration behavior require new measurements with this model.
  Previous YOLOE measurements do not establish Street72 performance.

The source checkpoint itself emits unusually dense detections: five of six sampled
training frames reach the 300-box limit at the existing threshold. This behavior
also occurs in PyTorch and is not fixed by conversion. It may produce redundant or
incorrect obstacles and needs training/threshold review before operational use.
There has been no independent accuracy acceptance. Fourteen classes lack verified
positive training examples: rock, parking_meter, suitcase, shopping_cart,
wheelchair, walker, skateboard, scaffolding, ladder, cable, patio_umbrella,
vending_machine, box, statue. The manifest records these gaps.

Evidence: `validation/mobile-world72/` contains conversion results (including the
failed FP16 run), Swift geometry output, built bundle audit, and installation summary.

## Phone check

1. In Settings → Diagnostics, confirm **Street72 · epoch 15**, **640 px**,
   **72 categories**, **boxes only**, **on device**.
2. Choose **Test a video**, import a local clip, and play. The player displays
   the original video without detection boxes or a detection-preview toggle.
   On-device analysis and voice alerts continue; inspect session status or
   Diagnostics to confirm analysis is running. Voice assistance remains a
   separate control.
3. Unplug the phone and repeat with the computer off. No computer connection is
   needed by the bundled model. Import clips stored locally, not cloud-only files.
4. For DJI, follow **Connect drone**, start the screen broadcast, confirm the
   video area, and return to DJI Fly. Verify analyzed-frame status; broadcasting
   alone does not prove that inference is running.

The installed development profile expires **2026-10-02 22:26:30 UTC**. Re-signing
and installation will be needed after expiry; this is separate from offline inference.

## Rebuild

Use the existing `.venv-mobile-export` environment. `export_world72_mobile.py`
verifies the checkpoint digest, fixed vocabulary and epoch count. The export
explicitly sets Core ML compute precision: Ultralytics' `half=False` alone still
defaults ML Program conversion to FP16 in this toolchain.

```sh
.venv-mobile-export/bin/python scripts/export_world72_mobile.py --precision fp32 --result /path/to/street72_resume_epoch9_to15_result.json
.venv-mobile-export/bin/python scripts/verify_world72_mobile.py --resource SkyWorld72_epoch15_640_FP32 --result /path/to/street72_resume_epoch9_to15_result.json
python3 scripts/prepare_mobile_app.py
xcodebuild -project ios/SkyCompanionCapture.xcodeproj -scheme SkyCompanion -configuration Release -destination 'generic/platform=iOS' -derivedDataPath /tmp/skycompanion-device DEVELOPMENT_TEAM=4ACQ5K4HVB -allowProvisioningUpdates build
python3 scripts/verify_mobile_bundle.py /tmp/skycompanion-device/Build/Products/Release-iphoneos/SkyCompanion.app
```

Exports are immutable: an existing destination is not overwritten. To roll back,
restore `validation/mobile-world72/previous-selectedModel.json` as the selected
manifest, regenerate the project, rebuild and reinstall. Do not change class order
or replace text embeddings during export.
