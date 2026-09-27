#!/usr/bin/env python3
"""Offline prompt-vocabulary comparison; no training or live-service changes.

Screenshots contain existing predictions/player UI and are diagnostic inputs only.
No screenshot here is a training example or an accuracy ground-truth annotation.
All dependencies and original weights must already exist locally; no downloads.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import time
from pathlib import Path

os.environ["YOLO_AUTOINSTALL"] = "False"

import cv2
import numpy as np
import torch
from ultralytics import YOLO, YOLOE, __version__

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "backend/data/models"
OUTPUT = ROOT / "backend/data/obstacle_experiments/furniture"
DESKTOP = Path("/Users/stanley/Desktop")
CASE = ROOT / "backend/data/obstacle_cases/20260925-215027-5f22ede2"
ADDED = ["chair", "table", "rock", "stone block", "concrete barrier", "planter",
         "pillar", "column", "street kiosk", "scaffolding pole", "newsstand", "kiosk"]
V5_ADDED = ["chair", "table", "outdoor table", "boulder", "stone barrier", "concrete block",
            "concrete barrier", "pillar", "column", "street kiosk", "scaffolding pole",
            "newsstand", "kiosk", "news kiosk", "booth"]
FOCUS = set(ADDED + V5_ADDED + ["pole", "light pole", "signpost", "potted plant", "construction barrier",
                              "dining table", "dog", "parking meter"])


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def prepare(size, names, version=4):
    source = MODEL_DIR / f"yoloe-11{size}-seg.pt"
    if not source.is_file():
        return None
    output = MODEL_DIR / f"skycompanion-yoloe-11{size}-v{version}-candidate.pt"
    model = YOLOE(str(source))
    embedding = model.get_text_pe(names)
    model.set_classes(names, embedding)
    model.save(str(output))
    reloaded = YOLOE(str(output))
    assert list(reloaded.names.values()) == names
    assert torch.equal(reloaded.model.pe, embedding)
    manifest = {
        "kind": "pretrained_with_text_prompts_not_finetuned", "vocabulary_version": version,
        "names": names, "source": f"https://github.com/ultralytics/assets/releases/download/v8.4.0/yoloe-11{size}-seg.pt",
        "source_sha256": sha(source), "sha256": sha(output), "ultralytics": __version__,
        "status": "offline_candidate_not_selected_for_live_service", "training_performed": False,
    }
    save_json(output.with_suffix(".json"), manifest)
    return output


def inputs(include_parking=False):
    specifications = [
        ("screenshot-tables-chairs", DESKTOP / "Screenshot 2026-09-25 at 10.00.06\u202fpm.png", [32, 419, 1344, 1156]),
        ("screenshot-stone-barriers", DESKTOP / "Screenshot 2026-09-25 at 10.00.30\u202fpm.png", [32, 419, 1344, 1156]),
        ("screenshot-newsstand", DESKTOP / "Screenshot 2026-09-25 at 10.02.41\u202fpm.png", [32, 419, 1344, 1156]),
        ("screenshot-white-column", DESKTOP / "Screenshot 2026-09-25 at 9.51.51\u202fpm.png", [32, 9, 1344, 746]),
        ("raw-signpost-3003", CASE / "00003003-input.png", None),
        ("raw-linknyc-2943", CASE / "00002943-input.png", None),
    ]
    if include_parking:
        specifications.append(("raw-parking-meter-15718", ROOT / "backend/data/obstacle_cases/20260925-220434-988997c7/00015718-input.png", None))
    frames = []
    for name, path, crop in specifications:
        original = cv2.imread(str(path))
        if original is None:
            raise FileNotFoundError(path)
        if crop:
            x1, y1, x2, y2 = crop
            image = cv2.resize(original[y1:y2, x1:x2], (791, 443), interpolation=cv2.INTER_AREA)
        else:
            image = original
        saved = OUTPUT / "inputs" / f"{name}.png"
        saved.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(saved), image)
        frames.append((name, image, {"source": str(path), "source_sha256": sha(path),
                                   "input_path": str(saved), "input_sha256": sha(saved),
                                   "crop_xyxy": crop, "input_wh": list(image.shape[1::-1]),
                                   "kind": "annotated_screenshot_diagnostic_only" if crop else "raw_capture",
                                   "contains_existing_overlays": bool(crop), "is_ground_truth": False,
                                   "training_eligible": False}))
    return frames


def detections(result):
    return [{"label": result.names[int(cls)], "class_id": int(cls), "confidence": float(conf),
             "xyxy": [float(v) for v in box]}
            for box, cls, conf in zip(result.boxes.xyxy.cpu().tolist(), result.boxes.cls.cpu().tolist(), result.boxes.conf.cpu().tolist())]


def annotated(image, boxes, heading, screenshot):
    canvas = np.full((image.shape[0] + 76, image.shape[1], 3), (20, 20, 24), np.uint8)
    canvas[76:] = image
    cv2.putText(canvas, heading, (12, 23), cv2.FONT_HERSHEY_SIMPLEX, .49, (240, 240, 240), 1, cv2.LINE_AA)
    note = "SCREENSHOT DIAGNOSTIC: existing teal overlays remain" if screenshot else "RAW CAPTURE: no ground-truth annotations"
    cv2.putText(canvas, note, (12, 45), cv2.FONT_HERSHEY_SIMPLEX, .45, (180, 190, 210), 1, cv2.LINE_AA)
    cv2.putText(canvas, "New predictions in AMBER; prompt expansion, no training", (12, 65), cv2.FONT_HERSHEY_SIMPLEX, .44, (50, 190, 255), 1, cv2.LINE_AA)
    for box in boxes:
        x1, y1, x2, y2 = (int(round(v)) for v in box["xyxy"])
        y1 += 76
        y2 += 76
        color = (30, 190, 255)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        label = f"{box['label']} {box['confidence']:.2f}"
        (width, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, .42, 1)
        tx = max(0, min(x1, canvas.shape[1] - width - 6))
        ty = max(92, y1)
        cv2.rectangle(canvas, (tx, ty - 17), (tx + width + 6, ty), (15, 25, 35), -1)
        cv2.putText(canvas, label, (tx + 3, ty - 4), cv2.FONT_HERSHEY_SIMPLEX, .42, color, 1, cv2.LINE_AA)
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v5", action="store_true", help="One bounded follow-up: small model, revised terms, conf=.25 only.")
    parser.add_argument("--v6", action="store_true", help="Preserve COCO80 categories, union with v5 additions; include clean parking-meter sample.")
    parser.add_argument("--imgsz", type=int, choices=[640, 960], default=640,
                        help="Use 960 for the bounded v5/v6 resolution check; reuse the saved weight file.")
    args = parser.parse_args()
    if args.v5 and args.v6:
        parser.error("Choose one vocabulary follow-up.")
    if args.imgsz != 640 and not (args.v5 or args.v6):
        parser.error("The resolution follow-up is supported only with --v5 or --v6.")
    torch.set_num_threads(2)
    os.chdir(MODEL_DIR)  # Existing local MobileCLIP encoder is resolved here.
    assert (MODEL_DIR / "mobileclip_blt.ts").is_file(), "Local text encoder is required; no download permitted."
    names = json.loads((MODEL_DIR / "skycompanion-yoloe-11s-v2.json").read_text())["names"] + (V5_ADDED if args.v5 or args.v6 else ADDED)
    if args.v6:
        coco_names = list(YOLO(str(MODEL_DIR / "yolo11n.pt")).names.values())
        assert len(coco_names) == 80
        names = list(dict.fromkeys(coco_names + names))
        assert names[:80] == coco_names and len(names) == len(set(names))
    else:
        assert len(names) == len(set(names)) == (43 if args.v5 else 40)
    models = [] if args.v5 or args.v6 else [("v2-small", MODEL_DIR / "skycompanion-yoloe-11s-v2.pt")]
    v5_label = "v5-small" if args.imgsz == 640 else "v5-small-960"
    version = 6 if args.v6 else 5 if args.v5 else 4
    candidate_label = ("v6-small" if args.imgsz == 640 else "v6-small-960") if args.v6 else v5_label
    for size, label in ([("s", candidate_label)] if args.v5 or args.v6 else [("s", "v4-small"), ("l", "v4-large")]):
        if args.imgsz == 960:
            path = MODEL_DIR / f"skycompanion-yoloe-11s-v{version}-candidate.pt"
            assert path.is_file(), "Run the 640 check first; do not overwrite its weights."
            assert list(YOLOE(str(path)).names.values()) == names
        else:
            path = prepare(size, names, version=version)
        if path:
            models.append((label, path))
    if args.v6:
        models.append((v5_label, MODEL_DIR / "skycompanion-yoloe-11s-v5-candidate.pt"))
    frames = inputs(include_parking=args.v6)
    report = {"purpose": "offline_prompt_vocabulary_diagnostic_not_accuracy_benchmark", "device": "cpu",
              "threads": 2, "imgsz": 640, "iou": .7, "agnostic_nms": True,
              "training_performed": False, "ultralytics": __version__, "models": {},
              "inputs": {name: info for name, _, info in frames}, "results": []}
    if (args.v5 or args.v6) and (OUTPUT / "comparison.json").is_file():
        report = json.loads((OUTPUT / "comparison.json").read_text())
        report["results"] = [row for row in report["results"] if row["model"] != candidate_label
                             and not (args.v6 and row["model"] == v5_label and row["input"] == "raw-parking-meter-15718")]
        report["inputs"].update({name: info for name, _, info in frames})
        if args.v5:
            report["v5_followup"] = {"bounded_prompt_round": 1, "confidence_threshold": .25,
                                "removed_v4_terms": ["planter", "rock", "stone block"],
                                "added_terms": [name for name in V5_ADDED if name not in ADDED]}
        if args.v5 and args.imgsz == 960:
            report["resolution_followup"] = {"imgsz": 960, "same_v5_weight_file": True,
                                             "confidence_threshold": .25, "device": "cpu"}
        if args.v6:
            report["v6_coco_restoration"] = {"reason": "Earlier reduced vocabulary omitted COCO classes such as dog, dining table, parking meter.",
                                             "original_coco_classes_preserved": 80, "class_count": len(names),
                                             "confidence_threshold": .25, "training_performed": False}
    with torch.inference_mode():
        for label, path in models:
            model = YOLOE(str(path))
            report["models"][label] = {"path": str(path), "sha256": sha(path), "names": model.names, "imgsz": args.imgsz}
            model.predict(np.zeros((443, 791, 3), np.uint8), imgsz=args.imgsz, conf=.25, device="cpu", verbose=False, agnostic_nms=True)
            for frame_name, image, info in frames:
                if args.v6 and label == v5_label and frame_name != "raw-parking-meter-15718":
                    continue  # Preserve prior v5 rows; add only the newly supplied clean frame.
                rows = []
                for confidence in ([.25] if args.v5 or args.v6 else [.25, .20, .05]):
                    start = time.perf_counter()
                    result = model.predict(image, imgsz=args.imgsz, conf=confidence, device="cpu", verbose=False, agnostic_nms=True, iou=.7)[0]
                    elapsed = (time.perf_counter()-start)*1000
                    boxes = detections(result)
                    dest = OUTPUT / label / f"{frame_name}-c{round(confidence*100):02}.png"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(dest), annotated(image, boxes, f"{label} | conf={confidence:.2f} | CPU | {frame_name}", info["contains_existing_overlays"]))
                    row = {"model": label, "input": frame_name, "confidence_threshold": confidence,
                           "imgsz": args.imgsz,
                           "inference_ms": result.speed.get("inference"), "single_frame_call_ms": elapsed,
                           "timing_is_realtime_fps": False, "detections": boxes, "annotated_path": str(dest)}
                    rows.append(row)
                    report["results"].append(row)
                # Record unfiltered class-score maxima as diagnosis, never as displayed detections.
                predictor = model.predictor
                tensor = predictor.preprocess([image])
                output = predictor.inference(tensor)
                raw = output[0][0] if isinstance(output[0], tuple) else output[0]
                maxima = {name: float(raw[0, 4 + cid].max()) for cid, name in model.names.items() if name in FOCUS}
                for row in rows:
                    row["raw_max_class_score_anywhere_in_image"] = maxima
                print(json.dumps({"model": label, "input": frame_name,
                                  "new_class_detections_c025": [b for b in rows[0]["detections"] if b["label"] in FOCUS],
                                  "focus_raw_max": maxima}), flush=True)
    save_json(OUTPUT / "comparison.json", report)
    print(f"Report: {OUTPUT / 'comparison.json'}")


if __name__ == "__main__":
    main()
