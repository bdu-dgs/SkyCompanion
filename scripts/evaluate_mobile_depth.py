#!/usr/bin/env python3
"""Evaluate manually measured held-out depth CSV; never activates app guidance.
Columns: split,clip_id,camera_id,model_id,preprocessing_id,reference,predicted_m,measured_m.
Measure optical-axis depth with centered targets. Never substitute bbox growth for truth.
"""
import argparse,csv,json,math,statistics
from pathlib import Path

def percentile(values,p):
    values=sorted(values)
    return values[min(len(values)-1,math.ceil(p*len(values))-1)]

def evaluate(rows):
    reasons=[]
    scope={tuple(r.get(k,'') for k in ('camera_id','model_id','preprocessing_id','reference')) for r in rows}
    if len(scope)!=1 or not rows or any(not v for entry in scope for v in entry): reasons.append('Exactly one nonempty camera/model/preprocessing/reference scope required')
    if any(r.get('reference')!='camera_optical_axis' for r in rows): reasons.append('Optical-axis measurement reference required')
    partitions={'calibration':[],'test':[]}
    for r in rows:
        try:
            pred=float(r['predicted_m']);true=float(r['measured_m'])
            if not all(math.isfinite(x) and .1<x<79.5 for x in (pred,true)): raise ValueError()
            if not r.get('clip_id') or r.get('split') not in partitions: raise ValueError()
            partitions[r['split']].append((r['clip_id'],pred,true))
        except (KeyError,ValueError): reasons.append('Missing, invalid or nonfinite measurement row')
    clips={k:{r[0] for r in v} for k,v in partitions.items()}
    if clips['calibration']&clips['test']: reasons.append('Calibration and test clips must be disjoint')
    for key,values in partitions.items():
        if len(values)<30 or len(clips[key])<3: reasons.append(f'{key}: need at least 30 measured targets across 3 independent clips')
    report={'state':'insufficient_data' if reasons else 'evaluated','reasons':sorted(set(reasons)), 'appGuidanceEnabled':False,
            'scope':list(scope),'counts':{k:len(v) for k,v in partitions.items()},
            'limits':'Engineering screening only; correlated frames, domain coverage and labels require review. This file does not unlock distance speech.'}
    if reasons:return report
    radius=percentile([abs(p-t) for _,p,t in partitions['calibration']],.95)
    test=partitions['test'];errors=[abs(p-t) for _,p,t in test]
    coverage=sum(abs(p-t)<=radius for _,p,t in test)/len(test)
    report.update({'candidateIntervalHalfWidthMeters':radius,'testMAEMeters':statistics.mean(errors),'testP95AbsoluteErrorMeters':percentile(errors,.95),
                   'testRelativeErrorMedian':statistics.median(abs(p-t)/t for _,p,t in test),'testIntervalCoverage':coverage,
                   'engineeringScreenPassed':coverage>=.9 and percentile(errors,.95)<=1 and radius<=1})
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('csv',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
    with a.csv.open(newline='') as f:report=evaluate(list(csv.DictReader(f)))
    text=json.dumps(report,indent=2);print(text)
    if a.output:a.output.write_text(text+'\n')
if __name__=='__main__':main()
