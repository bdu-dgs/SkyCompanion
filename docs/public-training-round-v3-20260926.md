# Third Public-Data Specialist Training Round · 2026-09-26

Status: both training runs, fixed comparisons, clean-street regression, and original-photo transfer checks are complete: 30 epochs for construction and 20 epochs for the four ADE classes. New weights improve some areas but do not meet overall replacement conditions; this round did not replace the live YOLOE-11s v7 115-class weights.

## Classes and Training Limits

Priority classes this round are `pole`, `column`, `tree_trunk`, `fence`, `construction_barrier`, and `rock`. Class and visible-part rules are in `schemas/public-obstacles-v1.json` and `docs/public-obstacle-annotation-v1.md`.

Different publishers have not completely annotated all six classes, so images cannot simply be merged with missing labels treated as background. Separate, reversible specialist research runs therefore preserve the general model's table, chair, pavilion, and other capabilities. Even improvement in one specialist metric does not permit direct replacement of the 115-class model.

| Source / version | train / val / test image counts | Use and limits this round |
|---|---:|---|
| ROADWork `public-roadwork-v1` | 600 / 120 / 120 | Five construction-facility classes; Pittsburgh training, 9 other cities for validation, 8 for test. Construction fences are separate from ordinary fences. |
| ADE `public-ade-visible-v2` | 751 / 168 / 247 | Research on annotated semantic regions for pole / column / fence / rock; geographic independence unknown, image license limited to noncommercial research/education. |
| ForTrunk `public-fortrunk-v1` | 800 / 150 / 150 | Three forests isolated as whole groups; spot checks found unlabeled visible trunks and box-scope differences, so coverage changed to partial and direct standard training is prohibited. |

Original images, masks/XML, sources, licenses, splits, image SHA, and manifests are preserved. Public annotations are `published_annotations`, not newly performed human acceptance review by this project. No self-recorded videos were used, and automatic predictions were not presented as ground truth.

## Actual Findings and Corrections

- ROADWork's original `Fence` refers to construction fences; ordinary black sidewalk railings include unlabeled instances. The class is therefore `construction_fence`, without describing publisher construction labels as complete ordinary-fence annotations.
- The ForTrunk original ZIP passed official MD5 verification, and all 2,895 XML files parsed; only RGB was selected. The initial complete claim was withdrawn after visual spot checks: original manifest bytes and SHA are retained, all current entries use `tree_trunk=partial`, and the research-training gate actually rejected them. Class renaming was not used to bypass missing annotations.
- Original ADE challenge masks contain 0 (unannotated) pixels. The initial conversion requiring zero unannotated pixels yielded zero images; actual logs are preserved, and empty data was not used for training.
- ADE v2 performs only an explicitly derived task: unknown pixels are replaced with neutral RGB114 while originals and masks are preserved; training and fixed comparisons use the same derived images. Originals remain `source_annotation_coverage=partial`. This removes visual content in unknown regions, but neutral fill introduces artificial edges and domain shift. **It does not mean the original full frames are completely annotated, nor do derived scores establish reliable full-frame recognition.**
- ADE boxes come from visible semantic connected regions, not actual object instances; occlusion can split boxes and contact can merge them. Official validation serves as this research test set; official train is divided into train/val by duplicate-candidate groups, without claiming isolation by unknown locations.
- A second assistant audited all 751 ADE derived train images pixel by pixel: unknown regions are entirely 114, and known regions match decoded original pixels. Visual checks of four train images found that rock can mean an entire pebble beach, and 210 of 620 train fence regions contain only 1–4 pixels. Results can therefore be called only "semantic-region precision/recall," not improvements in low isolated rocks or complete fence instances; they do not justify deployment this round.

## Training and Evaluation Protocol

The construction specialist starts from local official COCO `yolo11n.pt`: 30 epochs, 640, batch8, MPS, AdamW lr0=.001, mosaic=.25, scale=.25, close_mosaic=5, patience8, seed20260926. Results are saved in `backend/data/obstacle_training/public-round-v3-20260926/roadwork/` without overwriting the original model.

ADE uses the same initialization and configuration for an initial 20-epoch bounded research task; differences from the construction specialist are not described as single-factor ablations. GPU tasks run sequentially to avoid unexplained resource contention from concurrent training.

Validation compares input sizes 640/960 and a predefined confidence list; per-class thresholds are chosen only on val, with both models and configurations locked before test. Per-image predictions, summaries, and validation lock files are saved. Parameters must not be reselected on test.

ROADWork's `construction_fence` and `construction_barricade` do not exactly match v7's output vocabulary; vocabulary coverage must also be disclosed. Scores of zero caused by missing output classes cannot all mean "nothing was seen." Ordinary fence is not silently renamed construction fence.

Five local clean frames with 11 reviewed pole/column targets serve as known-failure regression, not an independent test set; unlabeled objects are not false positives. Name detection and path-occupancy judgment are separate; this round's public static images contain no user-path or distance ground truth.

The following still require continuous annotated clips/physical devices: first-detection time, longest continuous miss, false positives per minute, actual phone frame rate, actual speech-onset latency, and interruptions per minute. Static inference times are not renamed as those metrics.

## Verification and Results

All actual executions this round exited successfully, with traceable weights, data, and parameter lock files. Checks passed separately for evaluation (20), training gates (13), ADE import (6), strict duplicate-annotation audit (8), original-image transfer (2), ROADWork import (6), and ForTrunk import (5), totaling 60. These tool tests are not model accuracy; model results follow.

### Construction Specialist: Fixed Test After Duplicate-Annotation Correction

Independent review found exact duplicate publisher source records: 431 train, 52 val, and 135 test records. The Ultralytics training loader had automatically deduplicated them, while external evaluation had still counted duplicate ground truth. Original data, weights, predictions, and locked parameters were preserved; a strictly deduplicated manifest was created separately and scores recomputed. **Thresholds were not retuned on revised validation; recomputation is neither a new test set nor a further weight improvement.** Historical independent review: `backend/data/obstacle_training/public-round-v3-20260926/roadwork-evaluation/independent-review-v1.md`.

| Class | Old weights P / R | New weights P / R | New weights TP / FP / FN |
|---|---:|---:|---:|
| Traffic cone, traffic_cone | 51.9% / 46.0% | 61.8% / 62.3% | 149 / 92 / 90 |
| Construction fence, construction_fence | — / 0%* | 27.4% / 31.3% | 26 / 69 / 57 |
| Construction barrel, construction_barrel | 67.2% / 14.4% | 79.1% / 53.3% | 144 / 38 / 126 |
| Construction barricade, construction_barricade | — / 0%* | 46.4% / 19.0% | 26 / 30 / 111 |
| Construction barrier, construction_barrier | 18.8% / 14.7% | 38.8% / 30.3% | 33 / 52 / 76 |

P is precision and R is recall. *v7 lacks exact output names or preapproved aliases for these two subclasses, so zero recall includes vocabulary mismatch and cannot be attributed entirely to not seeing them. Both models were separately tuned on the same val set and retain their original locked operating points.

Cones, barrels, and barriers improved, but fences have many false positives and barricades many misses; absolute barrel FP still rose from 19 to 38. Of 609 revised-val FNs, 192 have correct low-score boxes, 192 have localization/box-scope mismatch, 210 have no matching returned box, and 15 involve competition or other-class overlap. Lowering the threshold alone cannot resolve all problems.

### Four Classes Including Poles/Columns: Derived-Region Test and Original-Image Transfer

ADE trained for 20 epochs, with the best weights saved at the final epoch. Its connected regions are not complete object instances, and void/unknown areas in originals lack complete annotations. Parameters were first locked on identical known-pixel derived images, followed by a preregistered paired transfer check on **unmodified original JPEGs**. Original-image inference received no ground-truth mask, and parameters were not reselected.

| Class | Derived-region test old P / R | Derived-region test new P / R | Annotated-region recall on originals: old→new |
|---|---:|---:|---:|
| pole | 7.8% / 10.7% | 25.6% / 33.3% | 10.0% → 34.7% |
| column (building column) | 58.3% / 4.2% | 21.7% / 27.3% | 4.8% → 28.5% |
| fence | 19.3% / 8.6% | 11.1% / 9.2% | 8.6% → 7.0% |
| rock (rock region) | 22.7% / 13.0% | 23.0% / 18.2% | 13.0% → 19.5% |

Only annotated semantic-region recall is counted on originals; full-frame precision is not reported, and predictions outside those regions remain unknown. Originals and derived images come from the same material, so this is also a paired transfer check, not a new independent test set. Original-image hits: poles 52/150, columns 47/165, fences 13/185, rocks 30/154. **Many misses remain, and fences regressed.** These numbers cannot be directly compared with 45.8% pole recall on old HOT data because datasets and box definitions differ.

### Clean-Street Development Regression: Public Scores Do Not Replace Close-Range Acceptance

The targets below were reviewed beforehand by two assistants and excluded from this round's training. These are previously seen development examples, few in number and correlated within videos, not an independent release test or full-frame precision measurement. Each model uses its public-val locked settings without tuning to these frames.

| Specialist / selected targets | Old weight hits | New weight hits |
|---|---:|---:|
| ADE / 5 pole shafts | 1/5 | 1/5 |
| ADE / 6 building-column shafts | 0/6 | 3/6 |
| ADE / 2 fence locations | 2/2 | 0/2 |
| ADE / 2 protruding rocks | 0/2 | 0/2 |
| ROADWork / 3 construction barriers | 1/3 | 0/3 |

Building-column improvement is supported by actual original frames; two targets in one frame have IoU approximately 0.859 and 0.534. Examples where the new fence model boxes only a small local section were also checked. The earlier pole regression's old-model 0/5 and the 1/5 here use different operating points; both old and new weights here use new public-val tuning, so this cannot be called improvement of the old model itself. Classes not trained by a specialist are not reported as retained-capability scores.

### Actual Artifacts and Decision

Handoff note: the research weights, reports, and independent review referenced below are local historical artifacts, not bundled in this handoff. Their paths preserve provenance; no retraining or changes to the original records were performed for this handoff.

- Construction weights: `backend/data/obstacle_training/public-round-v3-20260926/roadwork/runs/candidate/weights/best.pt`, SHA256 `a82a08ab233c7939dd13d7eaeb888124806d622390aceab4b8f1bda6514b95e5`.
- Four-class pole/column/etc. weights: `backend/data/obstacle_training/public-round-v3-20260926/ade-regions/runs/candidate/weights/best.pt`, SHA256 `a40800a687a85278350fc8ee276fac633f6d36e8f9415aaa2d9e241cc21cb655`.
- The complete machine-readable summary (`backend/data/obstacle_training/public-round-v3-20260926/summary.json`), per-class results (`backend/data/obstacle_training/public-round-v3-20260926/RESULTS.md`), original-image transfer predictions, close-range overlays, frozen parameters, and source manifests are saved.
- This round did not replace live weights or directly turn lower class-confidence scores into more aggressive speech warnings. The model cannot be claimed reliable enough for blind walking assistance.
- No trunk specialist was trained: both ForTrunk and the newly examined Mendeley source have unlabeled background trunks. The official Mendeley small archive and three original train samples were retrieved and verified; the full large archive was not downloaded blindly. See the source audit. Unknown regions cannot be treated as trunk-free negatives.

The next round should first align complete-instance/visible-region rules for fences, column shafts, and rocks, add actual nearby and truncated targets, and repair incomplete trunk labels before comparing sampling, resolution, and model size. Fences can also be studied with original semantic masks and ignore-index segmentation, avoiding direct treatment of fragmented connected regions as complete instance boxes; effectiveness still needs measurement. ADE validation was still improving in the final epoch, so convergence was not established, but longer training alone cannot replace these annotation repairs. Test data already used for diagnosis remains regression data; the next release selection needs a separate independent-location test.

Phone frame rate, continuous-video first-detection time/longest miss, false positives per minute, speech-onset latency, interruptions, and user-path conflict remain unmeasured by this static-data round.

See the [public-data audit](public-obstacle-sources-20260926.md) and [ROADWork import](roadwork-import-20260926.md) for sources and licenses.
