import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.scene_description import SceneDescription

def box(label,x=.45,y=.3,w=.15,h=.5,confidence=.8):
    return dict(label=label,x=x,y=y,w=w,h=h,confidence=confidence)

class SceneTests(unittest.TestCase):
    def test_visible_people_and_lights_do_not_require_path_risk(self):
        scene=SceneDescription()
        boxes=[box('person'),box('traffic light',.8,.1,.05,.1)]
        for t in (10,10.2,10.4): scene.update(boxes,t)
        answer=scene.describe(10.5)
        self.assertEqual(answer['code'],'scene_summary')
        self.assertEqual({o['kind'] for o in answer['objects']},{'person','traffic_light'})
        self.assertEqual(next(o for o in answer['objects'] if o['kind']=='traffic_light')['direction'],'right')
    def test_unstable_train_or_absent_boxes_never_become_descriptions(self):
        scene=SceneDescription()
        for t in (10,10.2,10.4): scene.update([box('train'),box('person',confidence=.2)],t)
        self.assertEqual(scene.describe(10.5)['code'],'no_stable_objects')
        self.assertEqual(scene.describe(12)['code'],'vision_unavailable')
    def test_category_diversity_and_uncertain_structures(self):
        scene=SceneDescription()
        boxes=[box('person',x=x) for x in (.05,.45,.8)]+[box('traffic light',.8,.1,.05,.1),box('pole',.5,.1,.08,.88)]
        for t in (10,10.2,10.4): scene.update(boxes,t)
        kinds={o['kind'] for o in scene.describe(10.5)['objects']}
        self.assertEqual(kinds,{'person','traffic_light','obstacle'})
    def test_context_reset_erases_scene(self):
        scene=SceneDescription()
        for t in (10,10.2,10.4): scene.update([box('person')],t)
        scene.reset()
        self.assertEqual(scene.describe(10.5)['code'],'vision_unavailable')

if __name__=='__main__':unittest.main()
