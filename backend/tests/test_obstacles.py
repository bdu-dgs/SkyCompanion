import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.obstacle_capture import EvidenceBuffer
from app.obstacle_eval import evaluate, validate_dataset, dataset_readiness, reviewed_for_training
from app.obstacle_risk import RiskMonitor, validate_corridor
from app.obstacle_models import CLASSES, VOCABULARY_VERSION, LocalDetector


def box(label='train', x=.4, confidence=.9):
    return dict(label=label, x=x, y=.5, w=.15, h=.4, confidence=confidence)


class ObstacleTests(unittest.TestCase):
    def test_expanded_vocabulary_keeps_original_categories_and_versioned_config(self):
        names = [name for name, _ in CLASSES]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({'chair', 'dining table', 'dog', 'parking meter', 'fire hydrant',
                         'concrete block', 'fence', 'monument', 'pillar'} <= set(names))
        self.assertGreaterEqual(len(names), 80)
        detector = LocalDetector(device='cpu')
        self.assertEqual(detector.path.name, f'skycompanion-yoloe-11s-v{VOCABULARY_VERSION}.pt')
        self.assertEqual(detector.imgsz, 960)
        self.assertEqual(detector.confidence, .25)

    def test_unknown_name_and_same_level_changes_are_spaced(self):
        monitor = RiskMonitor()
        corridor = [[0,0],[1,0],[1,1],[0,1]]
        self.assertIsNone(monitor.update([box()], corridor, 0)['event'])
        self.assertIsNone(monitor.update([box()], corridor, .2)['event'])
        result = monitor.update([box()], corridor, .5)
        self.assertNotIn('train', result['text'])
        self.assertIn('Possible obstacle', result['text'])
        self.assertIsNotNone(result['event'])
        for t in [1., 1.2, 1.5]:
            result = monitor.update([box(x=.8)], corridor, t)
        self.assertIsNone(result['event'])
        for t in [8., 8.2, 8.5]:
            result = monitor.update([box(x=.8)], corridor, t)
        self.assertIsNotNone(result['event'])
        self.assertEqual(result['event']['direction'], 'right')
        self.assertIn('new_relevance', result['event']['reason_codes'])
        monitor.reset()
        self.assertIsNone(monitor.update([box()],corridor,9)['event'])

    def test_no_claim_without_corridor_or_with_empty_scene(self):
        monitor = RiskMonitor()
        self.assertEqual(monitor.update([box()],None,1)['state'],'unconfigured')
        result = monitor.update([],[[0,0],[1,0],[1,1],[0,1]],2)
        self.assertIsNone(result['event'])
        self.assertIn('does not mean the path is clear',result['text'])
        with self.assertRaises(ValueError):
            validate_corridor([[0,0],[float('nan'),1],[1,0]])

    def test_duplicate_detection_and_partial_coverage(self):
        im = dict(id='a',review_status='assistant_reviewed',reviewed_classes=['fence','train'],
                  annotations=[box('fence')])
        data = dict(classes=['fence','train','person'],images=[im])
        result = evaluate(data,{'a':[box('fence'),box('fence'),box('train'),box('person')]})['per_class']
        self.assertEqual((result['fence']['tp'],result['fence']['fp']),(1,1))
        self.assertEqual(result['train']['fp'],1)
        self.assertIsNone(result['person']['precision'])

    def test_video_location_and_hash_cannot_leak_between_splits(self):
        with tempfile.TemporaryDirectory() as root:
            f = Path(root)/'a'; f.write_bytes(b'image')
            a = dict(id='a',path=str(f),sha256=hashlib.sha256(f.read_bytes()).hexdigest(),
                     split='train',video_group='video-a',location_group='place-a')
            b = dict(a,id='b',split='test')
            for key in ['video_group','location_group','sha256']:
                aa, bb = dict(a),dict(b)
                for other in ['video_group','location_group']:
                    if other != key:bb[other] += '-different'
                with self.assertRaises(ValueError):
                    validate_dataset(dict(images=[aa,bb],classes=['pole']))
            with self.assertRaises(ValueError):
                validate_dataset(dict(images=[a],classes=['fence']),require_training=True)

    def test_readiness_never_promotes_partial_or_published_labels(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'frame.png';path.write_bytes(b'raw')
            image=dict(id='a',path=str(path),sha256=hashlib.sha256(b'raw').hexdigest(),
                       split='test',video_group='one-video',location_group='one-place',
                       annotations=[],reviewed_classes=['pole'],review_status='published_annotations')
            result=dataset_readiness(dict(classes=['pole'],images=[image]))
            self.assertFalse(result['ready_for_supervised_training'])
            self.assertEqual(result['complete_human_verified_images'],0)
            self.assertTrue(any('Independent' in b for b in result['blockers']))
            self.assertTrue(any('video_group' in b for b in result['blockers']))

    def test_independent_assistant_review_is_not_mislabeled_human(self):
        image={'review_status':'assistant_reviewed', 'review_passes':[
            {'reviewer':'agent-one','method':'visual'}, {'reviewer':'agent-two','method':'visual'}]}
        self.assertTrue(reviewed_for_training(image))
        self.assertEqual(image['review_status'],'assistant_reviewed')
        image['review_passes'][1]['reviewer']='agent-one'
        self.assertFalse(reviewed_for_training(image))
        image['review_status']='assistant_draft'
        self.assertFalse(reviewed_for_training(image))

    def test_published_evaluation_preserves_missing_classes_and_temporal_unknown(self):
        data=dict(classes=['pole','chair'],images=[dict(id='still',review_status='published_annotations',
            reviewed_classes=['pole'],annotations=[box('pole')])])
        result=evaluate(data,{'still':[box('pole')]})
        self.assertEqual(result['per_class']['pole']['tp'],1)
        self.assertIsNone(result['per_class']['chair']['recall'])
        self.assertEqual(result['sampled_first_detection'],[])

    def test_dataset_rejects_image_tampering_and_duplicate_vocabulary(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'frame.png';path.write_bytes(b'changed')
            image=dict(id='a',path=str(path),sha256=hashlib.sha256(b'original').hexdigest(),
                       split='test',video_group='v',location_group='place',annotations=[])
            with self.assertRaisesRegex(ValueError,'digest'):
                validate_dataset(dict(classes=['pole'],images=[image]))
            with self.assertRaisesRegex(ValueError,'unique'):
                validate_dataset(dict(classes=['pole','pole'],images=[]))

    def test_evidence_preserves_exact_raw_input_and_context(self):
        with tempfile.TemporaryDirectory() as root:
            image=np.arange(30*40*3,dtype=np.uint8).reshape(30,40,3)
            jpeg=cv2.imencode('.jpg',image)[1].tobytes()
            f=SimpleNamespace(session_id='s',revision=1,frame_id=4,received_at=10.,jpeg=jpeg,orientation=6)
            buffer=EvidenceBuffer(root)
            roi=[.25,0,.5,1]
            buffer.add(f,dict(frame_id=4,analysis_status='ok',boxes=[box()],image_b64='ignored'),roi,{'name':'test'})
            buffer.acknowledge('s',2,4)
            self.assertFalse(buffer.frames[0]['display_ack'])
            buffer.acknowledge('s',1,4)
            target=buffer.select('s',1,4)
            result=buffer.write(buffer.clip(target),target,'wrong_label','test','v')
            folder=Path(result['path']);m=json.loads((folder/'manifest.json').read_text())
            row=m['frames'][0]
            self.assertTrue(row['display_ack'])
            self.assertEqual((folder/row['source_file']).read_bytes(),jpeg)
            from app.live import crop_image
            original=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
            np.testing.assert_array_equal(cv2.imread(str(folder/row['input_file'])),crop_image(original,roi))
            self.assertEqual(m['annotation_status'],'unreviewed')
            with self.assertRaises(ValueError):buffer.select('different-session',1,4)


if __name__ == '__main__': unittest.main()
