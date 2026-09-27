#!/usr/bin/env python3
"""Import attributed ForTrunkDet RGB boxes with whole-forest split isolation.

This is a research detection dataset, not an urban-navigation acceptance set.
The official original ZIP and XML are retained; no generated or thermal labels
are admitted. Source image dimensions uniquely identify camera/location cohorts
in the original archive, verified against the original paper's Table 1.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import random
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RECORD = "https://zenodo.org/records/5213825"
PAPER = "https://pmc.ncbi.nlm.nih.gov/articles/PMC8468268/"
ARCHIVE_MD5 = "85b446b1561133e98d939288d0a1d4e1"
ARCHIVE_BYTES = 830002725
COHORTS = {
    (1920, 1080): {"location": "lobao", "camera": "gopro_hero6", "spectrum": "visible", "expected": 715, "split": "val"},
    (640, 512): {"location": "lobao", "camera": "flir_m232", "spectrum": "thermal", "expected": 866, "split": None},
    (1280, 720): {"location": "valongo", "camera": "zed_stereo", "spectrum": "visible", "expected": 847, "split": "train"},
    (1292, 964): {"location": "vila_do_conde", "camera": "allied_mako_g125", "spectrum": "visible", "expected": 467, "split": "test"},
}


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_annotation(xml_bytes, archive_name):
    """Preserve CVAT/VOC continuous coordinates; never fabricate masks or distance."""
    if b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
        raise ValueError("External XML definitions are not accepted")
    root = ET.fromstring(xml_bytes)
    width, height = (int(root.findtext(f"size/{name}", "0")) for name in ("width", "height"))
    cohort = COHORTS.get((width, height))
    if cohort is None:
        raise ValueError(f"Unknown source camera dimensions: {(width, height)}")
    source_name = root.findtext("filename", "")
    # Filenames in XML retain collection identity; archive basenames were renamed.
    if "Lobao_GoPro" in source_name and (width, height) != (1920, 1080):
        raise ValueError("Source filename contradicts published camera cohort")
    if "ViladoConde" in source_name and (width, height) != (1292, 964):
        raise ValueError("Source filename contradicts published camera cohort")
    annotations = []
    for obj in root.findall("object"):
        if obj.findtext("name", "").strip().lower() != "trunk":
            raise ValueError("Only source class trunk is accepted")
        values = [float(obj.findtext(f"bndbox/{key}", "nan")) for key in ("xmin", "ymin", "xmax", "ymax")]
        x1, y1, x2, y2 = values
        if not all(math.isfinite(v) for v in values) or x2 <= x1 or y2 <= y1:
            raise ValueError("Invalid source box")
        if x1 < -1 or y1 < -1 or x2 > width + 1 or y2 > height + 1:
            raise ValueError("Source box exceeds one-pixel coordinate tolerance")
        x1, y1, x2, y2 = max(0., x1), max(0., y1), min(float(width), x2), min(float(height), y2)
        if x2 <= x1 or y2 <= y1:
            raise ValueError("Source box outside image")
        attributes = {a.findtext("name"): a.findtext("value") for a in obj.findall("attributes/attribute")}
        annotations.append({"label": "tree_trunk", "x": x1 / width, "y": y1 / height,
                            "w": (x2 - x1) / width, "h": (y2 - y1) / height,
                            "source_box_xyxy_pixels": values,
                            "coordinate_clipped": values != [x1, y1, x2, y2],
                            "source_track_id": attributes.get("track_id"),
                            "source_keyframe": attributes.get("keyframe"),
                            "source_occluded": obj.findtext("occluded"),
                            "source_truncated": obj.findtext("truncated"),
                            "source_difficult": obj.findtext("difficult"),
                            "distance_m": None, "path_occupancy": "unknown"})
    original_index = re.search(r"(\d+)(?=\.[^.]+$)", source_name)
    return {"archive_annotation": archive_name, "source_filename": source_name,
            "source_folder": root.findtext("folder"), "source_original_path": root.findtext("path"),
            "source_frame_index": int(original_index.group(1)) if original_index else None,
            "width": width, "height": height, "cohort": dict(cohort), "annotations": annotations}


def choose_records(records, limits, seed):
    """All frames of each forest stay in one split; no random frame-level split."""
    buckets = defaultdict(list)
    for row in records:
        if row["cohort"]["spectrum"] == "visible":
            buckets[row["cohort"]["split"]].append(row)
    chosen = []
    for split in ("train", "val", "test"):
        rows = sorted(buckets[split], key=lambda r: r["archive_annotation"])
        random.Random(f"{seed}:{split}").shuffle(rows)
        chosen.extend(rows[:limits[split]])
    return sorted(chosen, key=lambda r: r["archive_annotation"])


def build_dataset(archive, output, metadata_path, limits, seed=20260926):
    from PIL import Image
    archive, output = Path(archive).resolve(), Path(output).resolve()
    if (output / "dataset.json").exists():
        raise ValueError("Use a new output directory; a frozen manifest already exists")
    if archive.stat().st_size != ARCHIVE_BYTES or digest(archive, "md5") != ARCHIVE_MD5:
        raise ValueError("Only the verified official original ForTrunkDet archive is accepted")
    metadata = json.loads(Path(metadata_path).read_text())
    if metadata.get("metadata", {}).get("license", {}).get("id") != "cc-by-4.0":
        raise ValueError("Official metadata must identify CC BY 4.0")
    recorded = [f for f in metadata.get("files", []) if f.get("key") == "forest_dataset_original.zip"]
    if len(recorded) != 1 or recorded[0].get("checksum") != "md5:" + ARCHIVE_MD5:
        raise ValueError("Official metadata does not match the pinned original archive")
    output.mkdir(parents=True, exist_ok=True)
    source = output / "source"
    source.mkdir(exist_ok=True)
    retained = source / archive.name
    if retained != archive:
        shutil.copy2(archive, retained)
    (source / "zenodo-record.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    (source / "LICENSE-SOURCE.md").write_text(
        "# ForTrunkDet original data\n\n"
        "Creators: Daniel Queirós da Silva and Filipe Neves dos Santos, INESC TEC.\n\n"
        f"Source: {RECORD}; DOI: 10.5281/zenodo.5213825; version 1.0.0.\n\n"
        "Dataset license from the publisher's Zenodo record: CC BY 4.0.\n"
        "License: https://creativecommons.org/licenses/by/4.0/\n\n"
        "Changes: RGB-only subset selection, entire-forest split reassignment, trunk → tree_trunk name mapping, "
        "pixel xyxy → normalized top-left xywh conversion; no synthetic labels. Original archive/XML retained.\n\n"
        f"Cite the dataset and original paper: {PAPER}\n")
    records = []
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive paths")
        for name in names:
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts:
                raise ValueError("Unsafe archive path")
            if name.startswith("Annotations/") and name.endswith(".xml"):
                records.append(parse_annotation(z.read(name), name))
        counts = Counter((r["width"], r["height"]) for r in records)
        if counts != Counter({wh: c["expected"] for wh, c in COHORTS.items()}):
            raise ValueError("Cohort counts disagree with the original paper; inspect source before import")
        selected = choose_records(records, limits, seed)
        images = []
        hashes = {}
        for row in selected:
            stem = PurePosixPath(row["archive_annotation"]).stem
            image_member = f"JPEGImages/{stem}.jpg"
            raw = z.read(image_member)
            sha = hashlib.sha256(raw).hexdigest()
            if sha in hashes:
                raise ValueError(f"Duplicate selected image content: {stem}, {hashes[sha]}")
            hashes[sha] = stem
            with Image.open(io.BytesIO(raw)) as image:
                if image.size != (row["width"], row["height"]):
                    raise ValueError(f"Image/XML dimensions disagree: {stem}")
                if image.mode != "RGB":
                    raise ValueError(f"Selected visible image is not RGB: {stem}")
                image.verify()
            split = row["cohort"]["split"]
            destination = output / "images" / split / f"{stem}.jpg"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            xml_destination = output / "annotations_original" / split / f"{stem}.xml"
            xml_destination.parent.mkdir(parents=True, exist_ok=True)
            xml_destination.write_bytes(z.read(row["archive_annotation"]))
            location = "fortrunk:" + row["cohort"]["location"]
            images.append({"id": "fortrunk-original:" + stem, "path": str(destination), "sha256": sha,
                           "split": split, "location_group": location,
                           # A whole camera/location cohort is a conservative grouping, NOT a confirmed video ID.
                           "video_group": "fortrunk:cohort:" + row["cohort"]["location"] + ":" + row["cohort"]["camera"],
                           "video_group_kind": "whole_collection_cohort_not_confirmed_video",
                           "source_video_id": "unknown", "time_s": None, "location_evidence": PAPER + "#table1",
                           "location_assignment": "original_dimensions_and_complete_cohort_count_match_published_table_1",
                           "review_status": "published_annotations", "reviewed_classes": [],
                           "annotation_coverage": {"tree_trunk": "partial"},
                           "coverage_reason": "Train-only visual audit found unboxed distant trunks and selected lower-trunk extents; full visible-trunk supervision is not verified.",
                           "annotation_source": RECORD, "annotation_license": "CC-BY-4.0",
                           "usage_status": "published_cc_by_4_attribution_retained",
                           "width": row["width"], "height": row["height"], "annotations": row["annotations"],
                           "source_annotation_path": str(xml_destination),
                           "source_annotation_sha256": hashlib.sha256(xml_destination.read_bytes()).hexdigest(),
                           "source_filename": row["source_filename"], "source_frame_index": row["source_frame_index"],
                           "source_cohort": row["cohort"], "distance_m": None,
                           "near_field_verified": False, "path_occupancy": "unknown"})
    data = {"version": 2, "name": "public-fortrunk-v1", "classes": ["tree_trunk"], "images": images,
            "training_admission": "blocked_partial_coverage_standard_yolo_would_treat_unlabelled_trunks_as_background",
            "evaluation_aliases": {"tree trunk": "tree_trunk"},
            "source": {"record": RECORD, "paper": PAPER, "archive": str(retained),
                       "md5": ARCHIVE_MD5, "sha256": digest(archive), "bytes": ARCHIVE_BYTES,
                       "metadata_sha256": digest(metadata_path), "license": "CC-BY-4.0"},
            "selection": {"seed": seed, "limits": limits, "spectrum": "visible_only",
                          "group_split": {c["location"]: c["split"] for c in COHORTS.values() if c["split"]},
                          "thermal_excluded": 866, "publisher_augmented_split_reused": False,
                          "all_source_records": len(records), "selected_counts": dict(Counter(i["split"] for i in images))},
            "annotation_policy": {"geometry": "publisher_axis_aligned_box_no_masks",
                                  "coordinates": "continuous_source_xyxy_no_plus_or_minus_one; clip <=1px overshoot, retain originals",
                                  "names": {"trunk": "tree_trunk"}, "labels_generated": False,
                                  "source_annotation_review": "publisher_manual_CVAT; not independently reviewed by SkyCompanion"},
            "limitations": ["A forest detection research task, not proof of urban close-range obstacle performance.",
                            "Each split has a different forest AND camera; geographic and camera shifts are confounded.",
                            "Published boxes can omit distant trunks; inspect completeness before acceptance.",
                            "Original videos, timing and reliable metric depth are unavailable; do not infer time from image numbers.",
                            "Physical proximity, path occupancy, speech latency, mobile FPS and interruptions cannot be certified from these still images.",
                            "Sequence IDs unknown; entire location/camera cohort assigned together to prevent possible adjacent frames crossing splits.",
                            "Original paper excluded excessive blur/glare; these failure modes need separate urban regression."]}
    sys.path.insert(0, str(ROOT / "backend"))
    from app.obstacle_eval import validate_dataset, dataset_readiness
    validate_dataset(data)
    data["readiness"] = dataset_readiness(data)
    (output / "dataset.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    summary = {"status": "imported_quarantined_partial_coverage_not_trainable_by_standard_yolo", "images": len(images),
               "split_images": dict(Counter(im["split"] for im in images)),
               "split_boxes": {s: sum(len(im["annotations"]) for im in images if im["split"] == s) for s in limits},
               "archive_md5_verified": True, "thermal_excluded": 866,
               "clipped_boxes": sum(b["coordinate_clipped"] for im in images for b in im["annotations"]),
               "dataset_sha256": digest(output / "dataset.json"), "readiness": data["readiness"]}
    (output / "import-report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-limit", type=int, default=800)
    parser.add_argument("--val-limit", type=int, default=150)
    parser.add_argument("--test-limit", type=int, default=150)
    parser.add_argument("--seed", type=int, default=20260926)
    args = parser.parse_args()
    limits = {s: getattr(args, s + "_limit") for s in ("train", "val", "test")}
    if any(n < 1 for n in limits.values()):
        parser.error("Each split must have a positive image limit")
    print(json.dumps(build_dataset(args.archive, args.output, args.metadata, limits, args.seed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
