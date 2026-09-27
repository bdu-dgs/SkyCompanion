#!/usr/bin/env python3
"""Register sampled raw inputs; leave all annotations unreviewed."""
import argparse
import hashlib
import json
from pathlib import Path

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('case',type=Path)
    p.add_argument('dataset',type=Path)
    p.add_argument('--video-group',required=True)
    p.add_argument('--location-group',default='unknown')
    p.add_argument('--split',choices=['unassigned','train','val','test'],default='unassigned')
    p.add_argument('--interval',type=float,default=1.)
    a=p.parse_args()
    if a.interval <= 0:p.error('interval must be positive')
    source=json.loads((a.case/'manifest.json').read_text())
    if source.get('evidence_kind') or not source.get('frames'):
        p.error('Original sampled clips are required; screenshots cannot serve as clean training input')
    data=json.loads(a.dataset.read_text())
    old_ids={im['id'] for im in data['images']}
    previous=-float('inf')
    first=source['frames'][0]['received_monotonic_s']
    for f in source['frames']:
        t=f['received_monotonic_s']-first
        if t-previous < a.interval:continue
        previous=t
        identifier=f"{source['case_id']}-{f['frame_id']}"
        if identifier in old_ids:continue
        path=(a.case/f['input_file']).resolve()
        data['images'].append({'id':identifier,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
             'video_group':a.video_group,'location_group':a.location_group,'split':a.split,
             'clip_id':source['case_id'],'time_s':t,'time_basis':'capture_relative_not_original_video_timestamp',
             'review_status':'unreviewed','reviewed_classes':[],'annotations':[],
             'source_case':str((a.case/'manifest.json').resolve())})
    # Validate before changing the index, including video/location split conflicts.
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
    from app.obstacle_eval import validate_dataset
    validate_dataset(data)
    a.dataset.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print('registered',len(data['images'])-len(old_ids),'unreviewed images')
