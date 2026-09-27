# Fixed Dataset and Supervised Fine-Tuning Record · 2026-09-26

## Preserved Original Evidence

`backend/data/obstacle_dataset/regression-20260926-v1/dataset.json` freezes 70 existing/newly sampled original frames, preserves SHA256, and draws no prediction boxes onto images. `context/` preserves original JPEGs, inference-input PNGs, frame times, predictions, ROI, models, and configurations for 10 recorded before/after frame sequences. Original snapshot SHA256: `d41b05bdecc5b9584ed6498f6042d61b99ce9b3b74bf0726c1350e10f4e80d7f`.

Three new clips from the currently playing video added 328 clean captured frames, approximately 8 seconds per clip; 8 frames per clip at 1-second intervals enter the queue, totaling 24. Times use the receiver's monotonic clock and are not presented as original video playback times. All potentially overlapping New York routes are conservatively grouped; adjacent frames are not randomly split into training and test.

`labels-assistant-draft-v1.json` selects 3 additional precise problem frames from the frozen sequences, totaling 73 images. It contains selected-class assistant reviews for rocks, kiosk-like street facilities, and parking meters, plus pending-review drafts for nearby poles, building columns, fences, and truncated trunks. Assistant checks are honestly recorded; the current draft has not completed two independent visual review passes for all classes. Unchecked classes remain unknown rather than background negatives. These data have been used in development and cannot be called an unseen blind-test set.

`review.html` is a local annotation tool: open it, draw boxes on original images, and select English classes; truncation, occlusion, and close-range image attributes can be marked. Check human review only after completing class-by-class inspection, then download JSON to save. Checking a review flag without inspecting all instances is not sufficient. Original bytes/historical labels are always preserved, with later changes saved as separate versions.

## Licenses and Uses

Three historical Pexels frames are retained as historical evidence but marked `license_review_required` and automatically excluded from new ML comparisons. Pexels' general free-license overview does not establish rights for automated ML collection; its [Terms of Service](https://www.pexels.com/terms-of-service/) must be checked. The frozen snapshot is not silently rewritten; restrictions are recorded in `license-audit.json` and derived annotation manifests.

The user's current video is stored under `user_authorized_local_research`: the user authorized local research, but the original video's copyright provenance has not been independently confirmed, so samples are not published externally. User screenshots with YOLO boxes were not used for training.

## Public Pole Specialist Training

Source: [HOT/UC Berkeley Street-level Poles & Towers](https://huggingface.co/datasets/hotosm/streetlevel-poles). Published license CC BY-SA 4.0, pinned revision `0352f0b2b067439ca3467994cb9938a42310a09e`. README, original Parquet packages, SHA256, original annotations, and source/GPS metadata are preserved in `public-hotosm/`. The original data contains 3,500 images: train 2001, val 996, test 503; 977 pole boxes and 586 tower boxes.

Annotation status is `published_annotations`, not a claim of new human verification by the SkyCompanion team. Publisher splits are preserved; most positives lack original video IDs/GPS, so video/location isolation cannot be established. This is therefore a research candidate experiment, not formal blind-navigation acceptance.

An initial shard trial found only 7 positive images among 401 and was stopped with logs preserved; its output was not deployed. All 3,500 images were then collected for 10 epochs of supervised fine-tuning from YOLO11n pretrained weights, imgsz640, batch8, MPS, seed0. This is a **two-class pole/tower specialist candidate** that loses other general classes and cannot directly replace the existing 115-class SkyCompanion Vision.

Training output: `backend/data/obstacle_training/pole-full-research-20260926/`. Training status, weight SHA, and actual comparison results are added to this file after completion. Current v7 weights are retained without automatic deployment.

## Comparison and Replacement Conditions

Run current v7 and the new candidate on identical fixed test samples, input scale, threshold, and device. Record per-class TP/FP/FN, precision/recall, false positives per frame, and actual warmed-up batch1 P50/P95/serial recognition FPS. Serial static inference FPS is not phone-to-headphone end-to-end FPS/latency.

Public static images lack continuous timing, so first-detection time is unavailable. Development clips have only a few sampled annotations and can at most report "detection delay relative to the first annotated sampled frame," not actual first appearance time. Formal video acceptance requires continuous target tracks, complete ground truth, and independent review. Further domain-expert inspection before real blind-assistance deployment is recommended as a product acceptance suggestion, not a user-imposed requirement to annotate personally.

`obstacle_acceptance.py` generates per-class improvement/regression tables and blocking reasons without changing live configuration. Retain the old model whenever key classes lack positives, misses/false positives regress, source/split provenance is unclear, or phone field performance remains unverified.

## Annotation and Augmentation Rules

- `tree trunk` boxes cover only visible trunks; full canopies/whole trees use `tree`. Neither can substitute for the other to establish nearby-trunk acceptance.
- Record top truncation, edge truncation, partial occlusion, and visible bases separately. `near_in_image` is only image evidence of proximity; do not invent metric distance.
- Preserve track_id across frames for the same entity. Annotate long fences by separable instance or continuous segment under consistent rules rather than arbitrarily splitting/merging each frame.
- Training may use random crops, scale, brightness, and moderate blur, with synchronized box transformation and clipping. Augmented images or adjacent frames must not enter another split. Validation/test use no random augmentation.
- Current pole research training does not treat unannotated trees, chairs, or pavilions as 115-class negatives or claim to solve those classes.
- Steps, potholes, overhead obstacles, tables, and chairs currently lack locally reviewed positives; formal acceptance is incomplete. See `coverage.json`.

## Reproduction

```bash
backend/.venv/bin/python scripts/collect_public_obstacles.py --output backend/data/obstacle_dataset/public-hotosm
backend/.venv/bin/python scripts/train_obstacles.py backend/data/obstacle_dataset/public-hotosm/dataset.json --output backend/data/obstacle_training/NEW_RUN --epochs 10 --batch 8 --imgsz 640 --device mps --research-published --run
backend/.venv/bin/python scripts/obstacle_benchmark.py backend/data/obstacle_dataset/public-hotosm/dataset.json --split test --models yoloe-11s --candidate PATH_TO_CANDIDATE --confidence .25 --imgsz 960 --device mps --repeat 3 --output NEW_COMPARISON.json
```

`--research-published` accepts only complete public annotations with provenance and licensing, not model pseudo-labels. Default training requires complete class annotations, clearly independent train/val/test, and traceable review: either human review or assistant visual review by two distinct reviewers is accepted, with the latter not labeled human_verified. Research mode does not remove deployment gates.

## Additional Independent Videos and Review Progress

Two original Wikimedia Commons videos with clear licenses were also collected and decoded into 10 frames each. Original videos, actual per-frame PTS, SHA, authors, licenses, and before/after clip intervals are preserved in `samples/local/external-streets-20260926/manifest.json`. Tokyo Shibuya is a CC BY 2.0 overhead night scene, not close-range walking-obstacle acceptance; the Japanese riverside is a CC BY 4.0 first-person walking clip containing railings, cones, curbs, and trunks. Where the city is unknown, the original description is retained without inventing a location. These 20 images enter separate `external-commons-review-v1.json/.html` for annotation, not this round's frozen test or HOT training.

The 6 selected-class drafts were independently viewed in their original form by the dataset_training and risk_guidance assistants, recording two independent visual review passes: 2 LinkNYC device boxes, 1 empty-label image with the device out of frame, 2 rock images, and 1 parking-meter image. Trunk 17327 also received independent target-box review, without claiming all trunks in the full image are annotated; it remains target-only. All are honestly marked assistant_reviewed/draft, not human_verified.

## This Training Round Completed

All 10 supervised fine-tuning epochs finished. Training-log duration was 1373.86 seconds (approximately 22.9 minutes); candidate weight SHA256: `79b5382ae3e6de46d0a5890bbfbdbaf1b8a17ad622188b61053a72e6358244d9`. Validation contains 996 images/816 boxes: overall mAP50=0.331, pole mAP50=0.233, tower mAP50=0.428. These are research metrics on the publisher's val distribution, not evidence that nearby roadside columns or all 115 classes passed acceptance. The fixed test comparison is recorded separately.

## Measured Fixed-Test Results: Do Not Replace the Current Model

First, 503 public test images were tested at the same 960 input, 0.25 threshold, MPS, and 3 batch1 repetitions per image (IoU≥0.5):

| Model | pole hits TP | pole false positives FP | pole misses FN | pole recall | P50 / P95 | Serial inference FPS |
|---|---:|---:|---:|---:|---:|---:|
| Current v7 | 2 | 7 | 271 | 0.73% | 27.1 / 44.9 ms | 31.9 |
| This pole specialist candidate | 2 | 1 | 271 | 0.73% | 14.7 / 22.8 ms | 61.3 |

This failure result is preserved in `test-comparison.json` without overwriting. Val mAP cannot directly be interpreted as actual recall at the default threshold.

Next, only the 996 validation images were used to compare candidate sizes 640/960 and confidence 0.01/0.025/0.05/0.1/0.15/0.25/0.35/0.5, selecting by pole F1 and locking parameters before retesting the same 503 test images. Alias folding is explicitly listed in the report: pole, light pole, signpost, scaffolding pole, utility pole, and similar labels map to pole; fence/railing/pillar are not arbitrarily merged. Current v7 selects 960/0.1; the candidate selects 640/0.05. This is a **comparison of system configurations independently calibrated on val**, reported separately from the identical-parameter comparison above.

| Model | pole TP / FP / FN | pole precision | pole recall | tower TP / FP / FN | P50 / P95 | Serial inference FPS |
|---|---|---:|---:|---|---:|---:|
| v7, val-calibrated | 32 / 327 / 241 | 8.9% | 11.7% | 0 / 0 / 136 | 35.7 / 59.1 ms | 26.2 |
| Specialist candidate, val-calibrated | 82 / 164 / 191 | 33.3% | 30.0% | 92 / 200 / 44 | 13.0 / 17.2 ms | 73.7 |

There is improvement, but the candidate still misses 191/273 poles, produces 164 false positives, and supports only pole/tower. **This round rejects direct replacement of the 115-class live model**, retaining the old model. Low thresholds only increase candidate detections, not establish accurate safety warnings; these low-confidence labels are not directly connected to phone announcements. Both timing groups measure local warmed-up serial inference, excluding network, screen, and phone audio; they are not actual blind-navigation closed-loop frame rate or first-detection time.

YOLO11n, v7, and the specialist candidate also ran on 70 local street images permitted by licensing, with 3 Pexels images explicitly excluded. Against ground truth in 6 selected-class images reviewed by two assistants, v7 hits only 1/3 stone barriers, 0/2 kiosks, and 0/1 parking meters; the specialist hits zero for all these classes and cannot replace an all-class model. Other unannotated classes are excluded from statistics. Raw per-frame predictions are in `street-regression-comparison.json`.

The conversion audit checked actual decoded dimensions for all 3,500 images and consistency of 1,563 restored normalized boxes with the publisher's independent COCO xywh coordinates/class names: 0 differences (0.01-pixel tolerance). Low recall was not caused by reading xywh as xyxy in this conversion; data domain, training sufficiency, output confidence, and scale adaptation still need improvement.

All result files are in `backend/data/obstacle_training/pole-full-research-20260926/`: `result.json`, `test-comparison.json`, `validation-calibrated-test.json`, `street-regression-comparison.json`, and `acceptance.json`. First-detection time on static test data is unavailable. Live configuration was not modified, and old weights were not deleted.

## Final Data Review Addendum

The 39 draft boxes in 10 riverside originals were visually checked separately by risk_guidance and the main task. Results are saved separately in `samples/local/external-streets-20260926/riverside-labels-reviewed-v2.json`, without overwriting v1. `human_reviewed=false` honestly preserves the two-assistant review status. The curb subclass is clarified as a stone drainage-channel edge; trunk labels retain partial coverage/ignore regions rather than treating unlabeled trees as ordinary YOLO background negatives. All are from the same video/location, so adjacent frames cannot be divided across three sets.

Cross-split perceptual-hash screening of public HOT data also completed: 11 near-duplicate candidate pairs among 3,500 images (63-bit DCT hash, Hamming distance ≤4). These are leads for visual review, not proof of duplication, recorded in `public-hotosm/near-duplicate-audit.json`. Even without these candidates, missing original video IDs and positive-example GPS still prevent proof of geographic isolation; this round remains research.

Final checks: 10 obstacle unit tests passed; modified scripts passed Python compilation checks; the local annotation page passed JavaScript syntax checks; fixed snapshot SHA and image-digest/box-coordinate validation for 3 data manifests passed. Training, fixed test, calibrated test, and street regression all actually completed, with no training process left running. Deployment status remains not deployed.
