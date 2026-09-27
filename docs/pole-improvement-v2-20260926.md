# Second Pole Improvement Round · 2026-09-26

Status: 30 training epochs and the fixed comparison are complete. The candidate was not deployed and live v7 remains unchanged. The user's main goal is to improve missed nearby poles; no static research score is treated as successful field validation for blind mobility assistance.

## Identified Problems and Changes in This Round

1. Of the publisher's 2,001 training images, only 133 have pole annotations, with 199 pole boxes; 1,774 images are empty-label images (88.66%). A fixed spot check of 12 empty-label originals found two clearly visible unannotated utility poles; their entries in the publisher's original COCO file were also empty. Inconsistent class scope for streetlights/signposts was also observed. See the [visual data audit](pole-data-audit-20260926.md). The 2/12 finding was not treated as the dataset-wide missing-label rate.
2. The last few epochs of the previous run were still improving, so 10 epochs do not represent the model's limit. Lamp arms that enlarge boxes also obscure how thin the actual pole shaft is. Adjusting confidence alone, or claiming to increase a class "weight," does not establish a fix.
3. The derived research set changes only train: it excludes 10 cross-split perceptual-hash near-duplicate candidates and separately quarantines 52 empty-label images whose filenames lack negative_ (one overlaps the first group; the total suspicious empty-label group has 53 images). This is a conservative heuristic, not a claim that every image has confirmed missing labels.
4. All remaining 223 images with any positive annotation are retained, with 223 candidate negatives selected using fixed seed 20260926. Unselected originals and all labels are preserved. A negative_ filename does not guarantee no missing annotations; this round did not clean every image individually.
5. Training restarts from the original COCO YOLO11n weights to avoid inheriting learning from images now quarantined. Configuration: 30 epochs, 640, batch8, AdamW lr0=.001, mosaic=.25, scale=.25, close_mosaic=5, patience10, MPS. This is a combined multi-factor study, not an isolated demonstration of each factor's causal contribution.

Derived set: `backend/data/obstacle_dataset/pole-balanced-v2-20260926/dataset.json`. Original train/val/test IDs, image hashes, and labels are versioned; the 996 validation and 503 test images are unchanged. Publisher location/route independence remains unknown, and the old test set was used in the previous round, so this is only a repeated regression comparison.

## Comparison Protocol

- Compare 640/960 and the predefined threshold list on val, locking the best pole F1 point. Also select the highest-recall point with val precision >= 80%; explicitly report if none is attainable. The 80% point is an additional research operating point, not safety certification or automatic deployment authorization.
- Save predictions for every validation image to investigate misses, rather than keeping summaries alone. Process test images only after locking operating points.
- Compare against v1 and live v7 on the same publisher test set; report TP/FP/FN, precision, recall, and static inference timing with the differing configurations. Pure inference FPS must not be presented as phone closed-loop FPS.
- Separately review 5 local original images from 3 clips, containing 5 pole shafts and 6 building-column shafts. Both assistants viewed the originals; this is not described as human review, and the images were not added to training. Boxes cover only visible shafts and bases, excluding lamp globes/signs/crossarms. Report only selected-target hits and best compatible IoU; unannotated objects are not false positives, and full-frame precision is not invented. Some HOT boxes cover entire lighting assemblies, so the scope difference must be disclosed.
- A two-class pole/tower candidate cannot directly replace the 115-class general model. Using it as a supplementary detector would still require actual improvement on local close-range scenes and false-positive checks; no deployment changes were made to cloud or phone models or automatic speech.

Local target manifest: `backend/data/obstacle_experiments/pole-v2-audit/local-regression-targets-reviewed-v2.json`. Unknown classes/regions remain unknown.

## Reproduction Entry Points

```sh
backend/.venv/bin/python scripts/prepare_pole_rebalance.py backend/data/obstacle_dataset/public-hotosm/dataset.json --duplicate-audit backend/data/obstacle_dataset/public-hotosm/near-duplicate-audit.json --output NEW_DATASET.json
backend/.venv/bin/python scripts/train_obstacles.py NEW_DATASET.json --output NEW_RUN --model backend/data/models/yolo11n.pt --epochs 30 --patience 10 --batch 8 --imgsz 640 --device mps --optimizer AdamW --lr0 .001 --mosaic .25 --scale .25 --close-mosaic 5 --seed 20260926 --research-published --run
backend/.venv/bin/python scripts/evaluate_pole_candidate.py backend/data/obstacle_dataset/public-hotosm/dataset.json --candidate NEW_RUN/runs/candidate/weights/best.pt --output NEW_EVALUATION
```

Tool parameters follow the installed Ultralytics 8.4.37 implementation and were checked against the [official training documentation](https://docs.ultralytics.com/modes/train/). Running dependencies were not upgraded.

## Actual Results

The best pole F1 operating point was selected only on val: 960 / conf 0.25, val precision 45.38%, recall 46.73%. Weight SHA256: `9c506b938090f80f365d1a6c05570286be477c520b92c20e30ee10236ae4f61b`.

| Candidate (each tuned on val) | test TP / FP / FN | pole precision | pole recall |
|---|---|---|---|
| General v7: 960 / .10 | 32 / 327 / 241 | 8.9% | 11.7% |
| Specialist v1: 640 / .05 | 82 / 164 / 191 | 33.3% | 30.0% |
| Specialist v2: 960 / .25 | 125 / 151 / 148 | 45.3% | 45.8% |

Relative to v1, v2 increases recall by 15.8 percentage points and precision by 12.0 percentage points, but still misses approximately 54% of annotated poles. MPS serial single-image inference (including postprocessing): P50 16.43 ms, P95 25.98 ms, mean 56.9 fps. This is neither phone/drone end-to-end frame rate nor announcement latency.

Another operating point reached val precision 90% (960/.80), but test precision fell to 63.6% with only 2.6% recall (7 TP / 4 FP / 266 FN). A validation threshold cannot guarantee deployment precision.

Per-target diagnosis of 505 validation poles: 236 have compatible boxes at the current threshold and IoU>=.5; 186 have matching boxes in the lower-threshold returned list; 71 have no match among outputs at conf>=.01; 11 are localization/box-scope mismatch candidates; and 1 overlaps another class. This diagnosis is not one-to-one scoring and cannot be mixed with formal TP counts; lowering the threshold does not remove the false-positive cost.

Local close-range regression: v7, v1, and v2 all hit 0 of the 5 selected pole shafts and 0 of the 6 selected column shafts, with best compatible IoU 0 throughout. This specialist trains only pole/tower, not building columns; public-set improvements did not solve nearby streetlights, signposts, or building columns. Therefore this round is not deployed, and this model is not used for more confident risk announcements.

The next round needs consistent box definitions for "shaft/whole lighting assembly," genuine close-range, truncated, occluded, and column-shaft annotations, and independent-location data. Expanding conf or increasing class scores cannot accomplish this. The 11 repeatedly inspected targets were not quietly added to training or used as an independent acceptance set.

Result entry points:

- `backend/data/obstacle_training/pole-balanced-v2-20260926/evaluation/report.json`
- `backend/data/obstacle_training/pole-balanced-v2-20260926/evaluation/val-miss-diagnostic.json`
- `backend/data/obstacle_experiments/pole-v2-audit/local-v2-evaluation/report.json`
