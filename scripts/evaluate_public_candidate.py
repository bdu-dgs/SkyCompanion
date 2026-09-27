#!/usr/bin/env python3
"""Research-only public benchmark: calibrate on val, persist lock, then open test for inference.

Extends the existing partial-label evaluator without changing live configuration. Complete
image/class coverage alone contributes precision; known targets in partial images are
reported separately. Static inference timings never claim phone or audio performance.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.obstacle_eval import evaluate, validate_dataset
from app.obstacle_risk import iou

TAXONOMY = json.loads((ROOT / "schemas/public-obstacles-v1.json").read_text())
PRIORITY_CLASSES = tuple(TAXONOMY["x-taxonomy"])
ALIASES = TAXONOMY["x-evaluation-aliases"]
REVIEW_STATUSES = {"published_annotations", "assistant_reviewed", "human_verified"}
DEFAULT_THRESHOLDS = [.05, .1, .15, .25, .35, .5, .7]
# Fixed before any model results. These describe normalized box image-area only,
# never physical object size, metric distance, or a near/far classification.
IMAGE_AREA_BINS = (("image-area-tiny", 0., .001), ("image-area-small", .001, .01),
                   ("image-area-medium", .01, .1), ("image-area-large", .1, None))
GEOMETRY_NOTES = {
    "visible_component_bbox": "Visible semantic connected-region boxes; fragments may split one object and touching objects may merge. Not verified object instances.",
    "visible_instance_bbox": "Bounding box of the explicitly annotated visible object instance.",
    "publisher_bbox_unverified": "Publisher box geometry; visible/amodal and instance interpretation were not independently verified.",
}


def image_area_group(box):
    area = box["w"] * box["h"]
    return next(name for name, _, upper in IMAGE_AREA_BINS if upper is None or area < upper)


def truncation_group(box):
    attributes = box.get("attributes", {})
    value = attributes.get("truncated") if "truncated" in attributes else box.get("truncated")
    return "true" if value is True else "false" if value is False else "unknown"


def geometry_scope(box, image, data):
    return box.get("geometry_scope") or image.get("geometry_scope") or data.get("geometry_scope") or "publisher_bbox_unverified"


def recall_counts(count):
    targets = count["tp"] + count["fn"]
    return {"tp": count["tp"], "fn": count["fn"], "targets": targets,
            "recall": count["tp"] / targets if targets else None}


def model_vocabulary_coverage(metadata, classes):
    names = metadata.get("names")
    raw = list(names.values()) if isinstance(names, dict) else list(names) if isinstance(names, (list, tuple)) else None
    if raw is None:
        return {"status": "unknown", "dataset_classes": list(classes), "reason": "Model output vocabulary metadata unavailable."}
    mapped = {label: [name for name in raw if ALIASES.get(name, name) == label] for label in classes}
    return {"status": "known", "dataset_classes": list(classes), "raw_output_classes": raw,
            "approved_output_names_by_dataset_class": mapped,
            "missing_exact_or_approved_alias": [label for label, matches in mapped.items() if not matches],
            "scope": "Output-name coverage only, not evidence that a class is accurately detected. Missing fine-grained names must not be described solely as failure to see an object. No new aliases are inferred."}


def coverage_for(image, label):
    if image.get("review_status") not in REVIEW_STATUSES:
        return "unknown"
    explicit = image.get("annotation_coverage", {}).get(label)
    if explicit is not None:
        if explicit not in {"complete", "partial", "unknown"}:
            raise ValueError(f"Invalid annotation coverage: {explicit}")
        return explicit
    if label in image.get("reviewed_classes", []):
        return "complete"
    return "partial" if any(b["label"] == label for b in image.get("annotations", [])) else "unknown"


def normalize_predictions(predictions, classes):
    names = set(classes)
    return {key: [dict(box, label=ALIASES.get(box["label"], box["label"]))
                  for box in boxes if ALIASES.get(box["label"], box["label"]) in names]
            for key, boxes in predictions.items()}


def matched_indices(truth, guesses, threshold=.5):
    """One prediction can claim only one known target, matching existing evaluator order."""
    targets, predictions = set(), set()
    for index in sorted(range(len(guesses)), key=lambda j: -guesses[j]["confidence"]):
        overlap, target = max(((iou(guesses[index], box), j) for j, box in enumerate(truth)
                               if j not in targets), default=(0., -1))
        if overlap >= threshold:
            targets.add(target)
            predictions.add(index)
    return targets, predictions


def prediction_coverage(box, region):
    width = max(0., min(box["x"] + box["w"], region["x"] + region["w"]) - max(box["x"], region["x"]))
    height = max(0., min(box["y"] + box["h"], region["y"] + region["h"]) - max(box["y"], region["y"]))
    return width * height / max(box["w"] * box["h"], 1e-12)


def score_split(data, predictions, threshold=.5):
    """Use existing TP/FP/FN on complete labels; keep partial known-target recall separate."""
    predictions = normalize_predictions(predictions, data["classes"])
    result = {"iou_threshold": threshold, "per_class": {}, "sampled_first_detection": [],
              "status": "public_research_not_acceptance", "evaluation_aliases": ALIASES}
    for label in data["classes"]:
        complete_images, complete_predictions = [], {}
        counts = Counter(complete=0, partial=0, unknown=0)
        partial_tp = partial_fn = ignored = unknown_guesses = 0
        attribute_counts = {name: Counter(tp=0, fn=0) for name in ("near_in_image", "truncated", "occluded")}
        area_counts = {name: Counter(tp=0, fn=0) for name, _, _ in IMAGE_AREA_BINS}
        truncation_counts = {name: Counter(tp=0, fn=0) for name in ("true", "false", "unknown")}
        geometry_counts = {}
        for image in data["images"]:
            coverage = coverage_for(image, label)
            counts[coverage] += 1
            guesses = [b for b in predictions.get(image["id"], []) if b["label"] == label]
            if image.get("review_status") not in REVIEW_STATUSES:
                unknown_guesses += len(guesses)
                continue
            truth = [b for b in image.get("annotations", []) if b["label"] == label and not b.get("ignore")]
            hits, matched_guesses = matched_indices(truth, guesses, threshold)
            regions = [r for r in image.get("ignore_regions", []) if not r.get("labels") or label in r["labels"]]
            regions += [b for b in image.get("annotations", []) if b["label"] == label and b.get("ignore")]
            kept = []
            for index, box in enumerate(guesses):
                if index not in matched_guesses and any(prediction_coverage(box, region) >= .5 for region in regions):
                    ignored += 1
                else:
                    kept.append(box)
            for name, count in attribute_counts.items():
                for j, box in enumerate(truth):
                    if box.get("attributes", {}).get(name) is True or box.get(name) is True:
                        count["tp" if j in hits else "fn"] += 1
            if coverage == "complete":
                # Reuse the same complete-image, same-class assignment above.
                # Never match independently inside each area/truncation group.
                for j, box in enumerate(truth):
                    outcome = "tp" if j in hits else "fn"
                    area_counts[image_area_group(box)][outcome] += 1
                    truncation_counts[truncation_group(box)][outcome] += 1
                    scope = geometry_scope(box, image, data)
                    geometry_counts.setdefault(scope, Counter(tp=0, fn=0))[outcome] += 1
                # Missing timestamps cannot imply temporal evidence merely from a track ID.
                annotations = [dict(b) for b in truth]
                if not isinstance(image.get("time_s"), (int, float)) or not image.get("video_group"):
                    for box in annotations:
                        box.pop("track_id", None)
                complete_images.append(dict(image, annotations=annotations, reviewed_classes=[label]))
                complete_predictions[image["id"]] = kept
            else:
                partial_tp += len(hits)
                partial_fn += len(truth) - len(hits)
                unknown_guesses += len(kept) - len(matched_guesses)
        classic = evaluate({"classes": [label], "images": complete_images}, complete_predictions, threshold)
        row = classic["per_class"][label]
        row["metric_scope"] = "TP/FP/FN and precision/recall use complete image/class coverage only."
        row["coverage"] = dict(counts)
        row["ignored_predictions"] = ignored
        row["unscored_predictions_unknown_coverage"] = unknown_guesses
        row["partial_known_targets"] = {"tp": partial_tp, "fn": partial_fn, "recall": partial_tp / (partial_tp + partial_fn) if partial_tp + partial_fn else None,
                                         "precision": None, "scope": "Known targets only; unmatched predictions are unknown, not false positives."}
        row["known_target_attributes"] = {name: {**count, "miss_rate": count["fn"] / (count["tp"] + count["fn"]) if count["tp"] + count["fn"] else None,
                                                  "scope": "Explicit attributes on known annotated targets; no physical distance inference."}
                                               for name, count in attribute_counts.items()}
        row["target_recall_diagnostics"] = {
            "scope": "Complete image/class coverage only. One-to-one full-frame matching is performed before grouping targets; these diagnostics do not change official TP/FP/FN or parameter selection.",
            "grouping": "image-area",
            "image_area_definition": "Normalized ground-truth bbox width × height in the input image; not physical size or distance, and not foreground mask area.",
            "image_area": {name: {"normalized_area_min_inclusive": lower, "normalized_area_max_exclusive": upper,
                                  **recall_counts(area_counts[name])} for name, lower, upper in IMAGE_AREA_BINS},
            "truncated": {name: recall_counts(count) for name, count in truncation_counts.items()},
            "geometry_scope": {name: {**recall_counts(count),
                                      "interpretation": GEOMETRY_NOTES.get(name, "Source-defined geometry; do not assume verified object instances.")}
                               for name, count in geometry_counts.items()},
        }
        result["per_class"][label] = row
        result["sampled_first_detection"].extend(classic["sampled_first_detection"])
    return result


def filter_predictions(predictions, thresholds):
    return {key: [b for b in boxes if thresholds.get(b["label"]) is not None and b["confidence"] >= thresholds[b["label"]]]
            for key, boxes in predictions.items()}


def choose_settings(grid, classes):
    """Per-class val F1; common size by macro F1. No test input is accepted here."""
    sizes = sorted({row["imgsz"] for row in grid})
    options = []
    for size in sizes:
        settings, details = {}, {}
        for label in classes:
            rows = []
            for entry in grid:
                if entry["imgsz"] != size:
                    continue
                metrics = entry["evaluation"]["per_class"][label]
                if metrics["tp"] + metrics["fn"] == 0:
                    continue
                precision, recall = metrics["precision"] or 0., metrics["recall"] or 0.
                f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.
                rows.append({"threshold": entry["threshold"], "f1": f1, "precision": precision, "recall": recall})
            if rows:
                winner = max(rows, key=lambda row: (row["f1"], row["precision"], row["threshold"]))
                settings[label], details[label] = winner["threshold"], winner
            else:
                settings[label] = None
        if details:
            options.append({"imgsz": size, "thresholds": settings, "per_class_validation": details,
                            "macro_f1": sum(row["f1"] for row in details.values()) / len(details),
                            "macro_precision": sum(row["precision"] for row in details.values()) / len(details),
                            "uncalibrated_classes": [label for label in classes if label not in details]})
    if not options:
        raise ValueError("No fully annotated positive validation class; cannot calibrate candidate.")
    return max(options, key=lambda row: (row["macro_f1"], row["macro_precision"], -row["imgsz"]))


def validate_public_manifest(data):
    validate_dataset(data)
    seen = {}
    for image in data["images"]:
        for label in data["classes"]:
            coverage_for(image, label)
        for region in image.get("ignore_regions", []):
            if not all(type(region.get(k)) in (float, int) and math.isfinite(region[k]) for k in ("x", "y", "w", "h")):
                raise ValueError("Invalid ignore region geometry")
            if not (0 <= region["x"] < 1 and 0 <= region["y"] < 1 and 0 < region["w"] <= 1 - region["x"] + 1e-6 and 0 < region["h"] <= 1 - region["y"] + 1e-6):
                raise ValueError("Ignore region exceeds image")
        route = image.get("route_group")
        if route and not str(route).startswith("unknown"):
            if route in seen and seen[route] != image["split"]:
                raise ValueError(f"route_group crosses splits: {route}")
            seen[route] = image["split"]
    if any(not any(im["split"] == split for im in data["images"]) for split in ("val", "test")):
        raise ValueError("Both validation and test are required")


def coverage_report(data):
    all_classes = list(dict.fromkeys([*PRIORITY_CLASSES, *data["classes"]]))
    by_split = {}
    for split in ("train", "val", "test"):
        images = [im for im in data["images"] if im["split"] == split]
        by_split[split] = {}
        for label in all_classes:
            counts = Counter(complete=0, partial=0, unknown=0)
            counts.update(coverage_for(im, label) for im in images)
            by_split[split][label] = {**dict(counts),
                                     "known_positive_targets": sum(b["label"] == label and not b.get("ignore") for im in images for b in im.get("annotations", [])),
                                     "in_model_training_vocabulary": label in data["classes"]}
    return {"by_split": by_split, "review_provenance": dict(Counter(im.get("review_status", "unknown") for im in data["images"])),
            "geometry_scopes": dict(Counter(geometry_scope(b, im, data) for im in data["images"] for b in im.get("annotations", []))),
            "unknown_group_images": {kind: sum(not im.get(kind) or str(im[kind]).startswith("unknown") for im in data["images"])
                                     for kind in ("video_group", "route_group", "location_group")},
            "split_provenance": data.get("split_provenance", data.get("split_policy", {"status": "unknown"})),
            "split_provenance_source": "split_provenance" if "split_provenance" in data else "split_policy" if "split_policy" in data else "unavailable"}


def unavailable_runtime_metrics():
    return {metric: {"value": None, "status": "not_verified", "reason": reason} for metric, reason in {
        "false_positives_per_minute": "Requires timed, exhaustively annotated continuous video; per-image FP is not per-minute FP.",
        "first_discovery_time": "Requires true object onset and dense tracks; sampled first detection is separately qualified.",
        "longest_continuous_miss_s": "Requires continuous time, target tracks and verified visibility/occlusion.",
        "phone_processing_fps": "Requires sustained inference on the target phone with capture and resource pressure.",
        "actual_speech_onset_latency_ms": "Requires shared timing evidence and actual acoustic onset on the phone.",
        "interruptions_per_minute": "Requires actual playback and user interaction observation.",
        "path_occupancy_accuracy": "Object boxes alone do not provide user-path conflict ground truth."
    }.items()}


def collect(detector, images):
    import cv2
    import numpy as np
    predictions, timings = {}, []
    for image in images:
        frame = cv2.imread(image["path"])
        if frame is None:
            raise ValueError(f"Image decode failed: {image['path']}")
        start = time.perf_counter()
        predictions[image["id"]] = detector.predict(frame)
        timings.append((time.perf_counter() - start) * 1000)
    return predictions, {"p50_ms": float(np.percentile(timings, 50)), "p95_ms": float(np.percentile(timings, 95)),
                         "serial_inference_fps": 1000 / float(np.mean(timings)), "samples": len(timings),
                         "scope": "Warm sequential batch1 including model postprocess at the recorded confidence floor; excludes capture, network, UI and audio. Not deployed operating-point timing."}


def make_detector(profile, path, size, device, floor, candidate_family):
    from app.obstacle_models import LocalDetector
    detector = LocalDetector(profile, imgsz=size, device=device, confidence=floor)
    if path:
        detector.path = Path(path).resolve()
    if profile == "skycompanion-finetuned":
        detector.settings = dict(detector.settings, family=candidate_family)
    detector.load()
    return detector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--sizes", nargs="+", type=int, default=[640, 960])
    parser.add_argument("--baseline-sizes", nargs="+", type=int, default=[960])
    parser.add_argument("--thresholds", nargs="+", type=float, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--confidence-floor", type=float, default=.01)
    parser.add_argument("--candidate-family", choices=["yolo", "yoloe"], default="yolo")
    parser.add_argument("--iou", type=float, default=.5)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a fresh output directory; frozen evaluations are not overwritten.")
    if not 0 < args.confidence_floor <= min(args.thresholds) <= max(args.thresholds) <= 1 or not 0 < args.iou <= 1:
        raise ValueError("Invalid confidence/IoU range")
    if any(size <= 0 for size in [*args.sizes, *args.baseline_sizes]):
        raise ValueError("Image sizes must be positive")
    data = json.loads(args.dataset.read_text())
    for image in data["images"]:
        if not Path(image["path"]).is_absolute():
            image["path"] = str((args.dataset.resolve().parent / image["path"]).resolve())
    validate_public_manifest(data)
    subsets = {split: dict(data, images=[im for im in data["images"] if im["split"] == split]) for split in ("val", "test")}
    args.output.mkdir(parents=True)
    report = {"evaluation_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(), "candidate_sha256": hashlib.sha256(args.candidate.read_bytes()).hexdigest(),
              "taxonomy_sha256": hashlib.sha256((ROOT / "schemas/public-obstacles-v1.json").read_bytes()).hexdigest(),
              "dataset_classes": list(data["classes"]), "coverage": coverage_report(data), "model_fingerprints": {},
              "output_vocabulary_coverage": {}, "validation_grid": {}, "locked_settings": {}, "test": {},
              "selection_rule": "Per-class complete-label validation F1; tie precision then higher threshold. Common input size by macro F1, macro precision, then smaller size. Both models locked before test inference.",
              "comparison_scope": "Each model calibrated independently on the same validation set; not a fixed-configuration comparison.",
              "prediction_confidence_floor": args.confidence_floor, "aliases": ALIASES, "runtime_metrics": unavailable_runtime_metrics(),
              "test_role": data.get("test_role", "Public research benchmark; untouched and location-independent status is not presumed."),
              "deployment_allowed": False,
              "limitations": ["Publisher annotations are not new human verification.", "Component boxes from semantic masks are not necessarily object instances.",
                              "Classes without complete validation positives cannot be calibrated; missing labels remain unknown.",
                              "A specialist cannot replace the existing 115-class detector without preservation tests.",
                              "Static geometry cannot verify wearer-relative direction, physical distance or collision risk."]}
    def save():
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    specs = [("baseline_v7", "yoloe-11s", args.baseline, args.baseline_sizes),
             ("candidate", "skycompanion-finetuned", args.candidate, args.sizes)]
    save()
    for name, profile, path, sizes in specs:
        grid = []
        for size in sizes:
            detector = make_detector(profile, path, size, args.device, args.confidence_floor, args.candidate_family)
            metadata = detector.metadata()
            fingerprint = {key: metadata.get(key) for key in ("sha256", "family", "names", "ultralytics")}
            if name in report["model_fingerprints"] and report["model_fingerprints"][name] != fingerprint:
                raise ValueError(f"{name} model changed during validation")
            if name == "candidate" and metadata.get("sha256") != report["candidate_sha256"]:
                raise ValueError("Candidate weights changed after experiment registration")
            report["model_fingerprints"][name] = fingerprint
            report["output_vocabulary_coverage"][name] = model_vocabulary_coverage(metadata, data["classes"])
            predictions, timings = collect(detector, subsets["val"]["images"])
            predictions = normalize_predictions(predictions, data["classes"])
            (args.output / f"{name}-val-{size}-predictions.json").write_text(json.dumps({"metadata": detector.metadata(), "timing": timings, "predictions": predictions}) + "\n")
            for threshold in args.thresholds:
                scored = score_split(subsets["val"], filter_predictions(predictions, dict.fromkeys(data["classes"], threshold)), args.iou)
                grid.append({"imgsz": size, "threshold": threshold, "evaluation": scored})
            print(f"{name}: validation complete at {size}", flush=True)
        report["validation_grid"][name] = grid
        report["locked_settings"][name] = choose_settings(grid, data["classes"])
        save()
    # This immutable file is written before either model processes test pixels for inference.
    lock = {"evaluation_script_sha256": report["evaluation_script_sha256"],
            "dataset_sha256": report["dataset_sha256"], "candidate_sha256": report["candidate_sha256"],
            "locked_settings": report["locked_settings"], "selection_rule": report["selection_rule"], "aliases": ALIASES,
            "confidence_floor": args.confidence_floor, "iou_threshold": args.iou,
            "model_fingerprints": report["model_fingerprints"]}
    (args.output / "validation-lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    for name, profile, path, _ in specs:
        setting = report["locked_settings"][name]
        detector = make_detector(profile, path, setting["imgsz"], args.device, args.confidence_floor, args.candidate_family)
        fingerprint = {key: detector.metadata().get(key) for key in ("sha256", "family", "names", "ultralytics")}
        if fingerprint != report["model_fingerprints"][name]:
            raise ValueError(f"{name} model differs from locked validation weights")
        raw, timings = collect(detector, subsets["test"]["images"])
        predictions = filter_predictions(normalize_predictions(raw, data["classes"]), setting["thresholds"])
        (args.output / f"{name}-test-predictions.json").write_text(json.dumps({"metadata": detector.metadata(), "predictions": predictions, "raw_predictions": raw}) + "\n")
        report["test"][name] = {"metadata": detector.metadata(), "timing": timings, "evaluation": score_split(subsets["test"], predictions, args.iou)}
        save()
        print(f"{name}: locked test evaluation complete", flush=True)
    report["per_class_change"] = {}
    for label in data["classes"]:
        before, after = [report["test"][name]["evaluation"]["per_class"][label] for name in ("baseline_v7", "candidate")]
        report["per_class_change"][label] = {metric + "_delta": after[metric] - before[metric] if after[metric] is not None and before[metric] is not None else None
                                             for metric in ("precision", "recall")}
    save()


if __name__ == "__main__":
    main()
