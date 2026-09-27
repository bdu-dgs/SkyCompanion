#!/usr/bin/env python3
"""Lock research and precision-oriented operating points on val, then evaluate test."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.obstacle_models import LocalDetector
from app.obstacle_eval import evaluate,validate_dataset
from app.obstacle_risk import iou
from calibrate_obstacle_threshold import ALIASES
THRESHOLDS=[.01,.025,.05,.075,.1,.15,.2,.25,.3,.4,.5,.6,.7,.8,.9,.95,.99]


def filtered(pred,threshold):
    return {k:[b for b in boxes if b['confidence']>=threshold] for k,boxes in pred.items()}


def choice(grid,min_precision=0.):
    eligible=[g for g in grid if g['precision']>=min_precision and g['recall']>0]
    if not eligible:return None
    if min_precision:
        return max(eligible,key=lambda g:(g['recall'],g['precision'],g['threshold']))
    return max(eligible,key=lambda g:(g['f1'],g['precision'],g['threshold']))


def collect(det,images):
    predictions={};timings=[]
    for im in images:
        frame=cv2.imread(im['path'])
        if frame is None:raise ValueError(im['path'])
        start=time.perf_counter();predictions[im['id']]=det.predict(frame)
        timings.append((time.perf_counter()-start)*1000)
    return predictions,{'p50_ms':float(np.percentile(timings,50)),
        'p95_ms':float(np.percentile(timings,95)),'serial_inference_fps':1000/float(np.mean(timings)),
        'samples':len(timings),'scope':'Warm serial batch1 including postprocess; excludes capture, network and audio.'}


def diagnose(images,predictions,threshold):
    """Explain val misses using already returned >=.01 predictions, not imagined raw proposals."""
    from collections import Counter
    rows=[]
    for im in images:
        boxes=predictions.get(im['id'],[])
        for index,target in enumerate(im['annotations']):
            if target['label']!='pole':continue
            same=[b for b in boxes if ALIASES.get(b['label'],b['label'])=='pole']
            active=[b for b in same if b['confidence']>=threshold]
            best_active=max(active,key=lambda b:iou(b,target),default=None)
            best_low=max(same,key=lambda b:iou(b,target),default=None)
            wrong=[b for b in boxes if ALIASES.get(b['label'],b['label'])!='pole' and b['confidence']>=threshold]
            best_wrong=max(wrong,key=lambda b:iou(b,target),default=None)
            if best_active and iou(best_active,target)>=.5:reason='compatible_box_iou_50'
            elif best_low and iou(best_low,target)>=.5:reason='below_selected_confidence'
            elif best_wrong and iou(best_wrong,target)>=.5:reason='other_class_overlap'
            elif best_active and iou(best_active,target)>=.1:reason='localization_or_box_scope_mismatch'
            else:reason='no_matching_returned_box_at_or_above_0.01'
            rows.append({'image_id':im['id'],'path':im['path'],'target_index':index,
                'target':target,'reason':reason,'best_active':best_active,'best_low_threshold':best_low})
    return {'scope':'Validation target-wise diagnostic; not one-to-one matching metrics or an assertion about raw network proposals.',
            'counts':dict(Counter(r['reason'] for r in rows)),'targets':rows}


def main():
    p=argparse.ArgumentParser();p.add_argument('dataset',type=Path)
    p.add_argument('--candidate',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--device',default='mps');p.add_argument('--sizes',nargs='+',type=int,default=[640,960])
    a=p.parse_args()
    if a.output.exists():raise ValueError('Fresh output directory required')
    d=json.loads(a.dataset.read_text());validate_dataset(d);d['evaluation_aliases']=ALIASES
    subsets={s:dict(d,images=[i for i in d['images'] if i['split']==s]) for s in ['val','test']}
    if any(not v['images'] for v in subsets.values()):raise ValueError('Missing val/test')
    a.output.mkdir(parents=True)
    report={'candidate_sha256':hashlib.sha256(a.candidate.read_bytes()).hexdigest(),
        'dataset_sha256':hashlib.sha256(a.dataset.read_bytes()).hexdigest(),
        'selection_rule':'Validation only: best pole F1, plus highest recall at precision >= 0.80 when achievable.',
        'test_role':'Previously used publisher test; repeated regression, not an untouched blind holdout.',
        'limitations':['Publisher labels have observed omissions and inconsistent pole scope.',
                       'Utility pole/tower candidate is not a replacement for the 115-class live model.',
                       'No video first-detection timing available.'], 'validation_grid':[], 'test':{}, 'deployed':False}
    for size in a.sizes:
        det=LocalDetector('skycompanion-finetuned',imgsz=size,device=a.device,confidence=.01)
        det.path=a.candidate.resolve();det.load()
        pred,timing=collect(det,subsets['val']['images'])
        (a.output/f'val-{size}-predictions.json').write_text(json.dumps({'metadata':det.metadata(),'predictions':pred,'timing':timing}))
        for threshold in THRESHOLDS:
            ev=evaluate(subsets['val'],filtered(pred,threshold));row=ev['per_class']['pole']
            pr,rc=row['precision'] or 0.,row['recall'] or 0.
            report['validation_grid'].append({'imgsz':size,'threshold':threshold,'precision':pr,'recall':rc,
                'f1':2*pr*rc/(pr+rc) if pr+rc else 0.,'evaluation':ev})
        print('Validation finished',size,flush=True)
    report['locked_settings']={'best_f1':choice(report['validation_grid']),
        'precision_80':choice(report['validation_grid'],.8)}
    # Persist all selected settings before processing test pixels.
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    best=report['locked_settings']['best_f1']
    if best:
        low=json.loads((a.output/f"val-{best['imgsz']}-predictions.json").read_text())['predictions']
        diagnostic=diagnose(subsets['val']['images'],low,best['threshold'])
        (a.output/'val-miss-diagnostic.json').write_text(json.dumps(diagnostic,indent=2)+'\n')
        report['validation_miss_diagnostic']=diagnostic['counts']
    for name,setting in report['locked_settings'].items():
        if setting is None:continue
        det=LocalDetector('skycompanion-finetuned',imgsz=setting['imgsz'],device=a.device,confidence=setting['threshold'])
        det.path=a.candidate.resolve();det.load()
        pred,timing=collect(det,subsets['test']['images'])
        report['test'][name]={'metadata':det.metadata(),'evaluation':evaluate(subsets['test'],pred),'timing':timing}
        (a.output/f'test-{name}-predictions.json').write_text(json.dumps(pred))
        (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(name,report['test'][name]['evaluation']['per_class']['pole'],timing,flush=True)


if __name__=='__main__':main()
