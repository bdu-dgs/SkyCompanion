# SkyCompanion Walking Video Training Dataset

This directory contains training data created from `walking video.mp4`. The original video is unchanged, and one frame per second is extracted by default. There are currently 134 images awaiting annotation. Existing annotations were cleared; the images and `classes.txt` are retained.

## Annotation Classes

| YOLO ID | Key | Class | Annotation scope |
|---:|---:|---|---|
| 0 | 1 | bicycle | The entire bicycle, including parked bicycles |
| 1 | 2 | streetlight | The streetlight pole and lamp head as one object |
| 2 | 3 | railing | Sidewalk railings and guardrails |
| 3 | 4 | bus_stop_shelter | The entire bus shelter, not only the sign |
| 4 | 5 | tree | Visible trees |
| 5 | 6 | traffic_light_red | The motor-vehicle traffic-light head when the red light is on |
| 6 | 7 | traffic_light_green | The motor-vehicle traffic-light head when the green light is on |
| 7 | 8 | utility_pole | A utility or communications pole, not a streetlight pole |

Distinguish streetlights and utility poles by appearance. Keep existing class IDs 0–6 unchanged; the new `utility_pole` class uses ID 7 so that existing labels do not shift.

## Annotate from Scratch

Open PowerShell in the project root. Run this the first time you prepare images or fill in missing extracted frames:

```powershell
python prepare_yolo_world_dataset.py --interval 1
```

This command preserves existing images and does not overwrite them. Then start the annotator:

```powershell
python annotate_yolo_world.py
```

Frame-by-frame workflow:

1. Hold the left mouse button and drag in an empty area to draw a box around each visible target; press `1`–`8` to select a class. If a target is occluded or only partly visible, box the visible portion.
2. Press `M` to annotate the roadway area. Click each point along the roadway boundary, then right-click or press Enter to close the polygon. Include only the roadway; exclude sidewalks, bike lanes, parking lots, and driveways.
3. If the roadway boundary is unclear or occluded, press `U` to outline an uncertain region; those pixels are ignored during roadway-model training.
4. Press `S` to save the current frame, then `N` to move to the next frame. Press `P` to return to the previous frame. If there are unsaved changes, the annotator requires you to save first.

To correct boxes: drag a box to move it; click a box and press a class number to change its class; right-click to delete it. `Z` undoes the last box or polygon point, `X` cancels an open polygon, and `Q` exits.

**Press `S` to save every frame.** Even if a frame contains none of the objects above, save an empty object-label file and annotate the visible roadway area. Otherwise, the split script refuses to start training. YOLO-World uses object boxes to learn bicycles, streetlights, utility poles, railings, bus shelters, trees, and traffic lights. The roadway is an irregular region, so train SegFormer with a separate polygon mask; do not replace the roadway area with one YOLO rectangle.

## After Annotation: Split and Train

After the annotator has processed every image and you have pressed `S` on every frame, run this from PowerShell in the project root:

```powershell
$env:KMP_DUPLICATE_LIB_OK = 'TRUE'
python split_yolo_world_dataset.py
python train_yolo_world.py --weights .\yolov8s-worldv2.pt --epochs 50 --imgsz 640 --batch 4 --device cpu
python train_road_lane_segmenter.py --epochs 20 --batch 1 --device cpu
```

`split_yolo_world_dataset.py` splits complete 10-second video segments into train and validation sets, reducing leakage from adjacent frames appearing in both sets. YOLO-World weights are written to `run/yolo_world_finetune/sidewalk_obstacles`; the roadway model is written to `run/road_lane_finetune/segformer_b0`. The current environment uses the CPU. If a compatible CUDA build of PyTorch is installed, change `--device cpu` to `--device 0` for YOLO and change the SegFormer option to `--device cuda`.

A single walking video provides limited scene coverage. First inspect validation results and annotated videos, then recheck the model with data from other streets, lighting conditions, and viewpoints. Recognizing a traffic light does not mean that crossing is safe.
