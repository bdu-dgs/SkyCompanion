#!/usr/bin/env python3
"""Fail-closed checks for measurement acceptance; synthetic rows are NOT accuracy data."""
import unittest
from evaluate_mobile_depth import evaluate
class EvaluationTests(unittest.TestCase):
 def rows(self):
  return [dict(split=split,clip_id=f'{split}-{i//10}',camera_id='c',model_id='m',preprocessing_id='p',reference='camera_optical_axis',predicted_m='3.1',measured_m='3') for split in ('calibration','test') for i in range(30)]
 def test_missing_data(self):self.assertEqual(evaluate([])['state'],'insufficient_data')
 def test_same_clip_rejected(self):
  r=self.rows();r[-1]['clip_id']='calibration-0';self.assertEqual(evaluate(r)['state'],'insufficient_data')
 def test_mixed_camera_rejected(self):
  r=self.rows();r[-1]['camera_id']='other';self.assertEqual(evaluate(r)['state'],'insufficient_data')
 def test_nonfinite_rejected(self):
  r=self.rows();r[-1]['measured_m']='nan';self.assertEqual(evaluate(r)['state'],'insufficient_data')
 def test_heldout_error_does_not_pass(self):
  r=self.rows()
  for v in r:
   if v['split']=='test':v['predicted_m']='15'
  report=evaluate(r);self.assertFalse(report['engineeringScreenPassed']);self.assertFalse(report['appGuidanceEnabled'])
 def test_synthetic_pass_never_unlocks_app(self):
  report=evaluate(self.rows());self.assertTrue(report['engineeringScreenPassed']);self.assertFalse(report['appGuidanceEnabled'])
if __name__=='__main__':unittest.main()
