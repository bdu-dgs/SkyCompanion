import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location('public_ade', Path(__file__).resolve().parents[2]/'scripts/import_ade_public.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def test_source_ids_and_visible_boxes_keep_tree_out():
    mask = np.ones((20,30), dtype='uint8')
    mask[:,2:4] = 94
    mask[5:12,10:15] = 43
    mask[15:18,20:29] = 35
    mask[0:4,18:30] = 5  # Whole tree must never become tree_trunk.
    boxes = m.regions(mask)
    assert {b['label'] for b in boxes} == {'pole','column','rock'}
    pole = next(b for b in boxes if b['label']=='pole')
    assert pole['h'] == 1 and pole['truncated']
    assert abs(pole['w']-2/30)<1e-10
    assert pole['distance_m'] is None


def test_all_components_retained_no_tiny_background_flip():
    mask=np.ones((10,10),dtype='uint8');mask[1,1]=33;mask[8,8]=33
    boxes=m.regions(mask)
    assert len(boxes)==2 and all(b['mask_area_px']==1 for b in boxes)


def test_duplicate_group_does_not_cross_publisher_holdout():
    rows=[{'id':'a','sha256':'same','phash':'0000000000000000','source_split':'training'},
          {'id':'b','sha256':'same','phash':'0000000000000000','source_split':'validation'},
          {'id':'c','sha256':'other','phash':'ffffffffffffffff','source_split':'training'}]
    groups,pairs=m.duplicate_groups(rows)
    excluded=m.assign_splits(rows,groups)
    assert excluded==['a'] and rows[1]['split']=='test'
    assert rows[0]['duplicate_group']==rows[1]['duplicate_group']
    assert rows[2]['split'] in {'train','val'}


def test_selection_reproducible_and_bounded_without_predictions():
    rows=[{'id':str(i),'split':'train','present_classes':['pole'] if i<20 else []} for i in range(40)]
    a=m.select(rows,{'train':5});b=m.select(list(reversed(rows)),{'train':5})
    assert {r['id'] for r in a}=={r['id'] for r in b}
    assert sum(bool(r['present_classes']) for r in a)==5


def test_source_pair_rejects_shifted_geometry_and_unknown_ids():
    import cv2
    mask = np.ones((10, 20), dtype='uint8')
    ok, raw = cv2.imencode('.jpg', np.zeros((10, 20, 3), dtype='uint8'))
    assert ok
    m.validate_source_pair(mask, raw.tobytes())
    for invalid, image in [(mask[:5], raw.tobytes()), (np.full((10, 20), 151), None),
                           (np.zeros((10, 20, 3), dtype='uint8'), None), (None, None)]:
        try:
            m.validate_source_pair(invalid, image)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid geometry or semantic IDs accepted')


def test_unknown_source_content_removed_without_changing_known_pixels():
    import cv2
    source = np.full((12, 16, 3), (7, 20, 200), dtype='uint8')
    mask = np.ones((12, 16), dtype='uint8'); mask[:, :4] = 0
    _, raw = cv2.imencode('.png', source)
    transformed = cv2.imdecode(np.frombuffer(m.rendered_known_pixels(raw.tobytes(), mask), np.uint8), 1)
    assert np.all(transformed[:, :4] == 114)
    assert np.array_equal(transformed[:, 4:], source[:, 4:])
    assert np.all(source[:, 0] == (7, 20, 200))


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(fn) for name,fn in globals().items()
                              if name.startswith('test_') and callable(fn))
