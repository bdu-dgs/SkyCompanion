"""Fine-tune Cityscapes SegFormer to segment the annotated motor-vehicle lane."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random

import cv2
import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from transformers import AutoImageProcessor, SegformerForSemanticSegmentation

ROOT = Path(__file__).resolve().parent
BASE_MODEL = "nvidia/segformer-b0-finetuned-cityscapes-1024-1024"


class RoadLaneDataset(Dataset):
    def __init__(self, data: Path, split: str, processor, train: bool = False):
        self.images = sorted((data / "images" / split).glob("*.jpg"))
        self.masks = data / "lanes" / split
        self.processor = processor
        self.train = train
        if not self.images:
            raise ValueError(f"No {split} images found")
        for path in self.images:
            mask = self.masks / f"{path.stem}.png"
            if not mask.is_file():
                raise ValueError(f"Missing lane mask: {mask}")

    def __len__(self):
        return len(self.images)

    def __getitem__(self, index):
        path = self.images[index]
        image = Image.open(path).convert("RGB")
        mask_path = self.masks / f"{path.stem}.png"
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ValueError(f"Could not read {mask_path}")
        unknown_values = set(np.unique(mask).tolist()) - {0, 1, 255}
        if unknown_values:
            raise ValueError(f"{mask_path.name} contains values outside 0, 1, 255: {unknown_values}")
        if self.train and random.random() < 0.5:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            mask = cv2.flip(mask, 1)
        pixel_values = self.processor(images=image, return_tensors="pt")["pixel_values"][0]
        target_h, target_w = pixel_values.shape[-2:]
        target = cv2.resize(mask, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
        return pixel_values, torch.from_numpy(target.astype(np.int64)), path.name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "datasets" / "yolo_world_sidewalk")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    args = parser.parse_args()
    if args.epochs < 1 or args.batch < 1:
        parser.error("epochs and batch must be positive")

    processor = AutoImageProcessor.from_pretrained(BASE_MODEL, do_reduce_labels=False)
    train_data = RoadLaneDataset(args.data, "train", processor, train=True)
    val_data = RoadLaneDataset(args.data, "val", processor)
    train_loader = DataLoader(train_data, batch_size=args.batch, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_data, batch_size=args.batch, shuffle=False, num_workers=0)
    id2label = {0: "not_motor_vehicle_lane", 1: "motor_vehicle_lane"}
    label2id = {value: key for key, value in id2label.items()}
    model = SegformerForSemanticSegmentation.from_pretrained(
        BASE_MODEL, num_labels=2, id2label=id2label, label2id=label2id,
        ignore_mismatched_sizes=True,
    ).to(args.device)
    model.config.semantic_loss_ignore_index = 255
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)

    output = ROOT / "run" / "road_lane_finetune" / "segformer_b0"
    output.mkdir(parents=True, exist_ok=False)
    best_iou = -1.0
    history = []
    for epoch in range(args.epochs):
        model.train()
        train_losses = []
        for pixels, labels, _ in train_loader:
            pixels, labels = pixels.to(args.device), labels.to(args.device)
            optimizer.zero_grad(set_to_none=True)
            loss = model(pixel_values=pixels, labels=labels).loss
            loss.backward()
            optimizer.step()
            train_losses.append(float(loss.detach().cpu()))

        model.eval()
        val_losses, intersection, union = [], 0, 0
        with torch.inference_mode():
            for pixels, labels, _ in val_loader:
                pixels, labels = pixels.to(args.device), labels.to(args.device)
                result = model(pixel_values=pixels, labels=labels)
                val_losses.append(float(result.loss.cpu()))
                pred = torch.nn.functional.interpolate(result.logits, size=labels.shape[-2:],
                                                       mode="bilinear", align_corners=False).argmax(1)
                valid = labels != 255
                intersection += int(((pred == 1) & (labels == 1) & valid).sum().cpu())
                union += int((((pred == 1) | (labels == 1)) & valid).sum().cpu())
        lane_iou = intersection / union if union else 0.0
        record = {"epoch": epoch + 1, "train_loss": float(np.mean(train_losses)),
                  "val_loss": float(np.mean(val_losses)), "lane_iou": lane_iou}
        history.append(record)
        print(json.dumps(record))
        if lane_iou > best_iou:
            best_iou = lane_iou
            model.save_pretrained(output / "best")
            processor.save_pretrained(output / "best")
    (output / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    print(json.dumps({"best_lane_iou": best_iou, "model_dir": str(output / "best"),
                      "warning": "Relative lane proximity only; not a metric-distance estimate."}, indent=2))


if __name__ == "__main__":
    main()
