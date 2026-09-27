# SkyCompanion Obstacle Detection Implementation and Preliminary Test Record

**Latest implementation and acceptance entry point: [Nearby Obstacles and Voice on Both Devices](vision-and-voice-update.md).**
The current experimental configuration has a 115-class vocabulary, 960 input, and Apple GPU use when available. The following record preserves earlier model/CPU results by implementation stage; earlier descriptions of the “default model” and dropdown selection no longer describe the current interface.

2026-09-25. Status: sampling, candidate models, annotation, and assessment tools are implemented; accuracy acceptance testing and SkyCompanion-specific fine-tuning remain incomplete.

## Actual Additions in This Round

- The webpage saves the currently displayed frame and up to 4 seconds before and after it: original JPEG, actual model-input PNG, prediction boxes, frame ID, session, revision, rotation, crop, display acknowledgment, weight SHA256, and inference configuration. The buffer is limited to 12 seconds and 64 MB; persistence occurs only on a click.
- Candidate selection: original YOLO11n, official YOLOE-11s segmentation model with 24 text prompts, and externally supervised BrailleGuard v6 with 8 classes. Switching pauses old analysis and clears old results; analysis restarts after successful loading. The default at this stage remains original YOLO11n.
- Predictions and human annotations are separate. The annotation page can add/delete boxes, review each class, and download JSON. Unreviewed classes are not counted as background.
- Same-frame offline assessment, cross-split leakage checks by video/location/image digest, per-class TP/FP/FN, first-discovery delay at sampled timestamps, and serial inference duration. First discovery is relative only to annotated sampled frames and cannot replace actual first appearance or speech onset.
- After confirming a central image attention corridor, occupancy alerts can be tested: mask or box-bottom overlap, plus at least 3 observations lasting 0.4 seconds; an 8-second speech cooldown is retained across targets. No class has passed voice acceptance testing, so spoken names remain unconfirmed and generic. Boxes retain original model labels; `train` was not deleted to conceal errors.
- Computer voice is off by default; disconnection, pause, and switching clear alerts. This is not audio returned to phone headphones. The attention corridor is a user-selected image region, not road segmentation, metric ranging, or a verified navigation strategy for blind users.

## Saved Evidence

`backend/data/obstacle_cases/20260925-212100-f85c93f5/`: 121 frames, approximately 4 seconds before and after. Analysis was disabled at that time. Offline predictions can be rerun, but these frames are not evidence of the original model's live output.

`backend/data/obstacle_cases/20260925-212743-797a205a/`: 120 analyzed frames. The video pointed upward at buildings and the player showed buffering; this is not an adequate walking-obstacle acceptance segment.

`backend/data/obstacle_cases/train-scaffolding-screenshot-20260925/`: user-provided screenshot with `train 36%`, displayed frame 9952, input 790×443. Visually, the large box covers construction scaffolding, supports, fencing, and a passage; no train is visible. The screenshot includes prediction overlays and webpage elements, and lacks a clean original frame or surrounding segment. It is retained as a false-positive record, excluded from training, and cannot rule out image/prediction desynchronization.

Transport and sample export were verified: display acknowledgments bind session/revision/frame ID, and saved PNG pixels equal the decoded-and-cropped JPEG pixels. Synchronization for the historical `train` false positive has not been reproduced.

## Weight Sources and Traceability

| Configuration | Source | Actual nature |
| --- | --- | --- |
| yolo11n | Official Ultralytics COCO weights | Original 80-class baseline, conf 0.35, class-wise NMS |
| yoloe-11s | [Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/download/v8.4.0/yoloe-11s-seg.pt) | Official pretrained segmentation weights + fixed text prompts, conf 0.25, class-agnostic NMS; not SkyCompanion fine-tuning |
| brailleguard-v6 | [Author's v6 release weights](https://github.com/apffkxhsls/OSS-Blind-Walk-Assistant/releases/tag/yolo11n-models-20260619) | Externally supervised YOLO11n fine-tuning, conf 0.25; not SkyCompanion fine-tuning |

Original YOLOE file SHA256: `8e439445c87338b79d9ce21dec109f4621e26df67e94d26ea1a98c1e64dce3e3`; fixed-prompt file: `44f64dd09326a868023d759d832ee5e9652dbe5b827f83f27a34682ef17092ea`.

BrailleGuard v6 SHA256: `454a47e241771d005e76921a0c0af7ed66d128123aa0dd99215e4ccb282c8ba8`. After download, checkpoint globals were inspected first, then loading was verified with `weights_only=True`, allowlisting only installed torch/ultralytics neural-network types. The weight record specifies 50 epochs, 640, batch 8, seed 0. Classes are bicycle, bollard, car, damaged_braille_block, kickboard, motorcycle, trash, and utility_pole. **`trash` means waste, not a trash can; `utility_pole` is not expanded to every type of pole or column.**

## Same-Image Preliminary Test: Not a Substitute for Formal Acceptance

Five registered images: three from the same Pexels video at 0/12/24 seconds, plus two original phone evidence frames. Only fence, trash can, and train in the first three images were reviewed image by image by the assistant; the user or an independent annotator has not reviewed them. Other classes are excluded from accuracy calculations. Video provenance is in `samples/README.md`. Confidence settings are recorded per configuration; a shared `--confidence` supports sensitivity comparisons. This table measures deployment configurations, so differences cannot all be attributed to network architecture.

| Class (3 images) | YOLO11n TP/FP/FN | YOLOE-11s TP/FP/FN | BrailleGuard v6 TP/FP/FN |
| --- | --- | --- | --- |
| Fence | 0 / 0 / 3 | 2 / 0 / 1 | 0 / 0 / 3 |
| Trash can | 0 / 0 / 1 | 0 / 2 / 1 | 0 / 0 / 1 |
| Train (all negative samples) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |

BrailleGuard does not support these three classes; misses for unsupported classes are still counted. Its lack of `train` output cannot be treated as a fix for train false positives. YOLOE did recover some fences, but its two trash-can predictions did not match ground truth, and the trash can remained missed. No train false positives in three ordinary scenes without trains does not establish a fix for the scaffolding false positive in the user's screenshot.

CPU, 640, five identical input images, three repetitions per image after warmup: YOLO11n P50 20.99 ms / P95 22.96 ms; YOLOE P50 53.99 ms / P95 56.78 ms; BrailleGuard P50 20.08 ms / P95 21.82 ms. These are serial inference timings including postprocessing and excluding network/webpage work. The live service was running during measurement, so this is not an exclusive-hardware benchmark or actual phone inference FPS.

Complete input digests, per-frame predictions, and statistics: `backend/data/obstacle_dataset/benchmark.json`. Partial annotations: `dataset.json` in the same directory. Samples are 12 seconds apart, so they establish discovery only at sampled timestamps and cannot support precise first-discovery latency acceptance.

## Operation Entry Points

Run from the project root:

```bash
backend/.venv/bin/python scripts/obstacle_review.py backend/data/obstacle_dataset/dataset.json --output backend/data/obstacle_dataset/review.html
backend/.venv/bin/python scripts/obstacle_benchmark.py backend/data/obstacle_dataset/dataset.json --output backend/data/obstacle_dataset/benchmark.json
```

With the SkyCompanion service running, open `http://127.0.0.1:8000/api/live/annotations` locally on the Mac. Box and review-status edits remain in browser memory. Download JSON, save it to the data directory, and rerun assessment. This page does not upload to external services.

Training entry point (training had not yet run at this stage):

```bash
backend/.venv/bin/python scripts/train_obstacles.py path/to/reviewed-dataset.json --output backend/data/obstacle_training/run-001 --run
```

Training requires fully reviewed target classes, identified videos/locations, and independent train/val/test splits. Current data does not meet those requirements. The export entry point was actually verified to reject it with an error meaning “Training requires human review, complete class annotations, and fixed splits; predictions cannot serve as ground truth.” No new SkyCompanion-trained weights were fabricated.

## Acceptance Items Not Yet Met

- The scaffolding `train` false positive lacks a clean original input and surrounding segment; screenshot evidence is saved.
- Cones, construction barrels, all pole/column types, warning tape, traffic lights, and other classes lack complete per-class ground truth. The existing five images cannot constitute a dedicated training set.
- More scenes from independent videos/locations and complete annotations are required. Unknown video sources/locations cannot enter reliable training splits.
- Actual first-discovery/speech latency, false positives per minute, missed hazard alerts, audio returned to phone headphones, and path segmentation remain to be implemented or verified.
- This round does not approve any candidate as default weights for navigation by blind users or claim that the false-positive problem is resolved.

## Software Verification

25 Python behavior tests passed, covering frame correspondence, buffer eviction, rotation/session invalidation, saved input pixels, annotation leakage, duplicate predictions, partial-annotation counting, generic alerts without accepted classes, and cooldown.
Four frontend protocol tests and the production build passed. Actual browser operations and measured YOLOE results are added below.

### YOLOE Device Measurements and Interface Verification

The webpage was switched to `yoloe-11s` and analysis resumed; the startup default remained yolo11n. During 30 continuous seconds with YOLOE and analysis enabled, inference was 14.8–15.0 fps, median per-frame inference time 56.45 ms, display-acknowledgment P95 at sampled times 156.79–159.13 ms, and one additional frame was dropped. Display acknowledgment covers phone capture through webpage drawing and acknowledgment return, not photon latency, the drone link, or voice latency. Raw record: `backend/data/obstacle_dataset/yoloe-live-30s.json`.

Actual browser checks passed: model dropdown switch → load; crop → analyze; save a missed detection → success after 4 seconds; advance to the next image in the annotation page. Neither the live nor annotation page console showed warn/error entries or a framework error overlay. Dragging boxes and exporting from the annotation page, and phone headphone playback, have not passed end-to-end acceptance testing.

New-model case `20260925-213831-5a60cd49` saved 120 frames, 119 with webpage display acknowledgments; the one undisplayed frame cannot be claimed as displayed. All original predictions are retained pending ground-truth review. This segment was not mixed into the fixed five-image preliminary test above.

New segments can be registered in a dataset copy using `scripts/import_obstacle_case.py`: supply the original case directory, dataset JSON, and `--video-group`; fill `--location-group` only after confirming the location. The default split is unassigned. The script registers clean inputs only, never treats predictions as annotations, and rejects screenshots as clean training inputs.

## English Interface and Single Model Entry Point (Subsequent Update)

At the user's request, the live webpage is now English and detection boxes/lists use original English labels. The product displays only **SkyCompanion Vision · Experimental**. YOLO11n, YOLOE v1, and BrailleGuard selectors were removed from the user interface and remain in offline comparison scripts.

The default was updated to YOLOE-11s prompt vocabulary v2 (28 classes), adding tree, tree trunk, light pole, and signpost. This is a fixed-prompt expansion, not retraining. File: `skycompanion-yoloe-11s-v2.pt`, SHA256 `4a8f4efb7d6701781e9fd0101d0a6188dea7ced0616fab437d63fd0a95137191`. Original v1 weights are retained, and profile `yoloe-11s-v1` reproduces the experiment. This default refers to the experimental product's single current entry point, not a pass in navigation accuracy acceptance testing.

On the same five images, v1/v2 TP/FP/FN for annotated fences and trash cans were unchanged. v2 did not detect trees/poles in these images. Additional 640/960 and conf 0.10 tests on the building and bare winter tree scene also yielded no detections, so tree misses cannot be claimed fixed. Adding classes addresses missing output vocabulary; small-object pixels, occlusion, and domain differences still require dedicated data. The live threshold was not lowered to conceal misses.

Whole-tree masks can include overhead canopy, so they do not automatically trigger path-occupancy speech. Tree trunks and other objects occupying the path at their base are assessed separately. Road segmentation and actual risk acceptance testing remain incomplete.

Voice and phone migration architecture is in `mobile-voice-architecture.md`. Existing computer TTS was changed to English; native iOS STT/TTS had not yet been implemented at this stage, and the existing ReplayKit extension still discarded audio samples.

On-site verification of the English version: actual detection labels were person / car / construction barrel; no model dropdown remained. Instantaneous performance was about 15 fps and 57–58 ms inference. Hot reload during editing briefly showed `serviceMessage is not defined`; the complete code defines that function. Restart/reload restored the interface, and browser logs over the following two minutes showed no new warn/error entries. Rebuild and 25 backend plus 4 frontend protocol tests passed.

Actual v2 saved case `20260925-215027-5f22ede2`: 121 frames, all with display acknowledgments, and weight metadata vocabulary_version=2. A thin signpost beside parked cars remained missed in the target frame; a draft box for human review was added. No clear tree appears in this frame, so it is not treated as a tree-recall sample. New samples entered a separate `annotation-queue.json`, without changing the fixed preliminary test's `dataset.json`.
