#!/usr/bin/env python3
"""Evaluate selected clean-frame targets; unannotated objects are NOT false positives."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import cv2
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.obstacle_models import LocalDetector
from app.obstacle_risk import iou

LABELS={'pole':{'pole','light pole','signpost','scaffolding pole','utility_pole','utility pole','lamp post'},
        'column':{'column','pillar'}}


def apply_locked_thresholds(predictions, thresholds):
    """Use thresholds selected on a separate validation set, never on these frames."""
    if not thresholds:
        return predictions
    kept = []
    for box in predictions:
        category = next((name for name, aliases in LABELS.items() if box['label'] in aliases), None)
        if category is None or box['confidence'] >= thresholds.get(category, 1.):
            kept.append(box)
    return kept


def score_targets(targets,predictions):
    pairs=[]
    for n,t in enumerate(targets):
        for j,b in enumerate(predictions):
            if b['label'] in LABELS[t['label']]:pairs.append((iou(t,b),n,j))
    used_targets=set();used_predictions=set();matched={}
    for overlap,n,j in sorted(pairs,reverse=True):
        if overlap>=.5 and n not in used_targets and j not in used_predictions:
            used_targets.add(n);used_predictions.add(j);matched[n]=j
    rows=[]
    for n,t in enumerate(targets):
        compatible=[b for b in predictions if b['label'] in LABELS[t['label']]]
        best=max(compatible,key=lambda b:iou(t,b),default=None)
        rows.append({'target_id':t['target_id'],'label':t['label'],'subcategory':t['subcategory'],
            'hit_iou_50':n in matched,'best_compatible_iou':iou(t,best) if best else 0.,
            'best_compatible_prediction':best,
            'target':t})
    return rows


def main():
    p=argparse.ArgumentParser();p.add_argument('targets',type=Path)
    p.add_argument('--configs',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--device',default='mps');a=p.parse_args()
    if a.output.exists():raise ValueError('Use fresh output')
    d=json.loads(a.targets.read_text());configs=json.loads(a.configs.read_text())
    for im in d['images']:
        assert hashlib.sha256(Path(im['path']).read_bytes()).hexdigest()==im['sha256']
        assert len({r['reviewer'] for r in im['review_passes']})>=2
    a.output.mkdir(parents=True)
    report={'target_manifest_sha256':hashlib.sha256(a.targets.read_bytes()).hexdigest(),
        'scope':d['box_scope'],'limitations':['Selected targets only: precision and false-positive counts unavailable.',
            'Previously inspected development frames, not an independent holdout.',
            'Shaft boxes exclude projecting fixtures; low IoU can reflect inconsistent assembly/shaft scope.'],
        'models':{}}
    report['limitations'].extend(d.get('limitations', []))
    for cfg in configs:
        det=LocalDetector(cfg['profile'],imgsz=cfg['imgsz'],confidence=cfg['confidence'],device=a.device)
        if cfg.get('path'):det.path=Path(cfg['path']).resolve()
        det.load();rows=[];frames=[]
        for im in d['images']:
            frame=cv2.imread(im['path']);raw_boxes=det.predict(frame)
            boxes=apply_locked_thresholds(raw_boxes,cfg.get('thresholds'))
            results=score_targets(im['annotations'],boxes)
            rows.extend(results);frames.append({'id':im['id'],'predictions':boxes,'targets':results})
            canvas=frame.copy();h,w=canvas.shape[:2]
            for b in boxes:
                if not any(b['label'] in labels for labels in LABELS.values()):continue
                x,y,bw,bh=[b[k] for k in ('x','y','w','h')]
                p1,p2=(int(x*w),int(y*h)),(int((x+bw)*w),int((y+bh)*h))
                cv2.rectangle(canvas,p1,p2,(80,220,80),2)
                cv2.putText(canvas,f"{b['label']} {b['confidence']:.2f}",p1,cv2.FONT_HERSHEY_SIMPLEX,.4,(80,220,80),1)
            for t in im['annotations']:
                x1,y1,x2,y2=t['xyxy_pixels'];cv2.rectangle(canvas,(x1,y1),(x2,y2),(0,170,255),1)
            header=cv2.copyMakeBorder(canvas,30,0,0,0,cv2.BORDER_CONSTANT,value=(0,0,0))
            cv2.putText(header,cfg['name']+' | green=prediction; orange=reviewed target', (8,20),cv2.FONT_HERSHEY_SIMPLEX,.4,(255,255,255),1)
            cv2.imwrite(str(a.output/(cfg['name']+'-'+im['id']+'.png')),header)
        summary={kind:{'targets':sum(t['label']==kind for t in rows),
                        'hits':sum(t['label']==kind and t['hit_iou_50'] for t in rows)} for kind in LABELS}
        report['models'][cfg['name']]={'metadata':det.metadata(),'configuration':cfg,'selected_target_results':summary,'frames':frames}
        print(cfg['name'],summary,flush=True)
        (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
