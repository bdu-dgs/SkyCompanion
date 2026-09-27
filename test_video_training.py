"""Behavior checks for label geometry and cross-model consolidation."""
import unittest
from video_training import NAMES, iou, consolidate, to_label_line
from assemble_reviewed_dataset import validate_region


class LabelTests(unittest.TestCase):
    def test_full_image_and_edge_box_round_trip(self):
        for box in ([0,0,960,544],[958,540,960,544],[10.5,20.5,40.25,50.75]):
            c,cx,cy,w,h=map(float,to_label_line({'label':'person','xyxy':box},960,544).split())
            recovered=[(cx-w/2)*960,(cy-h/2)*544,(cx+w/2)*960,(cy+h/2)*544]
            self.assertEqual(int(c),NAMES.index('person'))
            for a,b in zip(box,recovered): self.assertAlmostEqual(a,b,places=3)

    def test_invalid_geometry_rejected(self):
        for box in ([-1,0,10,10],[0,0,961,544],[10,10,5,15],[0,0,1,0]):
            with self.assertRaises(ValueError):to_label_line({'label':'person','xyxy':box},960,544)

    def test_same_pole_not_duplicated_by_two_teachers(self):
        rows=[dict(label='pole',confidence=.6,xyxy=[1,1,10,100]),
              dict(label='streetlight',confidence=.7,xyxy=[1,1,10,100])]
        self.assertEqual([b['label'] for b in consolidate(rows)],['streetlight'])

    def test_trunk_and_tree_remain_distinct(self):
        rows=[dict(label=n,confidence=.8,xyxy=[0,0,100,200]) for n in ('tree','tree_trunk')]
        self.assertEqual(len(consolidate(rows)),2)

    def test_adjacent_instances_are_preserved(self):
        rows=[dict(label='person',confidence=.9,xyxy=b) for b in ([0,0,10,20],[9,0,20,20])]
        self.assertEqual(len(consolidate(rows)),2)
        self.assertEqual(iou([0,0,1,1],[2,2,3,3]),0)

    def test_repository_original_ids_preserved(self):
        self.assertEqual(NAMES[:8],['bicycle','streetlight','railing','bus_stop_shelter','tree',
            'traffic_light_red','traffic_light_green','utility_pole'])

    def test_review_regions_reject_invalid_negative_supervision(self):
        valid=dict(xyxy=[0,0,100,200],reason='Closed window',classes=['open_door'])
        validate_region(valid,960,544,64,negative=True)
        for changes in ({'xyxy':[0,0,float('nan'),200]}, {'xyxy':[0,0,100,545]},
                        {'classes':['window_unknown']}, {'classes':[]}, {'reason':''}):
            with self.assertRaises(ValueError):
                validate_region(dict(valid,**changes),960,544,64,negative=True)


if __name__=='__main__':unittest.main()
