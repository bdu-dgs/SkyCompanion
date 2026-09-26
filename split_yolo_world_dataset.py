"""Make a time-blocked train/validation split after annotation."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "datasets" / "yolo_world_sidewalk"
BLOCK_SECONDS = 10


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    args = parser.parse_args()
    images = sorted((args.data / "images" / "pending").glob("*.jpg"))
    labels_dir = args.data / "labels" / "pending"
    lanes_dir = args.data / "lanes" / "pending"
    if not images:
        raise SystemExit("No pending images found.")
    missing = [image.name for image in images if not (labels_dir / f"{image.stem}.txt").exists()]
    if missing:
        raise SystemExit(f"{len(missing)} frames are not labeled yet; save a label file for every frame, including empty negatives.")
    missing_lanes = [image.name for image in images
                     if not (lanes_dir / f"{image.stem}.json").is_file()
                     or not (lanes_dir / f"{image.stem}.png").is_file()]
    if missing_lanes:
        raise SystemExit(f"{len(missing_lanes)} frames have no lane polygon/mask; save a lane annotation for every frame.")
    split_images = args.data / "images"
    split_labels = args.data / "labels"
    val_count = 0
    for image in images:
        match = re.search(r"_t([0-9]+(?:\.[0-9]+)?)\.jpg$", image.name)
        if not match:
            raise SystemExit(f"Cannot read timestamp from {image.name}")
        block = int(float(match.group(1)) // BLOCK_SECONDS)
        split = "val" if block % 5 == 4 else "train"
        if split == "val":
            val_count += 1
        sources = ((split_images, image), (split_labels, labels_dir / f"{image.stem}.txt"),
                   (args.data / "lanes", lanes_dir / f"{image.stem}.json"),
                   (args.data / "lanes", lanes_dir / f"{image.stem}.png"))
        for base, source in sources:
            dest = base / split / source.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                raise SystemExit(f"Refusing to overwrite {dest}; move the old split before rebuilding it.")
            shutil.copy2(source, dest)
    print(f"Copied {len(images) - val_count} train and {val_count} validation frames into {args.data}")
    print("Validation uses held-out 10-second time blocks to reduce adjacent-frame leakage.")


if __name__ == "__main__":
    main()
