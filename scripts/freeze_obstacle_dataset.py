#!/usr/bin/env python3
"""Freeze exact regression inputs plus complete saved before/after frame sequences."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.obstacle_eval import validate_dataset, dataset_readiness


def freeze(source, output):
    data=json.loads(source.read_text());validate_dataset(data)
    if output.exists():raise ValueError('New version directory required; existing snapshots are never overwritten')
    output.mkdir(parents=True)
    contexts={}
    for im in data['images']:
        old=Path(im['path']);dest=output/'images'/(hashlib.sha256(im['id'].encode()).hexdigest()[:20]+old.suffix)
        dest.parent.mkdir(exist_ok=True);shutil.copy2(old,dest)
        im['original_path']=str(old);im['path']=str(dest.resolve())
        # Conservative grouping: keep all potentially overlapping NYC clips together.
        if im['video_group']=='bilibili-nyc-user-video':
            im['location_group']='new-york-manhattan-user-video'
            im['split']='test'
            im['split_note']='Development regression set already inspected; never claim a blind holdout.'
        if im.get('source_case'):
            manifest=Path(im['source_case']);case=json.loads(manifest.read_text())
            name=case['case_id'];target=output/'context'/name
            if name not in contexts:
                target.mkdir(parents=True)
                files={'manifest.json'}
                for frame in case['frames']:
                    files.update(frame[k] for k in ('source_file','input_file') if frame.get(k))
                inventory=[]
                for relative in sorted(files):
                    src=manifest.parent/relative;dst=target/relative;dst.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(src,dst)
                    inventory.append({'file':relative,'sha256':hashlib.sha256(dst.read_bytes()).hexdigest()})
                contexts[name]={'frame_count':len(case['frames']),'files':inventory,
                    'duration_s':case['frames'][-1]['received_monotonic_s']-case['frames'][0]['received_monotonic_s'],
                    'time_basis':'receiver_monotonic_frame_sequence_not_original_video_clock'}
            im['source_case']=str((target/'manifest.json').resolve())
    data.update(version='regression-20260926-v1',purpose='fixed_development_regression_not_blind_acceptance',
                source_dataset_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                freeze_policy='No frame resampling or image overlays; original context JPEG/PNG and timing retained.')
    validate_dataset(data)
    (output/'dataset.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    (output/'context-index.json').write_text(json.dumps(contexts,ensure_ascii=False,indent=2)+'\n')
    (output/'readiness.json').write_text(json.dumps(dataset_readiness(data),ensure_ascii=False,indent=2)+'\n')
    digest=hashlib.sha256((output/'dataset.json').read_bytes()).hexdigest()
    (output/'dataset.sha256').write_text(digest+'  dataset.json\n')
    print(json.dumps({'images':len(data['images']),'contexts':len(contexts),'dataset_sha256':digest,'output':str(output.resolve())}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();freeze(a.source,a.output.resolve())
