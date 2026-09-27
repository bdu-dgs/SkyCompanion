#!/usr/bin/env python3
"""Bounded, local Grounding DINO diagnostic; does not change live inference."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / "backend/data/models/hf-cache"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import cv2
import numpy as np
from PIL import Image
import torch
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection

REVISION = "a2bb814dd30d776dcf7e30523b00659f4f141c71"
MODEL_ID = "IDEA-Research/grounding-dino-tiny"
PROMPTS = {
    "all": "pole . pillar . kiosk . chair . table . rock . planter . newsstand . tree trunk . dog .",
    "structures": "pole . pillar . kiosk . newsstand . tree trunk .",
    "objects": "chair . table . rock . planter . dog .",
}
OUT = ROOT / "backend/data/obstacle_experiments/grounding-nearby"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def samples():
    case = ROOT / "backend/data/obstacle_cases/20260925-215027-5f22ede2"
    for name, frame in [("clean-thin-pole", 3003), ("clean-kiosk", 2943)]:
        path = case / f"{frame:08d}-input.png"
        yield name, Image.open(path).convert("RGB"), {
            "source": str(path), "sha256": sha(path), "clean_input": True, "ground_truth": False,
        }
    for stamp in ["9.53.43", "10.00.06", "10.00.30", "10.02.41"]:
        found = list(Path("/Users/stanley/Desktop").glob(f"Screenshot 2026-09-25 at {stamp}*pm.png"))
        assert len(found) == 1, found
        path = found[0]
        crop = (32, 9, 1344, 746) if stamp == "9.53.43" else (32, 419, 1344, 1156)
        im = Image.open(path).convert("RGB").crop(crop).resize((791, 443), Image.Resampling.LANCZOS)
        yield "screenshot-" + stamp.replace(".", "-"), im, {
            "source": str(path), "sha256": sha(path), "crop_ltrb": crop,
            "resize_wh": [791, 443], "clean_input": False, "ground_truth": False,
            "limitation": "Screenshot contains original boxes, text and cursor; diagnostic only.",
        }
    path = Path("/var/folders/5b/h8jvf2cj5vs26dcxp6mwdgy00000gn/T/codex-clipboard-7a76fc7d-a57e-48e5-8d85-0e8515ec4e81.png")
    crop = (32, 9, 1344, 746)
    im = Image.open(path).convert("RGB").crop(crop).resize((791, 443), Image.Resampling.LANCZOS)
    yield "screenshot-white-pillar", im, {
        "source": str(path), "sha256": sha(path), "crop_ltrb": crop,
        "resize_wh": [791, 443], "clean_input": False, "ground_truth": False,
        "limitation": "Screenshot contains original boxes, text and cursor; diagnostic only.",
    }


def boxes_of(pred):
    return [{"label": label, "confidence": float(score), "xyxy": box.tolist()}
            for label, score, box in zip(pred["text_labels"], pred["scores"].cpu(), pred["boxes"].cpu())]


def run(model, processor, im, prompt, size):
    torch.mps.synchronize()
    start = time.perf_counter()
    values = processor(images=im, text=prompt, size={"shortest_edge": size, "longest_edge": 1333}, return_tensors="pt").to("mps")
    torch.mps.synchronize()
    pre_done = time.perf_counter()
    with torch.inference_mode():
        raw = model(**values)
    torch.mps.synchronize()
    forward_done = time.perf_counter()
    predictions, post_ms = {}, {}
    for threshold in [.25, .30]:
        post_start = time.perf_counter()
        pred = processor.post_process_grounded_object_detection(
            raw, values.input_ids, threshold=threshold, text_threshold=.2,
            target_sizes=[im.size[::-1]],
        )[0]
        predictions[str(threshold)] = boxes_of(pred)
        torch.mps.synchronize()
        post_ms[str(threshold)] = (time.perf_counter() - post_start) * 1000
    return predictions, {
        "preprocess_transfer_ms": (pre_done-start)*1000,
        "forward_ms": (forward_done-pre_done)*1000,
        "postprocess_ms": post_ms,
        "pipeline_ms": {k: (forward_done-start)*1000+v for k, v in post_ms.items()},
        "model_tensor_hw": list(values.pixel_values.shape[-2:]),
    }


def overlay(im, boxes, path):
    arr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
    for box in boxes:
        x1,y1,x2,y2 = [int(round(v)) for v in box["xyxy"]]
        color = (40, 140, 255)
        cv2.rectangle(arr, (x1,y1),(x2,y2), color, 2)
        caption = f'{box["label"]} {box["confidence"]:.2f}'
        cv2.putText(arr,caption,(max(0,x1),max(14,y1-4)),cv2.FONT_HERSHEY_SIMPLEX,.4,color,1,cv2.LINE_AA)
    cv2.imwrite(str(path), arr)


def main():
    assert torch.backends.mps.is_available(), "MPS not available; run with local device permission, no silent CPU fallback."
    torch.set_num_threads(4)
    torch.manual_seed(0)
    path = Path(os.environ["HF_HOME"]) / "hub/models--IDEA-Research--grounding-dino-tiny/snapshots" / REVISION
    processor = AutoProcessor.from_pretrained(path, local_files_only=True)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(path, local_files_only=True, weights_only=True).to("mps").eval()
    OUT.mkdir(parents=True, exist_ok=True)
    weights = list(path.glob("*.safetensors")) + list(path.glob("pytorch_model*.bin"))
    report = {"model": MODEL_ID, "revision": REVISION, "weights": {p.name:sha(p) for p in weights},
              "device": "mps", "dtype": "float32", "torch": torch.__version__, "cpu_threads": 4,
              "prompts": PROMPTS, "box_thresholds": [.25,.30], "text_threshold": .2,
              "resize": "shortest_edge varied, longest_edge 1333, preserve aspect ratio; record actual tensor shape",
              "benchmark": "one warmup per size/prompt followed by two runs per image; preprocess+transfer+forward+postprocess; no file I/O/network/audio",
              "limitations": ["No GT scoring", "Screenshots contain overlays", "Single group time is not two-group ensemble time"], "results": []}
    images = list(samples())
    for size in [384, 512, 640]:
        for group,prompt in PROMPTS.items():
            _, warm = run(model, processor, images[0][1], prompt, size)
            print(f"warmup {size} {group}: {warm['forward_ms']:.1f} ms",flush=True)
            for name, im, provenance in images:
                timings = []
                for _ in range(2):
                    predictions, timing = run(model, processor, im, prompt, size)
                    timings.append(timing)
                dest = OUT / f"mps-{size}" / group / name
                dest.mkdir(parents=True,exist_ok=True)
                im.save(dest / "input.png")
                for threshold, boxes in predictions.items():
                    overlay(im, boxes, dest / f"overlay-{threshold}.png")
                row = {"name": name, **provenance, "size": size, "group": group,
                       "timings": timings, "predictions": predictions, "output": str(dest)}
                report["results"].append(row)
                (OUT / "results.json").write_text(json.dumps(report,indent=2))
                print(json.dumps({"name":name,"size":size,"group":group,
                                  "pipeline_p50_ms":float(np.median([t['pipeline_ms']['0.3'] for t in timings])),
                                  "boxes_030":predictions['0.3']}),flush=True)
    summary = []
    for size in [384,512,640]:
        for group in PROMPTS:
            rows = [r for r in report['results'] if r['size']==size and r['group']==group]
            values = [t['pipeline_ms']['0.3'] for r in rows for t in r['timings']]
            summary.append({"size":size,"group":group,"n":len(values),"p50_ms":float(np.median(values)),
                            "p95_ms":float(np.percentile(values,95)),"fps_mean":1000/float(np.mean(values))})
    (OUT / "summary.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2),flush=True)


if __name__ == "__main__":
    main()
