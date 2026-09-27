import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("public_duplicate_audit", ROOT/"scripts/audit_public_duplicates.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def source(identity=1, **changes):
    return dict(id=identity, image_id=10, category_id=1, bbox=[10, 20, 20, 30],
                segmentation=[[10,20,30,20,30,50,10,50]], iscrowd=0,
                attributes={"occluded": False}, area=600, **changes)


def fixture():
    box = dict(label="pole", x=.1, y=.2, w=.2, h=.3, source_annotation_id=1)
    image = dict(id="one", source_image_id=10, split="test", annotations=[box, dict(box, source_annotation_id=2)],
                 review_status="published_annotations", reviewed_classes=["pole"],
                 annotation_coverage={"pole":"complete"}, source_annotation_path="source.json")
    return dict(name="fixture", classes=["pole"], images=[image]), {"one":[source(1),source(2)]}


class StrictDuplicateAuditTests(unittest.TestCase):
    def test_removes_only_second_exact_source_record_and_preserves_review(self):
        data, sources = fixture()
        original = copy.deepcopy(data)
        revised, ledger = audit.deduplicate_manifest(data, sources)
        self.assertEqual(data, original)
        self.assertEqual(len(revised["images"][0]["annotations"]), 1)
        self.assertEqual(ledger[0]["removed_source_annotation_id"], 2)
        self.assertEqual(ledger[0]["kept_source_annotation_id"], 1)
        self.assertEqual(revised["images"][0]["review_status"], "published_annotations")
        self.assertEqual(revised["images"][0]["annotation_coverage"], {"pole":"complete"})

    def test_mask_attributes_crowd_area_or_any_extra_source_field_prevent_deletion(self):
        variants = [("segmentation", [[10,20,30,20,30,49,10,50]]), ("bbox", [10,20,20,31]),
                    ("iscrowd", 1), ("attributes", {"occluded":True}), ("area",601), ("other", "different")]
        for key, value in variants:
            with self.subTest(key=key):
                data, sources = fixture()
                sources["one"][1][key] = value
                revised, ledger = audit.deduplicate_manifest(data, sources)
                self.assertEqual(ledger, [])
                self.assertEqual(len(revised["images"][0]["annotations"]),2)

    def test_distinct_classes_or_images_are_never_combined(self):
        data, sources = fixture()
        sources["one"][1]["category_id"] = 2
        data["images"][0]["annotations"][1]["label"] = "column"
        self.assertEqual(audit.deduplicate_manifest(data,sources)[1],[])
        data, sources = fixture()
        sources["one"][1]["image_id"] = 11
        with self.assertRaisesRegex(ValueError,"identity mismatch"):
            audit.deduplicate_manifest(data,sources)

    def test_keep_smallest_id_independent_of_input_order(self):
        data, sources = fixture()
        data["images"][0]["annotations"].reverse()
        sources["one"].reverse()
        revised, ledger = audit.deduplicate_manifest(data,sources)
        self.assertEqual(revised["images"][0]["annotations"][0]["source_annotation_id"],1)
        self.assertEqual(ledger[0]["removed_source_annotation_id"],2)

    def test_inconsistent_derived_attributes_rejected(self):
        data, sources = fixture()
        data["images"][0]["annotations"][1]["ignore"] = True
        with self.assertRaisesRegex(ValueError,"inconsistent derived"):
            audit.deduplicate_manifest(data,sources)

    def test_repeated_source_id_and_incomplete_geometry_rejected(self):
        data, sources = fixture()
        sources["one"][1]["id"] = 1
        with self.assertRaisesRegex(ValueError,"Repeated source"):
            audit.deduplicate_manifest(data,sources)
        record=source()
        record.pop("segmentation")
        with self.assertRaisesRegex(ValueError,"Strict deduplication"):
            audit.source_key(record)

    def test_archive_and_source_copy_must_match_pinned_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            data,sources=fixture()
            member="annotations/publisher.json"
            archive=folder/"annotations.zip"
            with zipfile.ZipFile(archive,"w") as z:
                z.writestr(member,json.dumps({"annotations":sources["one"]}))
            path=folder/"copy.json"
            path.write_text(json.dumps({"annotations":sources["one"]}))
            data["source"]={"annotation_archive_sha256":audit.digest(archive)}
            data["images"][0].update(annotation_source="https://source/#"+member,source_annotation_path=str(path),source_annotation_sha256=audit.digest(path))
            self.assertEqual(audit.verified_archive_sources(data,archive),sources)
            path.write_text(json.dumps({"annotations":sources["one"][:1]}))
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                audit.verified_archive_sources(data,archive)
            data["images"][0]["source_annotation_sha256"]=audit.digest(path)
            with self.assertRaisesRegex(ValueError,"differs from pinned"):
                audit.verified_archive_sources(data,archive)

    def test_fixed_recount_uses_original_thresholds_and_not_new_holdout(self):
        data,sources=fixture()
        revised,_=audit.deduplicate_manifest(data,sources)
        metadata=dict(sha256="frozen",family="fixture",names={"0":"pole"},ultralytics="test",imgsz=960)
        fp={k:metadata[k] for k in ("sha256","family","names","ultralytics")}
        settings={"candidate":{"imgsz":960,"thresholds":{"pole":.5}}}
        lock=dict(locked_settings=settings,model_fingerprints={"candidate":fp},aliases=audit.ALIASES,iou_threshold=.5)
        prediction=dict(data["images"][0]["annotations"][0], confidence=.6)
        raw={"one":[prediction,dict(prediction,x=.7,confidence=.1)]}
        filtered={"one":[prediction]}
        report=dict(locked_settings=settings,model_fingerprints={"candidate":fp},test={"candidate":{"evaluation":audit.score_split(data,filtered)}})
        cache=dict(metadata=metadata,predictions=filtered,raw_predictions=raw)
        result=audit.frozen_recount(data,revised,report,lock,{"candidate":cache})
        self.assertFalse(result["new_holdout"])
        self.assertFalse(result["model_inference_performed"])
        self.assertFalse(result["threshold_selection_performed"])
        self.assertEqual(result["locked_settings"],settings)
        self.assertEqual(result["models"]["candidate"]["per_class_revision_delta"]["pole"],dict(tp=0,fp=0,fn=-1))
        self.assertEqual(result["models"]["candidate"]["deduplicated"]["per_class"]["pole"]["fp"],0)
        for tamper in ("fingerprint","threshold","frozen_counts"):
            badcache,badlock,badreport=copy.deepcopy(cache),copy.deepcopy(lock),copy.deepcopy(report)
            if tamper=="fingerprint": badcache["metadata"]["sha256"]="wrong"
            if tamper=="threshold": badlock["locked_settings"]["candidate"]["thresholds"]["pole"]=.05
            if tamper=="frozen_counts": badreport["test"]["candidate"]["evaluation"]["per_class"]["pole"]["tp"]=99
            with self.subTest(tamper=tamper),self.assertRaises(ValueError):
                audit.frozen_recount(data,revised,badreport,badlock,{"candidate":badcache})


if __name__ == "__main__":
    unittest.main()
