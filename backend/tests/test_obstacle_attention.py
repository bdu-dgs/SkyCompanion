import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.obstacle_attention import prioritize_obstacles
from app.obstacle_risk import RiskMonitor


def candidate(label, x, y, w, h, confidence=.9):
    return dict(label=label, x=x, y=y, w=w, h=h, confidence=confidence)


class AttentionTests(unittest.TestCase):
    def test_thin_near_pole_and_low_wide_block_survive_small_area(self):
        boxes = [candidate("person", .5, .35, .03, .12),
                 candidate("pole", .7, 0., .025, .97, .26),
                 candidate("stone block", .4, .76, .2, .08)]
        ranked = prioritize_obstacles(boxes)
        self.assertEqual({b['label'] for b in ranked if b['attention']['near']}, {'pole', 'stone block'})
        self.assertEqual(ranked[-1]['label'], 'person')

    def test_near_priority_preserves_confidence_geometry_and_all_raw_candidates(self):
        boxes = [candidate("car", .2, .4, .04, .04, .99),
                 candidate("chair", .1, .65, .12, .3, .27)]
        before = copy.deepcopy(boxes)
        ranked = prioritize_obstacles(boxes)
        self.assertEqual(boxes, before)
        self.assertEqual(ranked[0]['label'], 'chair')
        self.assertEqual(sorted([{k:v for k,v in b.items() if k != 'attention'} for b in ranked], key=lambda b:b['label']),
                         sorted(before, key=lambda b:b['label']))
        self.assertTrue(all(b['attention']['basis'] == 'image_geometry_not_metric_distance' for b in ranked))

    def test_small_low_obstacle_retained_but_high_small_object_not_near(self):
        ranked = prioritize_obstacles([candidate("rock", .4, .91, .06, .05),
                                      candidate("traffic light", .6, .1, .04, .08)])
        self.assertTrue(ranked[0]['attention']['near'])
        self.assertFalse(ranked[1]['attention']['near'])
        self.assertEqual(prioritize_obstacles([]), [])

    def test_large_visible_body_with_occluded_or_missed_base_is_not_hidden(self):
        boxes = prioritize_obstacles([candidate('monument', .55, .04, .20, .53),
                                      candidate('person', .1, .37, .03, .12)])
        self.assertTrue(boxes[0]['attention']['near'])
        self.assertFalse(boxes[1]['attention']['near'])

    def test_near_filter_does_not_assert_safe_path_or_bypass_corridor(self):
        monitor = RiskMonitor()
        boxes = prioritize_obstacles([candidate('pole', .05, 0, .03, 1)])
        self.assertEqual(monitor.update(boxes, None, 0)['state'], 'unconfigured')
        corridor = [[.3,0],[.7,0],[.7,1],[.3,1]]
        self.assertEqual(monitor.update(boxes, corridor, 1)['state'], 'unconfirmed')


if __name__ == '__main__':
    unittest.main()
