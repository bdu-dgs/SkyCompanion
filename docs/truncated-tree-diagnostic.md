# Missed Nearby Truncated Tree Trunk: Comparison on the Same Clean Original Frame

This measurement did not recover the right-hand trunk by lowering the threshold or reducing prompts to `tree` / `tree trunk`. Current results support adding reviewed partial-trunk training examples; they do not support lowering the live threshold directly to 0.05 or claiming that increasing a class weight has fixed the issue.

## Input and Method

- Original frame: `backend/data/obstacle_cases/20260926-012001-324062cf/00017327-input.png`, 960 × 443, retaining the phone's original black borders and containing no old prediction boxes.
- The nearby trunk on the right extends above the image, is partially occluded by a person in the middle, and has a visible base. The reference box `[565, 0, 633, 392]` is an assistant draft, **not human-reviewed and not drawn as a prediction box**.
- The baseline is the current `skycompanion-yoloe-11s-v7.pt` with its 115-class vocabulary, which already includes `tree` and `tree trunk`.
- The two prompt comparisons load the local same-source `yoloe-11s-seg.pt` and use `get_text_pe` / `set_classes` to set only `tree` or only `tree trunk`. No training, new weight downloads, or live configuration changes were performed.
- Each configuration runs at confidence thresholds 0.25, 0.10, and 0.05; `imgsz=960`, NMS IoU 0.7, and class-agnostic NMS. CPU, 2 threads; each configuration is warmed up and then run twice. Timing includes preprocessing, prediction, and postprocessing.
- All amber boxes in the images are actual model outputs. Images were not redrawn and boxes were not added manually. Result JSON preserves the model, input SHA256, all predictions, thresholds, and timings.

## Measured Results

| Configuration | Threshold | Full-frame output boxes | tree / tree trunk outputs | Right-hand target trunk detected? | Median CPU prediction-call time |
|---|---:|---:|---:|---|---:|
| Current v7, 115 classes | 0.25 | 13 | 0 | No | 101.9 ms |
| Current v7, 115 classes | 0.10 | 32 | 0 | No | 108.1 ms |
| Current v7, 115 classes | 0.05 | 50 | 0 | No | 110.5 ms |
| Same source, tree only | 0.25 | 0 | 0 | No | 104.8 ms |
| Same source, tree only | 0.10 | 0 | 0 | No | 106.9 ms |
| Same source, tree only | 0.05 | 0 | 0 | No | 105.1 ms |
| Same source, tree trunk only | 0.25 | 0 | 0 | No | 105.3 ms |
| Same source, tree trunk only | 0.10 | 0 | 0 | No | 104.5 ms |
| Same source, tree trunk only | 0.05 | 0 | 0 | No | 103.5 ms |

Lowering the v7 threshold produced `person` boxes (0.1575, 0.0782) overlapping the draft trunk box, but a person really is occluding the trunk at that position. Box overlap does not establish that the model classified the trunk as a person, and those boxes cannot count as trunk detections. A `concrete block` box at approximately 0.13 also appeared at the bottom; it did not cover the main trunk.

## Supported and Unsupported Conclusions

1. This is not an omitted `tree trunk` class-name issue; the current vocabulary already contains it.
2. In this frame, reducing the threshold from 0.25 to 0.05 still produced no usable tree/trunk output while adding many low-score boxes. This threshold should not be deployed without per-class acceptance checks.
3. Tree-only/trunk-only prompts still produced no output, showing that simply removing other prompts did not fix this frame's missed detection. NMS class competition cannot be identified as the sole cause.
4. This record covers postprocessed detections; **not all raw network tensors were inspected**. It therefore cannot prove that no internal candidate response existed, nor can one frame establish training-data bias as the sole cause.
5. One frame and two calls per configuration do not constitute accuracy, latency, or deployment acceptance. CPU timing does not represent phone performance, live MPS performance, or end-to-end frame rate.

## Next Training and Acceptance Steps

- Separate annotation rules for `whole tree` and `tree trunk`; nearby navigation concerns the actual visible trunk. Preserve top/edge truncation, partial occlusion, and base-visibility attributes without imagining out-of-frame extent.
- Add large trunks extending above the image, trunks with no visible canopy, varied bark and lighting, person occlusion, and confusing negative examples such as nearby columns and utility poles.
- Apply random cropping, scale changes, moderate occlusion, and other augmentation only to training data; clip boxes with crops and check that enough of the target remains visible. Do not retain heavily occluded examples with no visible information as reliable positives.
- Split by video and location. This frame has already been used for diagnosis and approach selection and must remain in a diagnostic regression set; it cannot be called an unseen final blind-test sample.
- Compare trunk-specific misses, false positives, time to first stable detection, and regressions in existing classes such as pedestrians and poles; retain the current live model until acceptance passes.

## Files

- Reproduction script: `scripts/experiments/truncated_tree.py`
- Complete results: `backend/data/obstacle_experiments/truncated-tree/results.json`
- Nine-panel actual-prediction comparison: `backend/data/obstacle_experiments/truncated-tree/comparison.png`
- Individual images: `v7-115-conf-0.25.png` and others in the same directory.
