"""Export visually reviewed positives; raw predictions never become training truth."""
import argparse,json,math,re
from collections import Counter
from pathlib import Path
import yaml
from video_training import ROOT,NAMES,digest,save,to_label_line


def validate_region(region,width,height,frame_id,negative=False):
    xy=region.get('xyxy',[])
    if (len(xy)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in xy)
            or not 0<=xy[0]<xy[2]<=width or not 0<=xy[1]<xy[3]<=height):
        raise ValueError(('Invalid review region',frame_id,region))
    if not region.get('reason'):raise ValueError(('Review region needs a reason',frame_id,region))
    if negative and (not region.get('classes') or any(c not in NAMES for c in region['classes'])):
        raise ValueError(('Invalid negative classes',frame_id,region))


def load_reviewed_source(source,review_paths,video_id=None,expected_frames=None):
    source=Path(source);frames=[json.loads(s) for s in (source/'frames.jsonl').read_text().splitlines()]
    if expected_frames is not None and len(frames)!=expected_frames:
        raise ValueError(('Unexpected source frame count',source,len(frames),expected_frames))
    if [r['frame_id'] for r in frames]!=list(range(len(frames))):
        raise ValueError('Source frame manifest must contain every frame exactly once in order')
    if video_id is not None and not re.fullmatch(r'[A-Za-z0-9_-]+',video_id):
        raise ValueError('Invalid video identifier')
    by_frame={};inputs=[]
    for path in map(Path,review_paths):
        inputs.append(dict(path=str(path.resolve()),sha256=digest(path)))
        for line in path.read_text().splitlines():
            row=json.loads(line);fid=row['frame_id']
            if fid in by_frame:raise ValueError(f'Duplicate reviewed frame {video_id}:{fid}')
            if row.get('status') not in {'assistant_reviewed','assistant_reviewed_partial_instances','assistant_reviewed_selected_instances'}:
                raise ValueError(f'Unreviewed or draft frame cannot be exported: {video_id}:{fid}')
            if not (row.get('review_evidence') or row.get('visual_evidence') or row.get('evidence')):
                raise ValueError(f'Missing visual review evidence: {video_id}:{fid}')
            if 'complete_classes_outside_unknown' not in row or 'unknown_regions' not in row:
                raise ValueError(f'Explicit class/region review coverage required: {fid}')
            by_frame[fid]=row
    if set(by_frame)!=set(range(len(frames))):raise ValueError('Every video frame needs its own review record')
    rows=[]
    for original in frames:
        r=dict(original);review=by_frame[r['frame_id']];boxes=review['boxes']
        complete=review['complete_classes_outside_unknown'];unknown=review['unknown_regions']
        negatives=review.get('explicit_negative_regions',[])
        if any(c not in NAMES for c in complete):raise ValueError(('Unknown class coverage',r['frame_id']))
        for b in boxes:
            if b.get('status')!='assistant_reviewed':
                raise ValueError(('Unreviewed box cannot be exported',r['frame_id'],b))
            if b['label'] not in NAMES or len(b['xyxy'])!=4 or not all(math.isfinite(x) for x in b['xyxy']):
                raise ValueError(('Invalid annotation',r['frame_id'],b))
            to_label_line(b,r['width'],r['height'])
        for region in unknown:validate_region(region,r['width'],r['height'],r['frame_id'])
        for region in negatives:validate_region(region,r['width'],r['height'],r['frame_id'],negative=True)
        if not Path(r['path']).is_file():raise ValueError(('Missing original frame',r['path']))
        stem=Path(r['path']).stem
        r.update(sample_id=f'{video_id}_{stem}' if video_id else stem,video_id=video_id,
            source_path=r['path'],boxes=boxes,annotation_status='assistant_reviewed_partial',human_reviewed=False,
            all_instances_verified=review.get('all_instances_verified',False),unknown_regions=unknown,
            complete_classes_outside_unknown=complete,explicit_negative_regions=negatives,
            review_evidence=review.get('review_evidence',review.get('visual_evidence',review.get('evidence'))),
            review_notes=review.get('notes',review.get('review_scope')))
        rows.append(r)
    provenance=dict(video_id=video_id,data_path=str(source.resolve()),frame_count=len(rows),
        video_sha256=json.loads((source/'source.json').read_text())['sha256'],
        source_frame_manifest_sha256=digest(source/'frames.jsonl'),review_inputs=inputs)
    return rows,provenance


def export_rows(rows,out,sources,schema_path=None):
    out=Path(out).resolve()
    if out.exists():raise ValueError('Use a new dataset version; refusing to replace a reviewed export')
    schema_path=Path(schema_path) if schema_path else ROOT/'street_classes.json'
    names=[c['name'] for c in json.loads(schema_path.read_text())['classes']]
    ids=[r['sample_id'] for r in rows]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate sample names across videos')
    counts=Counter();metadata={};no_positives=[]
    for r in rows:
        counts.update(b['label'] for b in r['boxes'])
        if not r['boxes']:no_positives.append(r['sample_id'])
        metadata[r['sample_id']]=dict(source_hw=[r['height'],r['width']],video_id=r['video_id'],frame_id=r['frame_id'],
            complete_classes_outside_unknown=r['complete_classes_outside_unknown'],
            unknown_regions=r['unknown_regions'],explicit_negative_regions=r['explicit_negative_regions'])
    (out/'images/train').mkdir(parents=True);(out/'labels/train').mkdir(parents=True)
    (out/'schema.json').write_bytes(schema_path.read_bytes())
    labels=[];exported=[]
    for row in rows:
        r=dict(row);image_path=out/'images/train'/(r['sample_id']+Path(r['source_path']).suffix)
        image_path.symlink_to(Path(r['source_path']).resolve());r['path']=str(image_path)
        label=out/'labels/train'/(r['sample_id']+'.txt')
        label.write_text('\n'.join(to_label_line(b,r['width'],r['height'],names) for b in r['boxes'])+'\n')
        labels.append(dict(path=str(label.relative_to(out)),sha256=digest(label)));exported.append(r)
    save(out/'labels_manifest.json',labels)
    (out/'annotations.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in exported))
    save(out/'training_review.json',metadata)
    # WorldTrainer requires an adapter loader for class text. This overlapping
    # subset is never used to claim validation accuracy or select a checkpoint.
    (out/'fit_diagnostic.txt').write_text('\n'.join(r['path'] for r in exported[::20])+'\n')
    (out/'data.yaml').write_text(yaml.safe_dump(dict(path=str(out),train='images/train',val='fit_diagnostic.txt',names=dict(enumerate(names))),sort_keys=False))
    (out/'classes.txt').write_text('\n'.join(names)+'\n')
    audit=dict(training_mode='assistant_reviewed_partial_labels_with_ignored_unknowns',frame_count=len(rows),
        label_count=len(rows),box_count=sum(counts.values()),all_frames_train=True,human_reviewed=False,
        independent_val_count=0,independent_test_count=0,all_instances_verified=all(r['all_instances_verified'] for r in rows),
        annotation_sha256=digest(out/'annotations.jsonl'),schema_file='schema.json',schema_sha256=digest(out/'schema.json'),
        training_review_sha256=digest(out/'training_review.json'),labels_manifest_sha256=digest(out/'labels_manifest.json'),
        data_yaml_sha256=digest(out/'data.yaml'),sources=sources,
        counts=dict(counts),zero_positive_classes=[n for n in names if not counts[n]],no_positive_frames=no_positives,
        note='Selected visually confirmed positives. Unresolved instances are not verified negatives. No independent validation. Repeated or overlapping clip content retained at user request.')
    save(out/'dataset_audit.json',audit)
    print(json.dumps(dict(output=str(out),frames=len(rows),boxes=sum(counts.values()),videos=len(sources))))
    return out


def assemble(source=None):
    source=Path(source or ROOT/'local_training/wechat-20260926')
    paths=[source/'reviews'/p/'reviewed_annotations.jsonl' for p in ('part1','part2','part3')]
    rows,provenance=load_reviewed_source(source,paths)
    return export_rows(rows,source/'reviewed_v1',[provenance])


def assemble_collection(manifest,output=None):
    manifest=Path(manifest);collection=json.loads(manifest.read_text());rows=[];sources=[];video_ids=set()
    for spec in [collection['original_video'],*collection['new_videos']]:
        vid=spec['video_id'];source=Path(spec['data_path'])
        if vid in video_ids:raise ValueError('Repeated video identifier')
        video_ids.add(vid)
        paths=([source/'reviews'/p/'reviewed_annotations.jsonl' for p in ('part1','part2','part3')]
               if spec is collection['original_video'] else [source/'reviews/assistant/reviewed_annotations.jsonl'])
        part,provenance=load_reviewed_source(source,paths,vid,spec['expected_frames']);rows+=part;sources.append(provenance)
    if len(rows)!=collection['expected_total_frames']:raise ValueError('Collection frame total mismatch')
    return export_rows(rows,output or manifest.parent/'reviewed_v1',sources)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--collection',type=Path);p.add_argument('--output',type=Path);p.add_argument('--source',type=Path)
    a=p.parse_args()
    if a.collection:assemble_collection(a.collection,a.output)
    else:assemble(a.source)
