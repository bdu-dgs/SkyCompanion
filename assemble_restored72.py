"""Keep all 72 classes and integrate only frozen, actually reviewed material."""
import argparse
import json
from collections import Counter
from pathlib import Path
import yaml

from assemble_reviewed_dataset import export_rows, validate_region
from simplify_street_dataset import BASE, COVERAGE, load_integrated_rows, read_rows
from video_training import ROOT, NAMES, dataset_names, digest, save, to_label_line


def validate(row):
    if not (row.get('review_evidence') or row.get('visual_evidence') or row.get('evidence')):
        raise ValueError(('Missing review evidence',row['sample_id']))
    for box in row['boxes']:
        if box.get('status')!='assistant_reviewed':
            raise ValueError(('Unreviewed box',row['sample_id']))
        to_label_line(box,row['width'],row['height'])
    if set(row['complete_classes_outside_unknown'])-set(NAMES):
        raise ValueError('Invalid coverage class')
    for region in row['unknown_regions']:
        validate_region(region,row['width'],row['height'],row['sample_id'])
    for region in row['explicit_negative_regions']:
        validate_region(region,row['width'],row['height'],row['sample_id'],negative=True)


def build(output,public_dir):
    if output.exists():raise ValueError('Refusing to overwrite an exported version')
    videos,baseline_audit,inputs,integration=load_integrated_rows()
    for row in videos:validate(row)
    public=read_rows(public_dir/'annotations.jsonl')
    seen=set(r['sample_id'] for r in videos)
    groups={};image_splits={}
    for index,row in enumerate(public):
        if row['sample_id'] in seen:raise ValueError('Duplicate sample ID')
        seen.add(row['sample_id'])
        if row['split'] not in {'train','val','test'}:raise ValueError('Unassigned public source')
        group=row['source_group']
        groups.setdefault(group,set()).add(row['split'])
        image_splits.setdefault(row['sha256'],set()).add(row['split'])
        row['source_path']=str(Path(row.get('source_path') or row['path']).resolve())
        if digest(row['source_path'])!=row['sha256']:raise ValueError('Public image changed')
        row.update(frame_id=index,timestamp_s=0.0,video_id='public_'+row['split'],
                   annotation_status='assistant_reviewed_partial',human_reviewed=False,all_instances_verified=False)
        validate(row)
    if any(len(v)>1 for v in [*groups.values(),*image_splits.values()]):
        raise ValueError('Group or identical-image leakage across public splits')
    historical_hashes={r['sha256'] for r in videos}
    if any(r['split']!='train' and r['sha256'] in historical_hashes for r in public):
        raise ValueError('Historical video frame in holdout')
    sources=[*baseline_audit['sources'],dict(source='visually_reviewed_public_supplements',
        manifest=str(public_dir/'annotations.jsonl'),sha256=digest(public_dir/'annotations.jsonl'))]
    training=[*videos,*(r for r in public if r['split']=='train')]
    export_rows(training,output,sources,ROOT/'street_classes.json')
    heldout_counts={}
    for split in ('val','test'):
        selected=[r for r in public if r['split']==split]
        (output/f'images/{split}').mkdir(parents=True)
        (output/f'labels/{split}').mkdir(parents=True)
        for row in selected:
            image=output/f'images/{split}'/(row['sample_id']+Path(row['source_path']).suffix)
            image.symlink_to(row['source_path']);row['path']=str(image)
            label=output/f'labels/{split}'/(row['sample_id']+'.txt')
            label.write_text('\n'.join(to_label_line(b,row['width'],row['height']) for b in row['boxes'])+'\n')
        (output/f'{split}_annotations.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in selected))
        (output/f'{split}.txt').write_text(''.join(r['path']+'\n' for r in selected))
        heldout_counts[split]=dict(images=len(selected),boxes=sum(len(r['boxes']) for r in selected),
            per_class=dict(Counter(b['label'] for r in selected for b in r['boxes'])))
    # These held-out photos are partial-label evaluation candidates. The current
    # baseline trainer uses fixed final epoch and performs no test-based tuning.
    config=yaml.safe_load((output/'data.yaml').read_text())
    config.update(val='val.txt',test='test.txt')
    (output/'data.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
    split_records=[dict(sample_id=r['sample_id'],split='train',source_group=r.get('video_group',r['video_id']),
        sha256=r['sha256']) for r in videos]
    split_records += [dict(sample_id=r['sample_id'],split=r['split'],source_group=r['source_group'],sha256=r['sha256']) for r in public]
    save(output/'split_manifest.json',split_records)
    split_audit=json.loads((public_dir/'audit.json').read_text())
    save(output/'public_group_audit.json',split_audit)
    inputs += [dict(path=str(public_dir/p),sha256=digest(public_dir/p)) for p in ('annotations.jsonl','split_manifest.json','audit.json')]
    audit=json.loads((output/'dataset_audit.json').read_text())
    audit.update(class_count=72,video_frame_count=len(videos),public_train_count=len(training)-len(videos),
        heldout_candidate_counts=heldout_counts,independent_evaluation_completed=False,
        data_yaml_sha256=digest(output/'data.yaml'),split_manifest_sha256=digest(output/'split_manifest.json'),
        heldout_annotation_sha256={s:digest(output/f'{s}_annotations.jsonl') for s in ('val','test')},
        increment_inputs=inputs,integration=dict(integration),
        note='All72 original class IDs retained. All6 videos train-only. Public groups split before training; candidate holdouts remain partially annotated, not complete all-class mAP truth. No final acceptance yet.')
    save(output/'dataset_audit.json',audit)
    assert dataset_names(output)==NAMES
    save(ROOT/'active_training.json',dict(profile='street72',schema=str(ROOT/'street_classes.json'),
        dataset=str(output),class_count=72,model='YOLOv8s YOLO-World v2',status='ready_for_updated_baseline',
        epochs=15,run_test_after_training=False,
        post_training_policy='Save weights and logs; no test-set inference or evaluation without a later user instruction.',
        supersedes='core18 (inactive historical export)',
        final_acceptance='Pending remaining annotation coverage, validation-based selection and fixed test evaluation.'))
    print(json.dumps({k:audit[k] for k in ('class_count','frame_count','video_frame_count','public_train_count','box_count','zero_positive_classes','heldout_candidate_counts')},ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'local_training/collection_20260926/reviewed72_v2')
    parser.add_argument('--public-dir',type=Path,default=COVERAGE/'public_split72_v1')
    args=parser.parse_args();build(args.output.resolve(),args.public_dir.resolve())
