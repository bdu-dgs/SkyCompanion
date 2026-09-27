# Pole Data Visual Audit (2026-09-26)

Conclusion: the current HOT training set contains verifiable utility poles with empty labels, as well as a mismatch between pole class semantics and the live system's broader pole/column target. Together with very few training positives and only 10 training epochs, these provide concrete grounds for the next research round; this audit does not identify any one factor as the proven sole cause of failure.

## Scope, Reproduction, and Evidence

Only train/val were counted and their original images viewed. No training, model inference, MPS use, or changes to original data/labels/live configuration occurred. An old calibration JSON contains a test section and was read during structural inspection, but this audit uses no test section, test image, or test result for sampling or decisions. Data SHA256: `70e87973a6701d064295d817ac7030f32e5bf60f15d606b978361a69a98c988d`.

To reproduce, run in `/Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion`:

```sh
backend/.venv/bin/python backend/data/obstacle_experiments/pole-v2-audit/audit.py
```

The script sorts by image ID and samples sequentially using Python `random.Random(20260926)`: 12 train empty-label images, 6 train pole-positive images, and 6 val pole-positive images. Positives require at least one pole; tower-only images are not sampled. Complete identities, original paths, original labels, and file checksums are in `backend/data/obstacle_experiments/pole-v2-audit/samples.json`; quantities are in `statistics.json` in the same directory. Each of 8 contact sheets contains 3 images: green for publisher pole boxes and orange for tower boxes. `*-raw.jpg` files are viewing copies without overlays (re-encoded, not original byte copies). Original images are verified using manifest paths and SHA.

`calibrate_obstacle_threshold.py` saved only val summaries, not per-image val predictions; training also used `save_json: false` and `save_txt: false`. The previously permitted substitute of "6 positive val images" was therefore used; **these are not confirmed model misses**. Model confidence/IoU failures per image cannot be distinguished from this evidence.

## Counts and Sources

| Metric | train | val |
|---|---:|---:|
| Images | 2001 | 996 |
| Empty-label images | 1774 (88.66%) | 495 (49.70%) |
| Images with any positive annotation | 227 | 501 |
| Pole-positive images | 133 (6.65%) | 297 (29.82%) |
| Pole boxes | 199 | 505 |
| Tower boxes | 139 | 311 |
| Filename contains negative_ and labels are empty | 1721 | 488 |
| Other filenames with empty labels | 53 | 7 |

| source_metadata.source | train positive/empty | val positive/empty |
|---|---:|---:|
| bryan | 218 / 1770 | 478 / 494 |
| roboflow | 7 / 3 | 20 / 1 |
| shanghai | 1 / 1 | 3 / 0 |
| oakland | 1 / 0 | 0 / 0 |

source is the publisher's provenance field, not necessarily a geographic city; bryan scenes include both European rural roads and East Asian streets. Positive images in both splits have no lat, so these fields cannot prove geographic/route independence. Train has even fewer pole-positive images than val; negative sampling and training duration require separate controls. Neither `published_annotations` nor `reviewed_classes` establishes complete human review of negative examples.

## Per-Image Observations in the Fixed Sample

Below, N corresponds to `train_negative-xx`, T to `train_pole_positive-xx`, and V to `val_pole_positive-xx`; complete IDs are in samples.json.

| Sample | Actual observation and conclusion |
|---|---|
| N01 | Highway, sign supports on the left; no clear utility pole observed. A signpost in the broader sense is visible. |
| N02 | Highway panorama, distant wind turbines; no confirmed utility pole, so turbines do not justify relabeling. |
| N03 | Highway panorama and trees; no confirmed utility pole. |
| N04 | Lawn, trees, playground equipment; no confirmed utility pole. |
| N05 | Forest edge, wires in the sky but no clear shaft; keep unknown. |
| N06 | `bryan_pole_534`: clear utility poles carrying wires nearby on the right and ahead on the road, but zero boxes; missing annotated objects confirmed. |
| N07 | Highway, overhead wires; no confirmed usable pole shaft in the image. |
| N08 | `bryan_pole_1876`: one complete, clear utility pole at center-right, but zero boxes; missing annotated object confirmed. |
| N09 | Rural road and fields; no confirmed utility pole. |
| N10 | Mountain road, visible roadside signs/thin supports; no confirmed utility pole. |
| N11 | Forest dirt road; no confirmed utility pole. |
| N12 | `negative_1651_pole`: residential panorama, clear streetlights on the right and center; missing labels for broad pole scope, but strict utility-only scope first needs definition. |
| T01 | Panorama, whole utility pole boxed on the right; horizontal top components make the box much wider than the shaft. |
| T02 | Only the visible top of a distant tree-occluded utility pole at center-left is labeled; a nearby speed-limit sign support on the right is unlabeled. These labels are not reliable training supervision for nearby signposts. |
| T03 | Right-hand utility pole overlaps trees/hedges; box includes the visible main body, with occlusion and low contrast. |
| T04 | Nearby pole is tilted; wiper/windshield visible; box widens with pole tilt. |
| T05 | Roadside utility pole on the right is boxed against a clear sky/field background. |
| T06 | Complete utility pole on the right is boxed; crossarm makes box wider than shaft. |
| V01 | Panorama, left-hand utility pole boxed, with partial base occlusion. |
| V02 | Complete streetlight on the right has a pole box, showing that the publisher's actual pole class includes non-utility poles. |
| V03 | East Asian street, right-hand utility pole labeled, prominent double-arm streetlight on the left unlabeled; incomplete for broad pole scope. |
| V04 | Two utility poles on the left of a rural road are both boxed, including a large nearby target and a small distant target. |
| V05 | Crowded Shanghai pedestrian street, thin lamp post in front of a building boxed, base occluded by people. |
| V06 | East Asian intersection panorama, central streetlight boxed while a clear utility/traffic pole on the left is unboxed; risk of incomplete coverage exists even for utility-only scope. |

High-resolution originals without overlays were additionally viewed for N06/N08 and checked against the publisher's local original `coco/instances_train.json`: N06 image_id=1858 and N08 image_id=1761 both have no annotation. These two problems therefore already exist in the publisher's COCO data, rather than being boxes lost only in local normalized conversion. Two confirmed cases out of 12 sampled empty-label images describes only this batch (16.7%) and **is not a precise estimate of the dataset-wide missing-label rate**. N12, N01, and similar cases must be distinguished by class scope; seeing a thin object does not itself confirm a missing label.

## Box Width and Thin Poles

Scale proportionally to longest side 640 using actual dimensions: `bbox_w_px * 640 / max(image_width,image_height)`, rather than assuming every image is square.

| Pole box width/height | train, 199 boxes | val, 505 boxes |
|---|---:|---:|
| Width P10 / P50 / P90 (640-pixel scale) | 13.90 / 30.72 / 65.98 | 12.23 / 28.21 / 59.49 |
| Height P50 (same scale) | 99.31 | 98.72 |
| Width <8px | 4 (2.0%) | 11 (2.2%) |
| Width <16px | 38 (19.1%) | 100 (19.8%) |
| Width <32px | 106 (53.3%) | 294 (58.2%) |
| Height-to-width ratio P50 | 3.20 | 3.42 |

**This is bounding-box width, not actual shaft thickness.** Crossarms in T01/T06, tilt in T04, and the streetlight cantilever in V02 enlarge bbox values, while actual shafts may be only a few pixels thick. A median width around 30px therefore does not rule out thin-pole difficulty. Train/val box-width distributions are similar; existing evidence does not support the explanation that "val boxes alone are much smaller than train boxes."

## Evidence-Supported Next Steps

1. Define live target scope first: record utility pole, lamp post, signpost, and building column separately before deciding mappings. HOT cannot directly supply complete labels for broad column-like objects.
2. Quarantine suspicious empty-label images in a versioned research set rather than automatically adding positive boxes. The 53 empty-label images without negative_ filenames can form a conservative candidate quarantine group, but only 2 were confirmed from originals in this audit; the rest cannot all be claimed to have missing labels. Empty negative_ labels also do not imply clean background (N12 is a counterexample). Preserve original data and the audit manifest.
3. Balance labeled positives/candidate negatives with a fixed seed, exclude cross-split near-duplicate candidates, and establish comparison training starting from original COCO-pretrained weights. Retain original val for comparison with prior research, disclosing label noise alongside the comparison.
4. Longer training is a hypothesis. In the previous 10 epochs, val mAP50 rose from 0.215 at epoch 7 to 0.331 at epoch 10 without a visible plateau; 10 epochs cannot represent the architecture's limit. Existing validation threshold curves show much higher recall at lower thresholds at the expense of precision, but thresholds cannot fix data semantics.
5. Next time save low-threshold per-image validation predictions, then diagnose misses, localization errors, class confusion, occlusion, and shaft thickness at preregistered thresholds/IoU. Do not reopen test for parameter tuning.
6. Use local original images of nearby poles, signposts, and building columns for separate development regression, with precise boxes and scope receiving a second review. This set has already been inspected during development; do not call it blind testing, add it to HOT training, or treat single-frame recall as successful real-time first detection/audio-loop acceptance.

This audit has a small sample and is not two-person blind annotation. It did not inspect every image, or establish whether the model missed the 6 validation images. Full-class semantic cleanup, label repair, and live acceptance remain incomplete.

## Local Nearby Pole/Column Regression Draft (Additional Authorized Work)

Five actual original images were selected from the local 73-image draft, viewed, and saved in a separate audit directory as `local-regression-targets-draft.json` and `local-regression-01..05-draft.png`; the original 73-image manifest was not changed. They include 2 nearby traffic poles/6 building columns at two times in front of the same building, 2 subway-entrance lamp posts at two times in another clip, and 1 signpost in a third clip: 11 target boxes across 3 clips. The two pairs of successive frames are highly correlated and cannot be treated as 5 independent scenes.

Box scope is explicitly "visible vertical load-bearing shaft/column and base," excluding protruding lamp globes, signs, signal heads, crossarms, and wires; building columns extend to the canopy underside. Top truncation and occlusion are recorded separately. This scope differs from some HOT boxes covering whole pole-plus-crossarm assemblies and must be disclosed; low cross-scope IoU cannot directly mean the pole was not seen at all. JSON preserves source-image SHA, pixel xyxy, normalized xywh, clip/time, and marks everything `assistant_target_only_draft_pending_second_visual_review`, awaiting the parent task's second review of originals. `reviewed_classes=[]`: unannotated objects are not negatives. The source manifest calls these test images, but they have been inspected in development, so their current declared use is development regression only.

Reproduce overlays: `backend/.venv/bin/python backend/data/obstacle_experiments/pole-v2-audit/local_regression_draft.py`. Nearby describes target selection in the image, not an estimate of actual metric distance.
