import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from prepare_pole_rebalance import rebalance

class PoleRebalanceTests(unittest.TestCase):
    def test_quarantine_determinism_and_untouched_holdouts(self):
        def im(i,split='train',positive=False):
            return dict(id=i,split=split,annotations=[{'label':'pole'}] if positive else [])
        data={'classes':['pole'],'images':[im('p',positive=True),im('dup',positive=True),im('empty-pole'),
              *[im('negative_'+str(i)) for i in range(10)],im('v','val',True),im('t','test',True)]}
        before=copy.deepcopy(data)
        pairs=[dict(left='dup',left_split='train',right='v',right_split='val')]
        result=rebalance(data,pairs)
        self.assertEqual(result,rebalance(data,pairs))
        self.assertEqual(data,before)
        self.assertEqual([i for i in result['images'] if i['split']!='train'],before['images'][-2:])
        self.assertEqual(len([i for i in result['images'] if i['split']=='train']),2)
        self.assertNotIn('dup',[i['id'] for i in result['images']])
        self.assertNotIn('empty-pole',[i['id'] for i in result['images']])

    def test_no_positive_pool_fails_instead_of_training_background(self):
        with self.assertRaises(ValueError):rebalance({'images':[{'id':'negative_1','split':'train','annotations':[]}]},[])
