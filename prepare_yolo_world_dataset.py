"""Extract annotation-ready stills from walking video without touching the source."""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent
CLASSES = ["bicycle", "streetlight", "railing", "bus_stop_shelter", "tree",
           "traffic_light_red", "traffic_light_green", "utility_pole"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=ROOT / "walking video.mp4")
    parser.add_argument("--output", type=Path, default=ROOT / "datasets" / "yolo_world_sidewalk")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between extracted frames")
    args = parser.parse_args()
    if args.interval <= 0 or not args.video.is_file():
        parser.error("video must exist and interval must be positive")
    image_dir = args.output / "images" / "pending"
    image_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {args.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    stride = max(1, round(fps * args.interval))
    saved = 0
    skipped = 0
    for frame_id in range(0, total, stride):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
        ok, frame = cap.read()
        if not ok:
            continue
        timestamp = frame_id / fps
        path = image_dir / f"frame_{frame_id:06d}_t{timestamp:07.2f}.jpg"
        if path.exists():
            skipped += 1
            continue
        if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 94]):
            raise OSError(f"Could not write {path}")
        saved += 1
    cap.release()
    labels_dir = args.output / "labels" / "pending"
    labels_dir.mkdir(parents=True, exist_ok=True)
    (args.output / "classes.txt").write_text("\n".join(CLASSES) + "\n", encoding="utf-8")
    print(f"Extracted {saved} new frames; kept {skipped} existing frames in {image_dir}")
    print(f"Source video duration: {total / fps:.1f}s; sampling interval: {args.interval:g}s")
    print("Next: python annotate_yolo_world.py")


if __name__ == "__main__":
    main()
