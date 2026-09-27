#!/usr/bin/env python3
"""Strict publisher-annotation deduplication and frozen-prediction recount; no inference.

Keep the source dataset and benchmark immutable. This produces a derived label
revision, not a new holdout or model improvement. Only source records identical in
every field except their annotation ID qualify; IoU and predictions play no part.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_public_candidate import ALIASES, filter_predictions, normalize_predictions, score_split


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def source_key(annotation):
    required = {"id", "image_id", "category_id", "bbox", "segmentation", "iscrowd"}
    if not required <= annotation.keys() or type(annotation["id"]) is not int:
        raise ValueError("Strict deduplication requires source ID, image/class, box, mask and crowd fields")
    return canonical({k: v for k, v in annotation.items() if k != "id"})


def deduplicate_manifest(data, sources):
    """sources maps manifest image IDs to original publisher annotation records."""
    revised, removals = deepcopy(data), []
    for image in revised["images"]:
        records = sources[image["id"]]
        by_id = {a["id"]: a for a in records}
        if len(by_id) != len(records):
            raise ValueError("Repeated source annotation ID needs separate investigation")
        groups = defaultdict(list)
        for box in image.get("annotations", []):
            source = by_id[box["source_annotation_id"]]
            if source["image_id"] != image["source_image_id"]:
                raise ValueError("Annotation source image identity mismatch")
            groups[(box["label"], source_key(source))].append(box)
        removed_ids = set()
        for (_, key), boxes in groups.items():
            if len(boxes) < 2:
                continue
            boxes.sort(key=lambda b: b["source_annotation_id"])
            keep = boxes[0]
            normalized = canonical({k: v for k, v in keep.items() if k != "source_annotation_id"})
            for duplicate in boxes[1:]:
                if canonical({k: v for k, v in duplicate.items() if k != "source_annotation_id"}) != normalized:
                    raise ValueError("Identical source annotations have inconsistent derived attributes")
                removed_ids.add(duplicate["source_annotation_id"])
                removals.append({"image_id": image["id"], "split": image["split"], "label": keep["label"],
                                 "kept_source_annotation_id": keep["source_annotation_id"],
                                 "removed_source_annotation_id": duplicate["source_annotation_id"],
                                 "source_record_except_id_sha256": hashlib.sha256(key.encode()).hexdigest(),
                                 "source_annotation_path": image.get("source_annotation_path"),
                                 "reason": "All original publisher fields except annotation ID are exactly identical in the same image and class."})
        image["annotations"] = [b for b in image.get("annotations", []) if b["source_annotation_id"] not in removed_ids]
        if removed_ids:
            image["exact_duplicate_source_ids_removed"] = sorted(removed_ids)
    # All review status, coverage, class vocabulary, images and split memberships stay unchanged.
    revised["name"] = data.get("name", "Public dataset") + " — exact source duplicates removed"
    return revised, removals


def verified_archive_sources(data, archive):
    """Verify original archive and copied source JSON before trusting source equality."""
    if digest(archive) != data["source"]["annotation_archive_sha256"]:
        raise ValueError("Publisher archive SHA mismatch")
    sources, member_indices = {}, {}
    with zipfile.ZipFile(archive) as z:
        for image in data["images"]:
            member = image["annotation_source"].split("#", 1)[1]
            if member not in member_indices:
                grouped = defaultdict(list)
                for annotation in json.loads(z.read(member))["annotations"]:
                    grouped[annotation["image_id"]].append(annotation)
                member_indices[member] = grouped
            records = member_indices[member][image["source_image_id"]]
            source_file = Path(image["source_annotation_path"])
            if digest(source_file) != image["source_annotation_sha256"]:
                raise ValueError("Copied source annotation SHA mismatch")
            if canonical(json.loads(source_file.read_text())["annotations"]) != canonical(records):
                raise ValueError("Copied source annotation differs from pinned publisher archive")
            sources[image["id"]] = records
    return sources


def frozen_recount(original, revised, frozen_report, lock, caches):
    if lock["locked_settings"] != frozen_report["locked_settings"] or lock["model_fingerprints"] != frozen_report["model_fingerprints"]:
        raise ValueError("Frozen report and validation lock differ")
    if lock["aliases"] != ALIASES:
        raise ValueError("Current aliases differ from frozen lock; use original evaluator revision")
    result = {"status": "same_test_images_label_revision_fixed_settings_recount", "new_holdout": False,
              "model_inference_performed": False, "threshold_selection_performed": False,
              "deployment_allowed": False, "locked_settings": deepcopy(lock["locked_settings"]), "models": {}}
    for name, cache in caches.items():
        fingerprint = {k: cache["metadata"].get(k) for k in ("sha256", "family", "names", "ultralytics")}
        if fingerprint != lock["model_fingerprints"][name]:
            raise ValueError("Saved predictions do not match locked model fingerprint")
        setting = lock["locked_settings"][name]
        if cache["metadata"]["imgsz"] != setting["imgsz"]:
            raise ValueError("Saved predictions have wrong locked image size")
        pred = filter_predictions(normalize_predictions(cache["raw_predictions"], original["classes"]), setting["thresholds"])
        if pred != cache["predictions"]:
            raise ValueError("Cached test filtering does not match frozen settings")
        scores = {}
        for revision, data in (("original", original), ("deduplicated", revised)):
            subset = dict(data, images=[im for im in data["images"] if im["split"] == "test"])
            if not {im["id"] for im in subset["images"]} <= set(pred):
                raise ValueError("Missing cached predictions for test images")
            scores[revision] = score_split(subset, pred, lock["iou_threshold"])
        for label in original["classes"]:
            if any(scores["original"]["per_class"][label][key] != frozen_report["test"][name]["evaluation"]["per_class"][label][key]
                   for key in ("tp", "fp", "fn")):
                raise ValueError("Original recount does not reproduce frozen test counts")
        scores["per_class_revision_delta"] = {label: {key: scores["deduplicated"]["per_class"][label][key]-scores["original"]["per_class"][label][key]
                                                     for key in ("tp", "fp", "fn")} for label in original["classes"]}
        scores["model_fingerprint"] = fingerprint
        result["models"][name] = scores
    result["limitations"] = ["The same test images and predictions are reused after label correction; this is not a new independent holdout.",
                            "Original validation settings remain fixed even though validation annotations also contain duplicates.",
                            "Changes in scores measure corrected labels, not changes in weights or inference ability.",
                            "Publisher labels retain their original review status; other annotation mistakes may remain.",
                            "No temporal, physical-distance, phone FPS, acoustic-latency or risk-acceptance evidence is added."]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a new output directory; never overwrite frozen or previous evidence")
    data = json.loads(args.dataset.read_text())
    report_path, lock_path = args.evaluation/"report.json", args.evaluation/"validation-lock.json"
    report, lock = [json.loads(p.read_text()) for p in (report_path, lock_path)]
    if digest(args.dataset) != report["dataset_sha256"] or digest(args.dataset) != lock["dataset_sha256"]:
        raise ValueError("Original dataset is not the frozen evaluated manifest")
    sources = verified_archive_sources(data, args.archive)
    revised, removals = deduplicate_manifest(data, sources)
    revised["annotation_revision"] = {"parent_manifest": str(args.dataset.resolve()), "parent_manifest_sha256": digest(args.dataset),
        "method": "Strict publisher record equality excluding only annotation ID; minimum numeric ID retained.",
        "review_status_unchanged": True, "image_split_membership_unchanged": True,
        "removal_ledger": str((args.output/"removed-duplicates.json").resolve()),
        "test_role": "Same original test images after source duplicate-label correction, not a new holdout."}
    caches = {name: json.loads((args.evaluation/f"{name}-test-predictions.json").read_text()) for name in lock["locked_settings"]}
    recount = frozen_recount(data, revised, report, lock, caches)
    inputs = [args.dataset, args.archive, report_path, lock_path,
              *[args.evaluation/f"{name}-test-predictions.json" for name in caches]]
    audit = {"rule": revised["annotation_revision"]["method"], "input_sha256": {str(p.resolve()): digest(p) for p in inputs},
             "script_sha256": digest(__file__), "evaluator_sha256": digest(ROOT/"scripts/evaluate_public_candidate.py"),
             "annotation_counts_before": {s: dict(Counter(a["label"] for im in data["images"] if im["split"]==s for a in im["annotations"])) for s in ("train","val","test")},
             "annotation_counts_after": {s: dict(Counter(a["label"] for im in revised["images"] if im["split"]==s for a in im["annotations"])) for s in ("train","val","test")},
             "removed_by_split": dict(Counter(r["split"] for r in removals)),
             "removed_by_split_class": {s: dict(Counter(r["label"] for r in removals if r["split"]==s)) for s in ("train","val","test")},
             "removals": removals, "deployment_allowed": False}
    args.output.mkdir(parents=True)
    for name, document in (("dataset.json", revised), ("removed-duplicates.json", audit), ("fixed-test-recount.json", recount)):
        (args.output/name).write_text(json.dumps(document, indent=2)+"\n")
    print(json.dumps({"output": str(args.output.resolve()), "removed_by_split": audit["removed_by_split"]}))


if __name__ == "__main__":
    main()
