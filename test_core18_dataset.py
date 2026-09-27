"""Protect semantic merges and historic labels during scope reduction."""
import json
import tempfile
import unittest
from pathlib import Path
from assemble_reviewed_dataset import export_rows
from simplify_street_dataset import SCHEMA, reduce_row, delete_exact
from video_training import dataset_names


class Core18Tests(unittest.TestCase):
    def setUp(self):
        self.schema=json.loads(SCHEMA.read_text())

    def row(self):
        return dict(sample_id='video01_frame_000000',video_id='video01',frame_id=0,width=100,height=100,
            source_path='',boxes=[],unknown_regions=[],explicit_negative_regions=[],
            complete_classes_outside_unknown=[],all_instances_verified=False)

    def box(self,label,xyxy=None):
        return dict(label=label,xyxy=xyxy or [10,10,20,90],status='assistant_reviewed')

    def test_tree_crown_is_never_relabelled_as_trunk(self):
        row=self.row();row['boxes']=[self.box('tree'),self.box('tree_trunk')]
        out,excluded=reduce_row(row,self.schema)
        self.assertEqual([b['label'] for b in out['boxes']],['tree_trunk'])
        self.assertEqual(excluded[0]['label'],'tree')
        self.assertEqual(out['unknown_regions'][0]['original_label'],'tree')
        self.assertEqual(row['unknown_regions'],[])

    def test_partial_subclass_negative_does_not_become_merged_negative(self):
        row=self.row();row['complete_classes_outside_unknown']=['car']
        row['explicit_negative_regions']=[dict(xyxy=[0,0,100,100],classes=['car'],reason='Only cars checked')]
        out,_=reduce_row(row,self.schema)
        self.assertEqual(out['complete_classes_outside_unknown'],[])
        self.assertEqual(out['explicit_negative_regions'],[])
        row['complete_classes_outside_unknown']=['car','bus','truck']
        row['explicit_negative_regions'][0]['classes']=['car','bus','truck']
        out,_=reduce_row(row,self.schema)
        self.assertEqual(out['complete_classes_outside_unknown'],['vehicle'])
        self.assertEqual(out['explicit_negative_regions'][0]['classes'],['vehicle'])

    def test_merging_does_not_suppress_different_overlapping_poles(self):
        row=self.row();row['boxes']=[self.box('pole'),self.box('signpost'),self.box('streetlight',[11,10,21,90])]
        out,_=reduce_row(row,self.schema)
        self.assertEqual(len(out['boxes']),2)
        self.assertEqual({b['class_id'] for b in out['boxes']},{5})

    def test_replacement_must_match_old_geometry_once(self):
        row=self.row();row['boxes']=[self.box('person')]
        with self.assertRaises(ValueError):delete_exact(row,self.box('person',[1,1,9,9]))
        self.assertEqual(len(row['boxes']),1)
        delete_exact(row,self.box('person'));self.assertEqual(row['boxes'],[])

    def test_export_uses_new_ids_and_rejects_mismatched_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'frame.png';image.write_bytes(b'export fixture')
            row=self.row();row['source_path']=str(image);row['boxes']=[self.box('car')]
            row,_=reduce_row(row,self.schema)
            out=export_rows([row],root/'export',[],SCHEMA)
            self.assertEqual(len(dataset_names(out)),18)
            self.assertEqual((out/'labels/train/video01_frame_000000.txt').read_text().split()[0],'1')
            yaml=out/'data.yaml';yaml.write_text(yaml.read_text().replace('1: vehicle','1: car'))
            with self.assertRaises(ValueError):dataset_names(out)

    def test_unreviewed_box_rejected(self):
        row=self.row();row['boxes']=[dict(self.box('person'),status='pending')]
        with self.assertRaises(ValueError):reduce_row(row,self.schema)


if __name__=='__main__':unittest.main()
