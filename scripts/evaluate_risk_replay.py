#!/usr/bin/env python3
"""Replay recorded detections; this measures scheduler behavior, not hazard accuracy."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.obstacle_risk import RiskMonitor


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('manifests',type=Path,nargs='+')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): raise ValueError('Use a new output file')
    corridor=[[.35,.45],[.65,.45],[.9,1],[.1,1]]
    report={'scope':'Recorded prediction replay, not fresh YOLO inference or human safety evaluation',
            'corridor':corridor,'corridor_basis':'fixed experimental image region, not a calibrated walking path',
            'limitations':['No obstacle ground truth or wearer pose/depth measurements',
                          'Missed detections remain absent; risk logic cannot create missing objects',
                          'Event counts are not measured acoustic interruptions'], 'clips':[]}
    for path in args.manifests:
        data=json.loads(path.read_text()); monitor=RiskMonitor(); rows=[]; counts=Counter(); events=[]
        frames=data['frames']; start=frames[0]['received_monotonic_s']
        for frame in frames:
            timestamp=frame['received_monotonic_s']
            result=monitor.update(frame['boxes'],corridor,timestamp)
            event=result.get('event'); counts[result['lifecycle']]+=1
            row={'frame_id':frame['frame_id'],'relative_s':round(timestamp-start,3),
                 'risk_level':result['risk_level'],'lifecycle':result['lifecycle'],
                 'direction':result['direction'],'reason_codes':result['reason_codes']}
            if event:
                age=frame.get('server_frame_age_ms',0)
                ev={'at_s':row['relative_s'],'track_id':event['track_id'],
                    'level':event['risk_level'],'reasons':event['reason_codes'],
                    'text':event['text'],'valid_after_recorded_processing':age<event['ttl_ms']}
                events.append(ev); row['event']=ev
            rows.append(row)
        report['clips'].append({'manifest':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'frames':len(frames),'duration_s':round(frames[-1]['received_monotonic_s']-start,3),
            'lifecycle_frames':dict(counts),'events':events,'trace':rows})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    for clip in report['clips']:
        print(Path(clip['manifest']).parent.name,clip['frames'],clip['duration_s'],len(clip['events']),clip['lifecycle_frames'])


if __name__=='__main__': main()
