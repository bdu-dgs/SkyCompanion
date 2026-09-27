import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import evaluate_public_candidate as public_eval


def box(label="pole", x=.3, confidence=.9, **extra):
    return dict(label=label, x=x, y=.2, w=.1, h=.6, confidence=confidence, **extra)


def sample(identifier="a", label="pole", coverage="complete", **extra):
    return dict(id=identifier, annotations=[box(label)], reviewed_classes=[label] if coverage == "complete" else [],
                annotation_coverage={label: coverage}, review_status="published_annotations", **extra)


class PublicCandidateEvaluationTests(unittest.TestCase):
    def test_missing_classes_are_unknown_not_negative(self):
        data = dict(classes=["pole", "tree_trunk"], images=[sample()])
        result = public_eval.score_split(data, {"a": [box(), box("tree trunk", x=.6)]})["per_class"]
        self.assertEqual((result["pole"]["tp"], result["pole"]["fp"]), (1, 0))
        self.assertEqual(result["tree_trunk"]["fp"], 0)
        self.assertIsNone(result["tree_trunk"]["precision"])
        self.assertEqual(result["tree_trunk"]["unscored_predictions_unknown_coverage"], 1)

    def test_partial_images_do_not_inflate_complete_precision(self):
        data = dict(classes=["pole"], images=[sample("complete"), sample("partial", coverage="partial")])
        result = public_eval.score_split(data, {"complete": [box(x=.7)], "partial": [box(), box(x=.7)]})["per_class"]["pole"]
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (0, 1, 1))
        self.assertEqual(result["precision"], 0)
        self.assertEqual(result["partial_known_targets"]["recall"], 1)
        self.assertIsNone(result["partial_known_targets"]["precision"])
        self.assertEqual(result["unscored_predictions_unknown_coverage"], 1)

    def test_ignore_is_class_scoped_and_never_erases_known_positive_hit(self):
        im = sample(ignore_regions=[dict(x=0, y=0, w=1, h=1, labels=["pole"], reason="partly reviewed")])
        im["reviewed_classes"].append("column")
        result = public_eval.score_split(dict(classes=["pole", "column"], images=[im]),
                                         {"a": [box(), box(x=.7), box("column", x=.7)]})["per_class"]
        self.assertEqual((result["pole"]["tp"], result["pole"]["fp"], result["pole"]["ignored_predictions"]), (1, 0, 1))
        self.assertEqual(result["column"]["fp"], 1)

    def test_duplicate_box_only_matches_once_and_big_box_is_not_correct(self):
        data = dict(classes=["pole"], images=[sample()])
        result = public_eval.score_split(data, {"a": [box(), box()]})["per_class"]["pole"]
        self.assertEqual((result["tp"], result["fp"]), (1, 1))
        result = public_eval.score_split(data, {"a": [dict(label="pole", x=0, y=0, w=1, h=1, confidence=.99)]})["per_class"]["pole"]
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (0, 1, 1))

    def test_tree_and_concrete_are_not_silently_renamed(self):
        guesses = {"a": [box("tree"), box("concrete block"), box("tree trunk"), box("boulder"), box("traffic cone")]}
        actual = public_eval.normalize_predictions(guesses, ["tree_trunk", "rock", "traffic_cone"])
        self.assertEqual([b["label"] for b in actual["a"]], ["tree_trunk", "rock", "traffic_cone"])

    def test_near_metric_requires_explicit_reviewed_attribute(self):
        im = sample()
        data = dict(classes=["pole"], images=[im])
        row = public_eval.score_split(data, {})["per_class"]["pole"]
        self.assertIsNone(row["known_target_attributes"]["near_in_image"]["miss_rate"])
        im["annotations"][0]["attributes"] = {"near_in_image": True, "truncated": True}
        row = public_eval.score_split(data, {})["per_class"]["pole"]
        self.assertEqual(row["known_target_attributes"]["near_in_image"]["miss_rate"], 1)

    def test_unreviewed_predictions_never_become_truth(self):
        im = sample()
        im["review_status"] = "assistant_draft"
        row = public_eval.score_split(dict(classes=["pole"], images=[im]), {"a": [box()]})["per_class"]["pole"]
        self.assertEqual((row["tp"], row["fp"], row["fn"]), (0, 0, 0))
        self.assertEqual(row["coverage"]["unknown"], 1)

    def test_class_without_complete_validation_positive_cannot_be_calibrated(self):
        data = dict(classes=["pole", "rock"], images=[sample()])
        grid = [{"imgsz": 640, "threshold": .1, "evaluation": public_eval.score_split(data, {"a": [box()]})}]
        settings = public_eval.choose_settings(grid, data["classes"])
        self.assertEqual(settings["thresholds"], {"pole": .1, "rock": None})
        im = sample(coverage="partial")
        grid = [{"imgsz": 640, "threshold": .1, "evaluation": public_eval.score_split(dict(classes=["pole"], images=[im]), {"a": [box()]})}]
        with self.assertRaisesRegex(ValueError, "No fully annotated"):
            public_eval.choose_settings(grid, ["pole"])

    def test_coverage_preserves_publisher_geometry_and_missing_targets(self):
        im = sample(split="test", geometry_unused=True)
        im["annotations"][0]["geometry_scope"] = "visible_component_bbox"
        report = public_eval.coverage_report(dict(classes=["pole"], images=[im]))
        self.assertEqual(report["review_provenance"], {"published_annotations": 1})
        self.assertEqual(report["geometry_scopes"], {"visible_component_bbox": 1})
        self.assertFalse(report["by_split"]["test"]["column"]["in_model_training_vocabulary"])
        self.assertEqual(report["unknown_group_images"]["location_group"], 1)

    def test_route_cannot_leak_even_if_video_ids_differ(self):
        with tempfile.TemporaryDirectory() as temporary:
            images = []
            for split in ("val", "test"):
                path = Path(temporary) / split
                path.write_bytes(split.encode())
                images.append(sample(split, path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                     split=split, video_group=split, location_group="unknown:publisher", route_group="same-route"))
            with self.assertRaisesRegex(ValueError, "route_group"):
                public_eval.validate_public_manifest(dict(classes=["pole"], images=images))

    def test_coverage_reads_legacy_split_policy_without_claiming_extra_provenance(self):
        policy = {"train_cities": ["pittsburgh"], "val_cities": ["boston"], "test_cities": ["charlotte"]}
        data = dict(classes=["pole"], images=[sample(split="val")], split_policy=policy)
        result = public_eval.coverage_report(data)
        self.assertEqual(result["split_provenance"], policy)
        self.assertEqual(result["split_provenance_source"], "split_policy")
        data["split_provenance"] = {"status": "explicit_provenance"}
        result = public_eval.coverage_report(data)
        self.assertEqual(result["split_provenance"], {"status": "explicit_provenance"})
        self.assertEqual(result["split_provenance_source"], "split_provenance")
        data.pop("split_provenance")
        data["split_policy"] = "Publisher split; geography unknown."
        self.assertEqual(public_eval.coverage_report(data)["split_provenance"], data["split_policy"])
        data.pop("split_policy")
        result = public_eval.coverage_report(data)
        self.assertEqual(result["split_provenance"], {"status": "unknown"})
        self.assertEqual(result["split_provenance_source"], "unavailable")

    def test_static_evaluation_never_fabricates_mobile_metrics(self):
        metrics = public_eval.unavailable_runtime_metrics()
        self.assertIn("actual_speech_onset_latency_ms", metrics)
        self.assertTrue(all(m["status"] == "not_verified" and m["value"] is None for m in metrics.values()))

    def test_image_area_bins_have_fixed_inclusive_boundary_rules(self):
        for area, expected in ((.000999, "image-area-tiny"), (.001, "image-area-small"),
                               (.009999, "image-area-small"), (.01, "image-area-medium"),
                               (.099999, "image-area-medium"), (.1, "image-area-large"), (1., "image-area-large")):
            with self.subTest(area=area):
                self.assertEqual(public_eval.image_area_group({"w": area, "h": 1.}), expected)

    def test_one_prediction_cannot_be_counted_again_in_another_image_area_bin(self):
        small = dict(label="pole", x=.3, y=.2, w=.05, h=.18, truncated=True)
        medium = dict(label="pole", x=.3, y=.2, w=.06, h=.18, truncated=False)
        im = sample()
        im["annotations"] = [small, medium]
        data = dict(classes=["pole"], images=[im])
        predictions = {"a": [dict(small, confidence=.9)]}
        row = public_eval.score_split(data, predictions)["per_class"]["pole"]
        original = public_eval.evaluate(data, predictions)["per_class"]["pole"]
        for key in ("tp", "fp", "fn", "precision", "recall"):
            self.assertEqual(row[key], original[key])
        diagnostics = row["target_recall_diagnostics"]
        self.assertEqual((row["tp"], row["fn"]), (1, 1))
        self.assertEqual(diagnostics["image_area"]["image-area-small"]["tp"], 1)
        self.assertEqual(diagnostics["image_area"]["image-area-medium"]["fn"], 1)
        self.assertEqual(diagnostics["image_area"]["image-area-medium"]["tp"], 0)
        self.assertEqual(diagnostics["truncated"]["true"]["tp"], 1)
        self.assertEqual(diagnostics["truncated"]["false"]["fn"], 1)
        self.assertEqual(sum(group["targets"] for group in diagnostics["image_area"].values()), row["tp"] + row["fn"])

    def test_image_area_diagnostics_exclude_partial_and_unreviewed_targets(self):
        complete, partial, draft = sample("complete"), sample("partial", coverage="partial"), sample("draft")
        draft["review_status"] = "assistant_draft"
        data = dict(classes=["pole"], images=[complete, partial, draft])
        predictions = {im["id"]: [box()] for im in data["images"]}
        row = public_eval.score_split(data, predictions)["per_class"]["pole"]
        groups = row["target_recall_diagnostics"]["image_area"]
        self.assertEqual(sum(group["targets"] for group in groups.values()), 1)
        self.assertEqual(row["partial_known_targets"]["tp"], 1)

    def test_truncation_keeps_true_false_and_unknown_separate(self):
        im = sample()
        im["annotations"] = [dict(box(x=.1), attributes={"truncated": True}),
                             dict(box(x=.3), truncated=False),
                             dict(box(x=.5), truncated=True, attributes={"truncated": None}),
                             dict(box(x=.7), truncated="0")]
        row = public_eval.score_split(dict(classes=["pole"], images=[im]), {})["per_class"]["pole"]
        groups = row["target_recall_diagnostics"]["truncated"]
        self.assertEqual({name: group["targets"] for name, group in groups.items()}, {"true": 1, "false": 1, "unknown": 2})
        self.assertTrue(all(group["recall"] == 0 for group in groups.values()))

    def test_component_recall_is_explicitly_semantic_region_not_verified_instance(self):
        data = dict(classes=["pole"], images=[sample(split="test")], geometry_scope="visible_component_bbox")
        row = public_eval.score_split(data, {"a": [box()]})["per_class"]["pole"]
        group = row["target_recall_diagnostics"]["geometry_scope"]["visible_component_bbox"]
        self.assertEqual(group["tp"], 1)
        self.assertIn("semantic connected-region", group["interpretation"])
        self.assertIn("Not verified object instances", group["interpretation"])
        self.assertEqual(public_eval.coverage_report(data)["geometry_scopes"], {"visible_component_bbox": 1})

    def test_missing_output_names_are_visible_without_inventing_roadwork_aliases(self):
        classes = ["traffic_cone", "construction_fence", "construction_barricade", "construction_barrier"]
        metadata = {"names": {0: "traffic cone", 1: "fence", 2: "construction barrier"}}
        report = public_eval.model_vocabulary_coverage(metadata, classes)
        self.assertEqual(report["missing_exact_or_approved_alias"], ["construction_fence", "construction_barricade"])
        self.assertEqual(report["approved_output_names_by_dataset_class"]["construction_barrier"], ["construction barrier"])
        self.assertEqual(report["dataset_classes"], classes)
        self.assertEqual(public_eval.model_vocabulary_coverage({}, classes)["status"], "unknown")

    def test_diagnostic_strata_cannot_change_formal_parameter_selection(self):
        data = dict(classes=["pole"], images=[sample()])
        grid = [{"imgsz": 640, "threshold": .1, "evaluation": public_eval.score_split(data, {"a": [box(), box(x=.7)]})},
                {"imgsz": 640, "threshold": .7, "evaluation": public_eval.score_split(data, {"a": [box()]})}]
        before = public_eval.choose_settings(grid, ["pole"])
        for row in grid:
            row["evaluation"]["per_class"]["pole"]["target_recall_diagnostics"] = {"fake_optimistic_diagnostic": row["threshold"] == .1}
        after = public_eval.choose_settings(grid, ["pole"])
        self.assertEqual(before, after)
        self.assertEqual(after["thresholds"]["pole"], .7)

    def test_both_models_are_locked_before_test_inference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = []
            for split in ("val", "test"):
                path = root / (split + ".jpg")
                path.write_bytes(split.encode())
                images.append(sample(split, path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                     split=split, video_group=split, location_group=split, route_group=split))
            dataset = root / "dataset.json"
            dataset.write_text(json.dumps(dict(classes=["pole"], images=images)))
            weights = root / "candidate.pt"
            weights.write_bytes(b"fixture-not-real-weights")
            output = root / "out"
            calls = []

            class FakeDetector:
                def metadata(self):
                    return {"test_double": True, "sha256": hashlib.sha256(weights.read_bytes()).hexdigest(), "names": {0: "pole"}}

            def fake_collect(detector, frames):
                split = frames[0]["split"]
                calls.append(split)
                if split == "test":
                    lock = json.loads((output / "validation-lock.json").read_text())
                    self.assertEqual(set(lock["locked_settings"]), {"baseline_v7", "candidate"})
                    self.assertEqual(calls[:2], ["val", "val"])
                return {frame["id"]: [box()] for frame in frames}, {"samples": len(frames), "scope": "test_double"}

            argv = ["evaluate_public_candidate.py", str(dataset), "--candidate", str(weights), "--output", str(output),
                    "--sizes", "640", "--baseline-sizes", "960", "--thresholds", ".1", ".7"]
            with patch.object(sys, "argv", argv), patch.object(public_eval, "make_detector", return_value=FakeDetector()), patch.object(public_eval, "collect", side_effect=fake_collect):
                public_eval.main()
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(calls, ["val", "val", "test", "test"])
            self.assertEqual(report["locked_settings"]["candidate"]["thresholds"]["pole"], .7)
            self.assertFalse(report["deployment_allowed"])
            self.assertEqual(report["test"]["candidate"]["evaluation"]["per_class"]["pole"]["tp"], 1)
            self.assertEqual(report["dataset_classes"], ["pole"])
            self.assertEqual(report["output_vocabulary_coverage"]["baseline_v7"]["missing_exact_or_approved_alias"], [])


if __name__ == "__main__":
    unittest.main()
