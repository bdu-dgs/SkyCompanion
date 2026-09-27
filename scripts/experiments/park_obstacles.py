#!/usr/bin/env python3
"""One bounded, offline v6/v7 prompt comparison; never modifies live config."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

os.environ["YOLO_AUTOINSTALL"] = "False"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import cv2
import numpy as np
import torch
from ultralytics import YOLOE, __version__

from street_furniture import annotated, detections, sha, save_json

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "backend/data/models"
OUTPUT = ROOT / "backend/data/obstacle_experiments/park"
ADDED = ["statue", "sculpture", "monument"]
CROP = [32, 419, 1344, 1156]


def inputs():
    frames = []
    for stamp in ["10.13.55", "10.13.59", "10.15.09", "10.15.49", "10.00.06", "10.00.30"]:
        matches = list(Path("/Users/stanley/Desktop").glob(f"Screenshot 2026-09-25 at {stamp}*pm.png"))
        assert len(matches) == 1, matches
        source = matches[0]
        image = cv2.imread(str(source))
        assert image is not None and image.shape[0] >= CROP[3] and image.shape[1] >= CROP[2]
        x1, y1, x2, y2 = CROP
        image = cv2.resize(image[y1:y2, x1:x2], (791, 443), interpolation=cv2.INTER_AREA)
        name = "screenshot-" + stamp.replace(".", "-")
        frames.append((name, image, {
            "source": str(source), "source_sha256": sha(source), "crop_xyxy": CROP,
            "contains_existing_overlays": True, "is_ground_truth": False,
            "training_eligible": False, "kind": "annotated_screenshot_diagnostic_only",
        }))
    source = ROOT / "backend/data/obstacle_cases/20260925-215027-5f22ede2/00003003-input.png"
    image = cv2.imread(str(source))
    assert image is not None
    frames.append(("raw-signpost-3003", image, {
        "source": str(source), "source_sha256": sha(source), "crop_xyxy": None,
        "contains_existing_overlays": False, "is_ground_truth": False,
        "training_eligible": False, "kind": "raw_capture",
    }))
    for name, image, info in frames:
        path = OUTPUT / "inputs" / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), image)
        info.update(input_path=str(path), input_sha256=sha(path), input_wh=list(image.shape[1::-1]))
    return frames


def prepare_candidate(names):
    source = MODEL_DIR / "yoloe-11s-seg.pt"
    assert source.is_file() and (MODEL_DIR / "mobileclip_blt.ts").is_file()
    output = MODEL_DIR / "skycompanion-yoloe-11s-v7-candidate.pt"
    assert not output.exists(), "This is a single bounded round; inspect existing output rather than rerunning."
    model = YOLOE(str(source))
    embedding = model.get_text_pe(names)
    model.set_classes(names, embedding)
    model.save(str(output))
    reloaded = YOLOE(str(output))
    assert list(reloaded.names.values()) == names
    assert torch.equal(reloaded.model.pe, embedding)
    save_json(output.with_suffix(".json"), {
        "kind": "pretrained_with_text_prompts_not_finetuned", "vocabulary_version": 7,
        "names": names, "added_to_v6": ADDED,
        "source": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yoloe-11s-seg.pt",
        "source_sha256": sha(source), "sha256": sha(output), "ultralytics": __version__,
        "status": "offline_candidate_not_selected_for_live_service", "training_performed": False,
    })
    return output


def main():
    assert torch.backends.mps.is_available(), "MPS required; no silent CPU fallback."
    torch.set_num_threads(2)
    torch.manual_seed(0)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    os.chdir(MODEL_DIR)
    baseline = MODEL_DIR / "skycompanion-yoloe-11s-v6.pt"
    metadata = json.loads(baseline.with_suffix(".json").read_text())
    assert sha(baseline) == metadata["sha256"]
    names = metadata["names"]
    assert len(names) == len(set(names)) == 112
    assert not set(ADDED) & set(names)
    candidate = prepare_candidate(names + ADDED)
    frames = inputs()
    report = {
        "purpose": "single_round_prompt_diagnostic_not_accuracy_benchmark",
        "device": "mps", "dtype": "float32", "threads": 2,
        "imgsz": 960, "confidence": .25, "iou": .7, "agnostic_nms": True,
        "training_performed": False, "added_to_v6": ADDED,
        "ultralytics": __version__, "torch": torch.__version__,
        "timing_scope": "Synchronized predict call, including preprocess and postprocess; excludes image loading, network and rendering.",
        "models": {}, "inputs": {name: info for name, _, info in frames}, "results": [],
    }
    overlays = {}
    with torch.inference_mode():
        for label, path in [("v6", baseline), ("v7", candidate)]:
            model = YOLOE(str(path))
            report["models"][label] = {"path": str(path), "sha256": sha(path), "names": model.names}
            kwargs = dict(imgsz=960, conf=.25, iou=.7, device="mps", verbose=False, agnostic_nms=True)
            for _ in range(2):
                model.predict(frames[0][1], **kwargs)
                torch.mps.synchronize()
            for name, image, info in frames:
                runs = []
                for _ in range(2):
                    torch.mps.synchronize()
                    start = time.perf_counter()
                    result = model.predict(image, **kwargs)[0]
                    torch.mps.synchronize()
                    elapsed = (time.perf_counter() - start) * 1000
                    runs.append({"predict_call_ms": elapsed, "ultralytics_speed_ms": result.speed, "detections": detections(result)})
                canvas = annotated(image, runs[-1]["detections"], f"{label} | conf=0.25 | imgsz=960 | MPS | {name}", info["contains_existing_overlays"])
                path_out = OUTPUT / label / f"{name}.png"
                path_out.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(path_out), canvas)
                overlays[label, name] = canvas
                row = {"model": label, "input": name, "runs": runs, "overlay": str(path_out)}
                report["results"].append(row)
                save_json(OUTPUT / label / f"{name}.json", row)
                save_json(OUTPUT / "results.json", report)
                print(json.dumps({"model": label, "input": name, "call_ms": [round(r["predict_call_ms"], 1) for r in runs], "detections": runs[-1]["detections"]}), flush=True)
            del model
            torch.mps.empty_cache()
    for name, _, _ in frames:
        cv2.imwrite(str(OUTPUT / f"compare-{name}.png"), np.hstack([overlays["v6", name], overlays["v7", name]]))
    summary = []
    for label in ["v6", "v7"]:
        values = [r["predict_call_ms"] for row in report["results"] if row["model"] == label for r in row["runs"]]
        summary.append({"model": label, "n": len(values), "p50_ms": float(np.median(values)), "p95_ms": float(np.percentile(values, 95)), "fps_from_mean_call_time": 1000 / float(np.mean(values)), "not_end_to_end_live_fps": True})
    save_json(OUTPUT / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
