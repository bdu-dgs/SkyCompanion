import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from evaluate_original_region_transfer import original_subset
from evaluate_public_candidate import score_split


class OriginalRegionTransferTests(unittest.TestCase):
    def test_original_unknown_content_never_becomes_false_positive_ground_truth(self):
        with tempfile.TemporaryDirectory() as folder:
            original=Path(folder)/'original.jpg';original.write_bytes(b'unchanged-source')
            box=dict(label='pole',x=.1,y=.1,w=.1,h=.7)
            image=dict(id='image',split='test',path='rendered.png',original_path=str(original),
                       source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
                       annotations=[box],review_status='published_annotations',
                       reviewed_classes=['pole'],annotation_coverage={'pole':'complete'})
            data=dict(classes=['pole'],images=[image])
            subset=original_subset(data,'test')
            self.assertEqual(subset['images'][0]['path'],str(original))
            self.assertEqual(image['path'],'rendered.png')
            self.assertEqual(image['annotation_coverage'],{'pole':'complete'})
            predictions={'image':[dict(box,confidence=.9),dict(box,x=.8,confidence=.8)]}
            score=score_split(subset,predictions)['per_class']['pole']
            self.assertIsNone(score['precision'])
            self.assertEqual(score['fp'],0)
            self.assertEqual(score['partial_known_targets']['recall'],1.)
            self.assertEqual(score['unscored_predictions_unknown_coverage'],1)

    def test_modified_original_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            original=Path(folder)/'original.jpg';original.write_bytes(b'modified')
            data=dict(classes=['pole'],images=[dict(id='bad',split='test',original_path=str(original),source_sha256='wrong')])
            with self.assertRaisesRegex(ValueError,'differs from saved source hash'):
                original_subset(data,'test')

if __name__=='__main__':unittest.main()
