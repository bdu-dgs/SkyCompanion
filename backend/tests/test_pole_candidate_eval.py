import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from evaluate_pole_candidate import choice, diagnose
from evaluate_pole_local_regression import score_targets

class PoleCandidateEvaluationTests(unittest.TestCase):
    def test_precision_constraint_can_reject_every_setting(self):
        grid=[dict(precision=.6,recall=.9,f1=.72,threshold=.1),
              dict(precision=.9,recall=.2,f1=.327,threshold=.7)]
        self.assertEqual(choice(grid)['threshold'],.1)
        self.assertEqual(choice(grid,.8)['threshold'],.7)
        self.assertIsNone(choice(grid,.95))

    def test_one_prediction_cannot_match_two_targets_or_wrong_class(self):
        target=dict(label='pole',x=.4,y=.1,w=.1,h=.8,target_id='a',subcategory='shaft')
        prediction=dict(target,confidence=.8)
        rows=score_targets([target,dict(target,target_id='b')],[prediction])
        self.assertEqual(sum(r['hit_iou_50'] for r in rows),1)
        rows=score_targets([dict(target,label='column')],[prediction])
        self.assertFalse(rows[0]['hit_iou_50'])

    def test_full_image_box_is_not_a_pole_hit(self):
        target=dict(label='pole',x=.4,y=.1,w=.02,h=.8,target_id='a',subcategory='shaft')
        rows=score_targets([target],[dict(label='pole',x=0,y=0,w=1,h=1,confidence=.99)])
        self.assertFalse(rows[0]['hit_iou_50'])

    def test_miss_diagnostic_distinguishes_threshold_from_missing_prediction(self):
        target=dict(label='pole',x=.4,y=.1,w=.02,h=.8)
        im=dict(id='a',path='unused',annotations=[target])
        result=diagnose([im],{'a':[dict(target,confidence=.1)]},.5)
        self.assertEqual(result['counts'],{'below_selected_confidence':1})
        result=diagnose([im],{'a':[]},.5)
        self.assertEqual(result['counts'],{'no_matching_returned_box_at_or_above_0.01':1})
