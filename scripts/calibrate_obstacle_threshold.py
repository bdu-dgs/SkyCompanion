#!/usr/bin/env python3
"""Select threshold/scale using publisher val only, then evaluate locked settings on test."""
import argparse,json,sys,time,hashlib
from pathlib import Path
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.obstacle_models import LocalDetector
from app.obstacle_eval import evaluate,validate_dataset
ALIASES={'light pole':'pole','signpost':'pole','scaffolding pole':'pole','utility_pole':'pole','utility pole':'pole','lamp post':'pole'}
THRESHOLDS=[.01,.025,.05,.1,.15,.25,.35,.5]


def run(detector,images):
    predictions={};timings=[]
    for im in images:
        frame=cv2.imread(im['path']);start=time.perf_counter();predictions[im['id']]=detector.predict(frame)
        timings.append((time.perf_counter()-start)*1000)
    return predictions,{'p50_ms':float(np.percentile(timings,50)),'p95_ms':float(np.percentile(timings,95)),
                        'serial_inference_fps':1000/float(np.mean(timings)),'samples':len(timings)}


def main():
    p=argparse.ArgumentParser();p.add_argument('dataset',type=Path);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('Use a fresh output file')
    data=json.loads(a.dataset.read_text());validate_dataset(data)
    data['evaluation_aliases']=ALIASES
    val=dict(data,images=[i for i in data['images'] if i['split']=='val'])
    test=dict(data,images=[i for i in data['images'] if i['split']=='test'])
    report={'dataset_sha256':hashlib.sha256(a.dataset.read_bytes()).hexdigest(),
            'selection_rule':'Highest validation pole F1; tie: higher precision then higher threshold. No test-based selection.',
            'aliases':ALIASES,'validation_grid':{},'test':{},'deployment_allowed':False,
            'time_limit':'Still images; temporal first discovery unavailable; inference timing excludes network/audio.'}
    for profile,sizes in [('yoloe-11s',[960]),('local-candidate',[640,960])]:
        grid=[]
        for size in sizes:
            det=LocalDetector('skycompanion-finetuned' if profile=='local-candidate' else profile,imgsz=size,device='mps',confidence=.01)
            if profile=='local-candidate':det.path=a.candidate.resolve()
            det.load();pred,timing=run(det,val['images'])
            for threshold in THRESHOLDS:
                filtered={k:[b for b in boxes if b['confidence']>=threshold] for k,boxes in pred.items()}
                ev=evaluate(val,filtered);pole=ev['per_class']['pole'];precision=pole['precision'] or 0.;recall=pole['recall'] or 0.
                f1=2*precision*recall/(precision+recall) if precision+recall else 0.
                grid.append({'imgsz':size,'threshold':threshold,'pole_f1':f1,'precision':precision,'evaluation':ev})
            print(profile,size,'validation complete',timing,flush=True)
        winner=max(grid,key=lambda x:(x['pole_f1'],x['precision'],x['threshold']))
        report['validation_grid'][profile]=grid
        # Lock the validation choice before opening test inputs for inference.
        report.setdefault('locked_settings',{})[profile]={k:winner[k] for k in ('imgsz','threshold','pole_f1')}
        a.output.write_text(json.dumps(report,indent=2)+'\n')
        det=LocalDetector('skycompanion-finetuned' if profile=='local-candidate' else profile,
                          imgsz=winner['imgsz'],device='mps',confidence=winner['threshold'])
        if profile=='local-candidate':det.path=a.candidate.resolve()
        det.load();pred,timing=run(det,test['images'])
        report['test'][profile]={'metadata':det.metadata(),'timing':timing,'evaluation':evaluate(test,pred),'predictions':pred}
        a.output.write_text(json.dumps(report,indent=2)+'\n')
        print(profile,'locked',report['locked_settings'][profile], 'test complete',flush=True)


if __name__=='__main__':main()
