"""No model execution: verify export refuses unknown and ignore supervision."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from train_obstacles import validate_training_data


class PublicTrainingGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = {'classes': ['pole', 'column'], 'images': []}
        for split in ('train', 'val', 'test'):
            path = Path(self.temporary.name) / (split + '.jpg')
            path.write_bytes(('unique-bytes-' + split).encode())
            self.data['images'].append({
                'id': split, 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'split': split, 'video_group': split + '-video', 'location_group': split + '-location',
                'route_group': split + '-route', 'review_status': 'published_annotations',
                'reviewed_classes': ['pole', 'column'], 'annotation_coverage': {'pole': 'complete', 'column': 'complete'},
                'annotation_source': 'https://example.invalid/published-annotations', 'annotation_license': 'CC-BY-4.0',
                'annotations': [{'label': 'pole', 'x': .3, 'y': 0., 'w': .1, 'h': .8}],
                'human_reviewed': False,
            })

    def reviewed(self, data):
        result = deepcopy(data)
        for image in result['images']:
            image['review_status'] = 'human_verified'
            image['human_reviewed'] = True
        return result

    def assert_rejected_in_both_modes(self, data, message):
        for research, dataset in ((True, data), (False, self.reviewed(data))):
            with self.subTest(research=research), self.assertRaisesRegex(ValueError, message):
                validate_training_data(dataset, research_published=research)

    def test_publisher_research_never_promotes_human_or_acceptance_status(self):
        before = deepcopy(self.data)
        readiness = validate_training_data(self.data, research_published=True)
        self.assertEqual(self.data, before)
        self.assertFalse(readiness['ready_for_supervised_training'])
        self.assertEqual(readiness['complete_human_verified_images'], 0)
        self.assertEqual(readiness['complete_reviewed_images'], 0)

    def test_full_human_review_still_works_without_research_override(self):
        readiness = validate_training_data(self.reviewed(self.data))
        self.assertTrue(readiness['ready_for_supervised_training'])

    def test_partial_unknown_missing_and_empty_explicit_coverage_are_rejected(self):
        for coverage in ({}, {'pole': 'complete'}, {'pole': 'partial', 'column': 'complete'},
                         {'pole': 'complete', 'column': 'unknown'}, None, []):
            data = deepcopy(self.data)
            data['images'][0]['annotation_coverage'] = coverage
            with self.subTest(coverage=coverage):
                self.assert_rejected_in_both_modes(data, 'complete coverage')

    def test_legacy_complete_publisher_contract_is_retained(self):
        for image in self.data['images']:
            image.pop('annotation_coverage')
        readiness = validate_training_data(self.data, research_published=True)
        self.assertFalse(readiness['ready_for_supervised_training'])
        self.data['images'][0]['reviewed_classes'] = ['pole']
        with self.assertRaisesRegex(ValueError, 'complete attributed'):
            validate_training_data(self.data, research_published=True)

    def test_ignore_regions_are_not_silently_background(self):
        self.data['images'][0]['ignore_regions'] = [{'x': 0., 'y': 0., 'w': .5, 'h': 1., 'reason': 'unreviewed'}]
        self.assert_rejected_in_both_modes(self.data, 'ignore-region')

    def test_annotation_ignore_and_crowd_are_not_exported_as_positives(self):
        for flag in ('ignore', 'iscrowd'):
            data = deepcopy(self.data)
            data['images'][0]['annotations'][0][flag] = 1
            with self.subTest(flag=flag):
                self.assert_rejected_in_both_modes(data, 'Ignored or crowd')

    def test_false_ignore_and_zero_crowd_do_not_remove_valid_targets(self):
        annotation = self.data['images'][0]['annotations'][0]
        annotation.update(ignore=False, iscrowd=0)
        validate_training_data(self.data, research_published=True)
        self.assertEqual(len(self.data['images'][0]['annotations']), 1)

    def test_known_route_leak_rejected_even_with_unique_images_and_videos(self):
        self.data['images'][0]['route_group'] = 'same-route'
        self.data['images'][2]['route_group'] = 'same-route'
        self.assert_rejected_in_both_modes(self.data, 'route_group crosses')

    def test_unknown_geography_allowed_only_as_unaccepted_public_research(self):
        for image in self.data['images']:
            image['video_group'] = 'unknown-publisher-video'
            image['location_group'] = 'unknown-publisher-location'
            image['route_group'] = None
        readiness = validate_training_data(self.data, research_published=True)
        self.assertFalse(readiness['ready_for_supervised_training'])
        self.assertTrue(any('location_group' in blocker for blocker in readiness['blockers']))
        with self.assertRaisesRegex(ValueError, 'video, location'):
            validate_training_data(self.reviewed(self.data))

    def test_draft_pseudo_labels_cannot_use_publisher_override(self):
        self.data['images'][0]['review_status'] = 'assistant_draft'
        with self.assertRaisesRegex(ValueError, 'not predictions'):
            validate_training_data(self.data, research_published=True)

    def test_publisher_attribution_is_required(self):
        self.data['images'][0].pop('annotation_source')
        with self.assertRaisesRegex(ValueError, 'attributed'):
            validate_training_data(self.data, research_published=True)

    def test_training_permission_is_not_bypassed_by_research(self):
        self.data['images'][0]['usage_status'] = 'license_review_required'
        self.assert_rejected_in_both_modes(self.data, 'permission remains unresolved')

    def test_all_three_splits_required(self):
        self.data['images'] = self.data['images'][:2]
        with self.assertRaisesRegex(ValueError, 'train/val/test'):
            validate_training_data(self.data, research_published=True)


if __name__ == '__main__':
    unittest.main()
