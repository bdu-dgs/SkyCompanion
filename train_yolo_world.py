"""Fine-tune YOLO-World after annotating and splitting the sidewalk dataset."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / ".deps"))
sys.path.insert(0, str(ROOT / ".deps_overlay"))
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT))

from ultralytics import YOLOWorld

CLASSES = ["bicycle", "streetlight", "railing", "bus_stop_shelter", "tree",
           "traffic_light_red", "traffic_light_green", "utility_pole"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "datasets" / "yolo_world_sidewalk")
    parser.add_argument("--weights", type=Path, default=ROOT / "yolov8s-worldv2.pt")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--device", default="cpu", help="use cpu or specify a CUDA device such as 0")
    args = parser.parse_args()
    train_images, val_images = args.data / "images" / "train", args.data / "images" / "val"
    train_labels, val_labels = args.data / "labels" / "train", args.data / "labels" / "val"
    required = [train_images, val_images, train_labels, val_labels, args.weights]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        parser.error("dataset split or pretrained YOLO-World weights missing: " + ", ".join(missing))
    if not list(train_images.glob("*.jpg")) or not list(val_images.glob("*.jpg")):
        parser.error("train and val image folders must both contain JPG images")
    for split, images_dir, labels_dir in (("train", train_images, train_labels), ("val", val_images, val_labels)):
        images = list(images_dir.glob("*.jpg"))
        missing_labels = [p.stem for p in images if not (labels_dir / f"{p.stem}.txt").is_file()]
        if missing_labels:
            parser.error(f"{split}: {len(missing_labels)} images have no label file; use the annotation UI and save every frame")

    yaml_path = args.data / "data.yaml"
    names_yaml = "\n".join(f"  {i}: {name}" for i, name in enumerate(CLASSES))
    yaml_path.write_text(f"path: {args.data.resolve().as_posix()}\ntrain: images/train\nval: images/val\nnames:\n{names_yaml}\n",
                         encoding="utf-8")
    model = YOLOWorld(str(args.weights))
    model.train(data=str(yaml_path), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                device=args.device, project=str(ROOT / "run" / "yolo_world_finetune"), name="sidewalk_obstacles",
                exist_ok=False, workers=0)


if __name__ == "__main__":
    main()
