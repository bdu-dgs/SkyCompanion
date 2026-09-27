"""Guard cross-video identity and geometry; repeated local frame IDs must not collide."""
import json,tempfile,unittest
from pathlib import Path
from assemble_reviewed_dataset import load_reviewed_source,export_rows


class CollectionTests(unittest.TestCase):
    def make_source(self,root,vid,width,height):
        p=root/vid;p.mkdir();image=p/'frame_000000.png';image.write_bytes(b'fixture')
        row=dict(frame_id=0,path=str(image),width=width,height=height,timestamp_s=0,sha256='fixture')
        (p/'frames.jsonl').write_text(json.dumps(row)+'\n');(p/'source.json').write_text('{"sha256":"fixture"}')
        review=p/'review.jsonl';review.write_text(json.dumps(dict(frame_id=0,status='assistant_reviewed',review_evidence={'fixture':'synthetic export unit test'},boxes=[dict(label='person',xyxy=[0,0,width,height],status='assistant_reviewed')],unknown_regions=[],complete_classes_outside_unknown=[],explicit_negative_regions=[]))+'\n')
        return p,review

    def test_same_frame_number_stays_distinct_and_native_dimensions_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rows=[];sources=[]
            for vid,w,h in [('video01',960,544),('video02',1270,720)]:
                p,review=self.make_source(root,vid,w,h)
                part,provenance=load_reviewed_source(p,[review],vid,1);rows+=part;sources.append(provenance)
            out=export_rows(rows,root/'joint',sources)
            exported=[json.loads(s) for s in (out/'annotations.jsonl').read_text().splitlines()]
            self.assertEqual(len({r['path'] for r in exported}),2)
            self.assertEqual([r['frame_id'] for r in exported],[0,0])
            metadata=json.loads((out/'training_review.json').read_text())
            self.assertEqual(metadata['video01_frame_000000']['source_hw'],[544,960])
            self.assertEqual(metadata['video02_frame_000000']['source_hw'],[720,1270])
            for r in exported:
                self.assertEqual(Path(r['path']).resolve(),Path(r['source_path']).resolve())
                label=out/'labels/train'/(r['sample_id']+'.txt')
                self.assertEqual(list(map(float,label.read_text().split()[1:])),[.5,.5,1,1])
            with self.assertRaises(ValueError):export_rows(rows,out,sources)
            with self.assertRaises(ValueError):export_rows([rows[0],rows[0]],root/'duplicate',sources)
            self.assertFalse((root/'duplicate').exists())

    def test_incomplete_and_duplicate_frame_reviews_block_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,review=self.make_source(Path(tmp),'video01',960,544)
            original=review.read_text();review.write_text('')
            with self.assertRaises(ValueError):load_reviewed_source(p,[review],'video01',1)
            review.write_text(original*2)
            with self.assertRaises(ValueError):load_reviewed_source(p,[review],'video01',1)
            review.write_text(original)
            with self.assertRaises(ValueError):load_reviewed_source(p,[review],'video01',2)

    def test_draft_or_missing_evidence_cannot_be_promoted_by_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,review=self.make_source(Path(tmp),'video01',960,544)
            original=json.loads(review.read_text())
            for kind in ['frame','box','evidence']:
                row=json.loads(json.dumps(original))
                if kind=='frame':row['status']='pending_overlay_review'
                elif kind=='box':row['boxes'][0]['status']='pending_overlay_review'
                else:row.pop('review_evidence')
                review.write_text(json.dumps(row)+'\n')
                with self.assertRaises(ValueError):load_reviewed_source(p,[review],'video01',1)


if __name__=='__main__':unittest.main()
