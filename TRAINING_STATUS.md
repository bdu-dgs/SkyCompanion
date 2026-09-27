# Current Status: 72 Classes, 15 Total Training Epochs Completed

Results verified on 2026-09-27: training successfully completed 15 total epochs, final weights were saved, and the test set was not run.

As most recently requested by the user, all 72 classes are retained without further removal. Training resumed from `last.pt` after epoch 8 of the original 72-class run and stopped at epoch 15 in total; **it did not restart for 15 new epochs**. The test set is not run after training at this stage.

## Actual Resume State

- Model: YOLOv8s / YOLO-World v2; device: local MPS.
- Current run: `street72_resume_epoch9_to15`, data directory `local_training/collection_20260926/reviewed72_v2/`. The run JSON and logs in that directory are authoritative for actual progress and success/failure.
- The checkpoint represents the end of epoch 8; unsaved epoch-9 mini-batches are repeated from the start of that epoch. Seven epochs remained: 9–15.
- `runs/street72_resume_epoch9_to15/resume_state.json` confirms start=9, total=15, restoration of 138 optimizer state entries, and EMA update count 1297 matching the original checkpoint exactly. The original checkpoint is preserved and new output is saved separately.
- Epochs 1–8 used the original six-video dataset; epochs 9–15 used the version with additional annotations and public training material. Class IDs remain unchanged. The total epoch target was reduced from 20 to 15; subsequent learning rates follow the 15-epoch schedule.
- No test-set prediction, test metrics, or test acceptance run is started; weights and logs are saved after training. The current workflow also does not use a partially annotated validation set for automatic model selection, and final-epoch weights are not represented as an independently validated best model.

## Current Data

- **All 7,662 frames from the original six videos are retained**, with 139,062 confirmed boxes after merging genuine reviewed additions.
- Public material totals 472 images: 352 training, 64 validation candidates, and 56 test candidates, with a fixed split across 401 source groups. The 68 historical SkyCompanion development images are included only in training.
- The combined training set has **8,014 images and 139,536 confirmed boxes**. The vocabulary remains 72 classes: 58 have training positives, while 14 currently have no verified positive examples. Those classes are retained without inflating counts using unverified candidates.
- Classes with no training positives yet: rock, parking_meter, suitcase, shopping_cart, wheelchair, walker, skateboard, scaffolding, ladder, cable, patio_umbrella, vending_machine, box, statue.
- video03 merges 2,086 additional tree-trunk boxes and precisely removes 100 invalid old boxes; video01 replaces 7 old boxes; video05 corrects 250 unknown-region positions. All confirmed fine-grained classes are retained; the 18-class filter was not applied.
- Unknown regions, explicit local counterexamples, and partial-annotation status are preserved. The public holdout is a partially annotated candidate holdout; it cannot directly support a claim of 72-class mAP or successful independent acceptance using complete scene ground truth.

## Verification and Entry Points

SHA checks matched all 7,662 original images; actual decoded dimensions matched all 472 public images; label digests matched all 8,014 training images. The 22 export/masking/MPS checks and 3 resume-protection checks passed. Actual runtime restoration of the epoch, optimizer, and EMA state was checked.

- Current entry point: `active_training.json`.
- Data and provenance audits: `reviewed72_v2/dataset_audit.json`, `split_manifest.json`, `public_group_audit.json`.
- Export script: `assemble_restored72.py`.
- The original `reviewed_v1` and inactive `reviewed_core18_v1` are both retained; original material and historical records are not deleted. SkyCompanion's live weights were not modified.

Outstanding: qualified examples for the remaining 14 classes, review of distant small/occluded targets, and subsequent validation. Test execution awaits a subsequent explicit user instruction and does not run automatically.
