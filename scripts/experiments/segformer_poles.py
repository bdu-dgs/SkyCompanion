#!/usr/bin/env python3
"""Local, diagnostic SegFormer pole segmentation; never uploads input images.

Screenshots carry existing overlays and are explicitly excluded as clean ground truth.
No morphology, object-category relabeling, or GT scoring is performed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / "backend/data/models/hf-cache"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import cv2
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

REPO = "nvidia/segformer-b0-finetuned-cityscapes-1024-1024"
REVISION = "21b3847fae21ddee674abd31129307b6a1235bd9"
CLASSES = {5: "pole", 6: "traffic light", 7: "traffic sign", 8: "vegetation"}
COLORS = {5: (255, 20, 220), 6: (40, 230, 255), 7: (255, 210, 20), 8: (35, 210, 60)}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    clean = [
        ("clean-thin-signpost", "20260925-215027-5f22ede2", 3003),
        ("clean-thick-traffic-pole", "20260925-215256-ad66dbd3", 5181),
        ("clean-case-6880", "20260925-215445-9d1990d5", 6880),
    ]
    for name, case, frame in clean:
        path = ROOT / "backend/data/obstacle_cases" / case / f"{frame:08d}-input.png"
        yield name, Image.open(path).convert("RGB"), {
            "source": str(path), "source_sha256": digest(path),
            "clean_input": True, "ground_truth": False,
        }
    for stamp in ("9.49.43", "9.49.53", "9.50.17"):
        matches = list(Path("/Users/stanley/Desktop").glob(f"Screenshot 2026-09-25 at {stamp}*pm.png"))
        if len(matches) != 1:
            continue
        path = matches[0]
        crop = [32, 356, 1344, 1093]
        im = Image.open(path).convert("RGB").crop(crop).resize((791, 443), Image.Resampling.LANCZOS)
        yield "screenshot-" + stamp.replace(".", "-"), im, {
            "source": str(path), "source_sha256": digest(path), "crop_ltrb": crop,
            "resize_wh": [791, 443], "clean_input": False, "ground_truth": False,
            "limitation": "Screenshot with existing prediction/UI overlays; diagnostic only.",
        }
    path = Path("/var/folders/5b/h8jvf2cj5vs26dcxp6mwdgy00000gn/T/codex-clipboard-7a76fc7d-a57e-48e5-8d85-0e8515ec4e81.png")
    if path.exists():
        crop = [32, 9, 1344, 746]
        im = Image.open(path).convert("RGB").crop(crop).resize((791, 443), Image.Resampling.LANCZOS)
        yield "screenshot-white-column", im, {
            "source": str(path), "source_sha256": digest(path), "crop_ltrb": crop,
            "resize_wh": [791, 443], "clean_input": False, "ground_truth": False,
            "limitation": "Screenshot with existing prediction/UI overlays; diagnostic only.",
        }


def sync(device):
    if device == "mps":
        torch.mps.synchronize()


def predict(model, processor, image, size, device):
    values = processor(images=image, size={"height": size, "width": size}, return_tensors="pt")
    values = {k: v.to(device) for k, v in values.items()}
    with torch.inference_mode():
        logits = model(**values).logits
        logits = F.interpolate(logits, size=(image.height, image.width), mode="bilinear", align_corners=False)
        probabilities = logits.softmax(1)[0].cpu().numpy()
    return probabilities.argmax(0).astype(np.uint8), probabilities


def export(image, labels, probabilities, dest):
    dest.mkdir(parents=True, exist_ok=True)
    rgb = np.array(image)
    overlay = rgb.copy()
    Image.fromarray(labels).save(dest / "labelmap.png")
    Image.fromarray((labels == 5).astype(np.uint8) * 255).save(dest / "pole-mask.png")
    np.save(dest / "pole-probability.npy", probabilities[5])
    components = []
    for class_id, label in CLASSES.items():
        mask = labels == class_id
        color = np.array(COLORS[class_id], dtype=np.float32)
        overlay[mask] = (rgb[mask] * .45 + color * .55).astype(np.uint8)
        count, connected, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        for index in range(1, count):
            x, y, w, h, area = map(int, stats[index])
            scores = probabilities[class_id][connected == index]
            component = {"label": label, "class_id": class_id, "component_id": index,
                         "xywh": [x, y, w, h], "area_px": area,
                         "mean_pixel_probability": float(scores.mean()),
                         "max_pixel_probability": float(scores.max()),
                         "is_object_instance": False}
            components.append(component)
            if area >= 12 and class_id != 8:
                cv2.rectangle(overlay, (x, y), (x + w - 1, y + h - 1), COLORS[class_id], 1)
                cv2.putText(overlay, f"{label} #{index}", (x, max(12, y - 3)), cv2.FONT_HERSHEY_SIMPLEX, .33, COLORS[class_id], 1, cv2.LINE_AA)
    Image.fromarray(overlay).save(dest / "overlay.png")
    Image.fromarray(np.concatenate([rgb, overlay], axis=1)).save(dest / "comparison.png")
    image.save(dest / "input.png")
    (dest / "components.json").write_text(json.dumps(components, indent=2))
    return components


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="+", default=[512, 1024])
    parser.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--output", type=Path, default=ROOT / "backend/data/obstacle_experiments/segformer")
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    model_path = Path(os.environ["HF_HOME"]) / "hub/models--nvidia--segformer-b0-finetuned-cityscapes-1024-1024/snapshots" / REVISION
    # Local-only checkpoint; installed transformers/torch performs weights-only loading.
    processor = SegformerImageProcessor.from_pretrained(model_path, local_files_only=True)
    model = SegformerForSemanticSegmentation.from_pretrained(model_path, local_files_only=True, weights_only=True).eval().to(args.device)
    metadata = {"repo": REPO, "revision": REVISION, "weights_sha256": digest(model_path / "pytorch_model.bin"),
                "id2label": model.config.id2label, "processor_default_size": processor.size,
                "device": args.device, "threads": args.threads, "torch": torch.__version__,
                "timing": "preprocess + forward + full-resolution bilinear logits + softmax + argmax, excluding disk IO; warmed; shared machine",
                "accuracy": "unmeasured; predictions only, no ground truth", "results": []}
    samples = list(inputs())
    args.output.mkdir(parents=True, exist_ok=True)
    for size in args.sizes:
        predict(model, processor, samples[0][1], size, args.device)
        for name, image, provenance in samples:
            times = []
            for _ in range(args.repeats):
                sync(args.device)
                start = time.perf_counter()
                labels, probabilities = predict(model, processor, image, size, args.device)
                sync(args.device)
                times.append((time.perf_counter() - start) * 1000)
            dest = args.output / f"{args.device}-{size}" / name
            components = export(image, labels, probabilities, dest)
            result = {"name": name, **provenance, "input_wh": [image.width, image.height], "model_input_hw": [size, size],
                      "timing_ms": times, "p50_ms": float(np.median(times)), "fps_mean": 1000 / float(np.mean(times)),
                      "pole_pixels": int((labels == 5).sum()),
                      "pole_components_ge12px": [c for c in components if c["class_id"] == 5 and c["area_px"] >= 12],
                      "output": str(dest)}
            metadata["results"].append(result)
            (args.output / f"results-{args.device}.json").write_text(json.dumps(metadata, indent=2))
            print(json.dumps({k: result[k] for k in ["name", "model_input_hw", "p50_ms", "fps_mean", "pole_pixels", "pole_components_ge12px"]}), flush=True)


if __name__ == "__main__":
    main()
