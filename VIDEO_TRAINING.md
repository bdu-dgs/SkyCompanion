# Local Video Training

All **72 classes** have been restored as most recently requested by the user, with no further class removal or merging. Class IDs in `street_classes.json` remain unchanged; `active_training.json` and `TRAINING_STATUS.md` define the current data and run status. The 18-class export is retained only as an inactive historical approach.

The updated export entry point is `assemble_restored72.py`: it retains every frame from the six videos, merges reviewed additions, and includes public material grouped by source, scene, and near-duplicate relationships. Training uses the updated data; validation and test material are excluded from training. Unknown regions remain unknown, and unreviewed candidates are not treated as ground truth.

Training and prediction checks read the dataset's `schema.json` and validate class order. The current run uses `--resume-checkpoint` to restore the optimizer, EMA, and epoch from the epoch-8 checkpoint, continuing at epoch 9. `--epochs 15` means 15 epochs in total, not 15 additional epochs. After training, only weights and logs are saved; the test set is not run.

Actual launch command (already running at the time of this record; do not launch a duplicate):

```sh
/Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/backend/.venv/bin/python video_training.py train \
  --data local_training/collection_20260926/reviewed72_v2 \
  --resume-checkpoint local_training/collection_20260926/reviewed_v1/runs/six_videos_v1_mpsfix/weights/last.pt \
  --device mps --imgsz 640 --batch 16 --epochs 15 --name street72_resume_epoch9_to15
```

The original 20-epoch command below is historical.

## Original 72-Class Workflow and Historical Run

This workflow follows the repository's YOLO-World training approach, adding a full-frame data index, visual review records, class extensions, and handling for incomplete annotations. The six videos were jointly exported as a partially annotated version with 7,662 frames and 133,598 confirmed boxes; 43 classes in the 72-class vocabulary had confirmed positive examples. See `TRAINING_STATUS.md` for current progress; the corresponding run's `*_result.json` is authoritative for actual results.

## Data and Annotations

- Original material: 133.55 seconds, 20 fps, 960×544, totaling 2,671 frames. `local_training/wechat-20260926/frames.jsonl` preserves actual PTS, original image paths, and SHA256.
- The five additional videos contain 349, 1,356, 1,100, 1,562, and 624 frames, respectively, at 1270/1280×720 and 30 fps. The six videos total 7,662 frames; the manifest is `local_training/collection_20260926/collection.json`, and the original MP4 files are stored separately.
- All 7,662 original images are retained for training. Adjacent frames are not randomly assigned to a supposedly independent test set.
- `street_classes.json` defines 72 classes; the first 8 IDs match upstream. Added classes include shrubs/hedges and cover people, vehicles, tree trunks, poles, bollards, curbs, planters, street furniture, construction objects, open door leaves, exposed pipes, and more. A vocabulary entry does not imply the existence of training examples for that class.
- `annotation_v2/` contains candidate boxes from three local models, retaining their unreviewed status. It used the old 67-class vocabulary when run; ground birds, handheld umbrellas, utility cabinets, and exposed pipes were introduced through subsequent visual review. Original candidates do not automatically become ground truth.
- `reviews/part1`, `part2`, and `part3` preserve per-frame viewing evidence, track anchors, confirmed boxes, uncertain regions, and explicit counterexamples. Linear interpolation is only a geometry proposal; identity and boundaries must be checked after occlusion, leaving the frame, and camera turns.
- `reviewed_examples/` contains single-frame correction examples, not proof that review of the entire video is complete. Specific corrections address an unannotated central tree, a closed window mistaken for an open door, a tree pit mistaken for an open manhole, missed poles, and truncated bases.

## Training Rules

When unresolved instances remain, data is explicitly marked `assistant_reviewed_partial`. `reviewed_loss.py` preserves standard box regression and DFL, masking only negative classification terms for unreviewed background. Confirmed targets retain foreground classification comparisons; explicitly reviewed local counterexamples still participate in training. Unknown background does not automatically become evidence of "no obstacle" merely because labels are absent.

Geometric augmentation is disabled so that reviewed regions in original images map accurately to training inputs. Class text order is fixed to prevent random class reordering from misaligning the mask during training. Data, the class list, reviewed regions, and label files are bound to digests and must be re-exported after changes.

The production training run `six_videos_v1_mpsfix` uses the original repository's `yolov8s-worldv2.pt`, AdamW, learning rate 0.0003, the first 10 layers frozen, input size 640, batch 16, and 20 epochs. It uses fixed final-epoch weights rather than presenting fit scores on the same videos as independent validation for model selection. Training does not modify SkyCompanion's live weights.

## Local Entry Points

The Python environment is `/Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/backend/.venv/bin/python`. Run from this repository directory; MPS requires host GPU access.

```sh
# Export after genuine review of all six videos; each sample_id combines video_id and original frame number.
# Missing frames, duplicate names, invalid boundaries, or incomplete review records block export; existing versions cannot be overwritten.
/Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/backend/.venv/bin/python assemble_reviewed_dataset.py \
  --collection local_training/collection_20260926/collection.json

# Training verifies input digests and rejects raw pseudo-label data.
/Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/backend/.venv/bin/python video_training.py train \
  --data local_training/collection_20260926/reviewed_v1 \
  --device mps --imgsz 640 --batch 16 --epochs 20 --name six_videos_v1_mpsfix

# Generate a local viewer and annotated video with original frames, all-class annotations, and uncertain regions.
/Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/backend/.venv/bin/python review_artifacts.py \
  local_training/collection_20260926/reviewed_v1/annotations.jsonl --video

# Measure only recall of confirmed positives and false positives on explicit counterexamples in the training videos.
/Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/backend/.venv/bin/python evaluate_reviewed_fit.py \
  --data local_training/collection_20260926/reviewed_v1 \
  --weights local_training/collection_20260926/reviewed_v1/six_videos_v1_mpsfix_candidate.pt
```

Reviewing predictions on training videos does not measure independent accuracy; predictions for incompletely annotated content are not counted as false positives. Classes with zero positives, unresolved instances, and unfinished items must be listed separately in the delivery report.
