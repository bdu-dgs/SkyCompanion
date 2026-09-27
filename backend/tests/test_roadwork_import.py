import io
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('roadwork', Path(__file__).resolve().parents[2]/'scripts/import_roadwork_public.py')
roadwork = importlib.util.module_from_spec(spec); spec.loader.exec_module(roadwork)


class RoadworkImportTests(unittest.TestCase):
    def test_truncated_range_retries_without_advancing_offset(self):
        class Response:
            status=206
            headers={'Content-Range':'bytes 0-9/10'}
            def __init__(self, data): self.data=data
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,n): return self.data
        with patch.object(roadwork.urllib.request,'urlopen',side_effect=[Response(b'12'),Response(b'1234567890')]) as request, patch.object(roadwork.time,'sleep'):
            reader=roadwork.RangeReader('https://example.invalid/a.zip',10)
            self.assertEqual(reader.read(10),b'1234567890')
            self.assertEqual(reader.tell(),10)
            self.assertEqual(request.call_count,2)

    def test_http_range_never_accepts_unbounded_full_body(self):
        class Response:
            status=200
            headers={}
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,n): raise AssertionError('Must reject before reading full body')
        with patch.object(roadwork.urllib.request,'urlopen',return_value=Response()):
            with self.assertRaises(ValueError): roadwork.RangeReader('https://example.invalid/a.zip',100).read(20)
        with self.assertRaises(ValueError): roadwork.RangeReader('https://example.invalid/a.zip',100000000).read()

    def test_categories_remain_distinct_and_source_mask_survives(self):
        image = dict(width=100, height=50)
        a = dict(id=2, category_id=7, bbox=[90, 5, 20, 10], segmentation=[[90,5,99,5,99,15]])
        got = roadwork.normalized_annotation(a, image)
        self.assertEqual(got['label'], 'construction_barrier')
        self.assertAlmostEqual(got['w'], .1)
        self.assertEqual(got['source_segmentation'], a['segmentation'])
        self.assertNotEqual(roadwork.CLASS_MAP[6], roadwork.CLASS_MAP[7])
        self.assertNotIn(9, roadwork.CLASS_MAP)
        with self.assertRaises(ValueError):
            roadwork.normalized_annotation(dict(a, iscrowd=1), image)

    def test_whole_videos_not_frame_sequences_form_groups(self):
        a = dict(file_name='x.jpg', city_name='boston', video_info={'vid_id':'abc','seq_id':'1'})
        b = dict(a, video_info={'vid_id':'abc','seq_id':'2'})
        self.assertEqual(roadwork.geographic_group(a,'val'), roadwork.geographic_group(b,'val'))
        self.assertEqual(roadwork.geographic_group({'file_name':'IMG_1.JPG'},'train'), (None,None))

    def test_exact_zip_member_crc_and_size_validation(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('images/example.jpg', b'image bytes'*100)
        with zipfile.ZipFile(buf) as z: info=z.getinfo('images/example.jpg')
        self.assertEqual(roadwork.decode_member(info,buf.getvalue()), b'image bytes'*100)
        info.CRC ^= 1
        with self.assertRaises(ValueError): roadwork.decode_member(info,buf.getvalue())

    def test_city_holdout_and_sampling_determinism(self):
        cats=[{'id':i,'name':n} for i,n in roadwork.EXPECTED_SOURCE.items()]
        def data(cities):
            images=[dict(id=i,file_name=f'{city}_{i}.jpg',city_name=city,video_info={'vid_id':str(i)}) for i,city in enumerate(cities)]
            return dict(categories=cats,images=images,annotations=[dict(image_id=i,category_id=7) for i in range(len(images))])
        train,val=data(['pittsburgh']*3),data(['boston','detroit','denver','houston']*3)
        first,meta=roadwork.select_subset(train,val,(2,2,2))
        self.assertEqual((first,meta),roadwork.select_subset(train,val,(2,2,2)))
        self.assertFalse(set(meta['val_cities']) & set(meta['test_cities']))
        used={}
        for row in first:
            self.assertEqual(used.setdefault(row['city'],row['split']),row['split'])
