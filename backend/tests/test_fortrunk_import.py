"""Guard source interpretation and prevent frame-level leakage in public import."""
import importlib.util
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location("fortrunk_import", Path(__file__).resolve().parents[2] / "scripts/import_fortrunk_public.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def xml(width=1280, height=720, name="img0001.jpg", x1=10, y1=20, x2=100, y2=600, label="trunk"):
    return f'''<annotation><filename>{name}</filename><size><width>{width}</width><height>{height}</height></size>
    <object><name>{label}</name><occluded>1</occluded><bndbox><xmin>{x1}</xmin><ymin>{y1}</ymin>
    <xmax>{x2}</xmax><ymax>{y2}</ymax></bndbox><attributes><attribute><name>track_id</name><value>7</value></attribute></attributes></object></annotation>'''.encode()


class ForTrunkImportTests(unittest.TestCase):
    def test_published_coordinates_preserved_not_tree_crown_relabel(self):
        row = module.parse_annotation(xml(), "Annotations/img1582.xml")
        box = row["annotations"][0]
        assert row["cohort"]["location"] == "valongo"
        assert box["x"] == 10 / 1280 and box["w"] == 90 / 1280
        assert box["source_track_id"] == "7" and box["source_occluded"] == "1"
        assert box["distance_m"] is None and box["path_occupancy"] == "unknown"
        with self.assertRaisesRegex(ValueError, "Only source class"):
            module.parse_annotation(xml(label="tree"), "Annotations/x.xml")


    def test_reject_incompatible_source_and_invalid_boxes(self):
        for raw in (xml(width=100), xml(x1=float("nan")), xml(x2=10), xml(x2=1300),
                    xml(name="Lobao_GoPro/JPEGImages/img1.jpg")):
            with self.assertRaises(ValueError):
                module.parse_annotation(raw, "Annotations/x.xml")
        with self.assertRaisesRegex(ValueError, "External XML"):
            module.parse_annotation(b'<!DOCTYPE annotation>' + xml(), "Annotations/x.xml")


    def test_clip_only_tiny_published_edge_overshoot_with_provenance(self):
        box = module.parse_annotation(xml(x1=-.3, x2=1280.4), "Annotations/x.xml")["annotations"][0]
        assert box["x"] == 0 and box["w"] == 1 and box["coordinate_clipped"]
        assert box["source_box_xyxy_pixels"] == [-.3, 20., 1280.4, 600.]


    def test_whole_forest_isolation_excludes_thermal_before_sampling(self):
        records = []
        for wh in module.COHORTS:
            for i in range(10):
                row = module.parse_annotation(xml(*wh, y2=min(600, wh[1] - 1)), f"Annotations/{wh[0]}-{i}.xml")
                records.append(row)
        rows = module.choose_records(records, {"train": 4, "val": 3, "test": 2}, 8)
        assert len(rows) == 9
        assert all(r["cohort"]["spectrum"] == "visible" for r in rows)
        assignments = {}
        for row in rows:
            cohort = row["cohort"]
            assignments.setdefault(cohort["location"], set()).add(cohort["split"])
        assert assignments == {"valongo": {"train"}, "lobao": {"val"}, "vila_do_conde": {"test"}}
        assert rows == module.choose_records(list(reversed(records)), {"train": 4, "val": 3, "test": 2}, 8)

    def test_archive_image_pairing_and_attribution_in_imported_fixture(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "fixture.zip"
            with zipfile.ZipFile(archive, "w") as output:
                for i, wh in enumerate(module.COHORTS):
                    # Original names intentionally differ from renamed ZIP names.
                    output.writestr(f"Annotations/img{i}.xml", xml(*wh, name="img999.jpg", y2=min(600, wh[1] - 1)))
                    buffer = io.BytesIO()
                    Image.new("RGB", wh, (30 * i, 10, 20)).save(buffer, "JPEG")
                    output.writestr(f"JPEGImages/img{i}.jpg", buffer.getvalue())
            md5 = hashlib.md5(archive.read_bytes()).hexdigest()
            metadata = root / "metadata.json"
            metadata.write_text(json.dumps({"metadata": {"license": {"id": "cc-by-4.0"}},
                                           "files": [{"key": "forest_dataset_original.zip", "checksum": "md5:" + md5}]}))
            cohorts = {wh: dict(c, expected=1) for wh, c in module.COHORTS.items()}
            with patch.object(module, "ARCHIVE_MD5", md5), patch.object(module, "ARCHIVE_BYTES", archive.stat().st_size), patch.object(module, "COHORTS", cohorts):
                report = module.build_dataset(archive, root / "out", metadata, {"train": 1, "val": 1, "test": 1})
            manifest = json.loads((root / "out/dataset.json").read_text())
            assert report["images"] == 3
            assert manifest["classes"] == ["tree_trunk"]
            assert all(im["source_filename"] == "img999.jpg" for im in manifest["images"])
            assert all(im["review_status"] == "published_annotations" for im in manifest["images"])
            assert all(im["annotation_coverage"] == {"tree_trunk": "partial"} and im["reviewed_classes"] == [] for im in manifest["images"])
            assert all(im["source_video_id"] == "unknown" and im["time_s"] is None for im in manifest["images"])
            assert all(Path(im["source_annotation_path"]).is_file() for im in manifest["images"])
            assert not manifest["readiness"]["ready_for_supervised_training"]
            trainer_spec = importlib.util.spec_from_file_location("fortrunk_training_gate", Path(__file__).resolve().parents[2] / "scripts/train_obstacles.py")
            trainer = importlib.util.module_from_spec(trainer_spec)
            trainer_spec.loader.exec_module(trainer)
            with self.assertRaisesRegex(ValueError, "complete coverage"):
                trainer.validate_training_data(manifest, research_published=True)


if __name__ == "__main__":
    unittest.main()
