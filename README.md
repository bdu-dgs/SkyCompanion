# SkyCompanion

The repository contains three parts: an iMessage event receiver, YOLO-World training and annotation, and a local video-to-JSONL pipeline with spoken warnings.

## 1. From Video Input to Output

If the `videos` directory contains a dated MP4 file, the program uses the first such file by default; otherwise it falls back to `videos/walking video.mp4`. The default model is `yolov8s-worldv2.pt`. Run this in PowerShell:

```powershell
.\start_sky.cmd
```

You can also specify the video, model, and sampling options:

```powershell
$env:KMP_DUPLICATE_LIB_OK='TRUE'
python sky_companion.py --video ".\videos\walking video.mp4" --model yolov8s-worldv2.pt --display
```

For a rear-facing following view, YOLO-World + ByteTrack locks onto the person who appears continuously near the center of the frame. The system uses the rectangular region above that person's head as the forward scan area and excludes the tracked person from obstacle warnings. Direction is based on the assumption that the top of a rear-facing view is forward; if the camera turns to the side or faces forward, the travel direction must be estimated again. The program processes the video frame by frame and writes `run/frames.jsonl`, `run/report.json`, and, when speech is enabled, `run/audio_events.jsonl`. Press `q` to exit; `--no-audio` disables speech, and `--stdout` also prints each JSON record to the terminal. Current scene and distance results are relative image estimates, not measurements in meters or a guarantee of safe passage.

After training, you can specify the resulting weights:

```powershell
python sky_companion.py --video ".\videos\walking video.mp4" --model run/yolo_world_finetune/sidewalk_obstacles/weights/best.pt --display
```

## 2. YOLO-World Training and Annotation

The complete guide to the dataset, classes, annotation controls, roadway-boundary annotation, and the workflow from empty labels to training is in [datasets/yolo_world_sidewalk/README.md](datasets/yolo_world_sidewalk/README.md). The 134 extracted images kept locally are not included in GitHub. Existing labels were cleared and must be recreated. YOLO-World handles object boxes; roadway boundaries are annotated as independent polygons and trained with a separate segmentation model.

Train YOLO-World:

```powershell
$env:KMP_DUPLICATE_LIB_OK='TRUE'
python split_yolo_world_dataset.py
python train_yolo_world.py --weights .\yolov8s-worldv2.pt --epochs 50 --imgsz 640 --batch 4 --device cpu
```

With NVIDIA CUDA, change `--device cpu` to `--device 0`. See the dataset README for the roadway-boundary segmentation command and prerequisites.

## 3. iMessage

The iMessage API service is documented in [skycompanion/README.md](skycompanion/README.md). It receives events from the phone; video recognition and warnings still need to be integrated into the phone, and the Windows video pipeline is not an iPhone deployment.

## Directory

- `sky_companion.py`, `start_sky.cmd`: video inference, scene rules, JSONL, and local speech output.
- `datasets/yolo_world_sidewalk/`: extracted frames, box annotations, roadway-boundary annotations, and training data.
- `skycompanion/`: iMessage event API.
- `assets/tts/en_short/`: offline English warning audio.
- `weights/clip/`: local CLIP text-encoder weights required by YOLO-World, excluded from GitHub.
