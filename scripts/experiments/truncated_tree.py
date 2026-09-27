#!/usr/bin/env python3
"""Bounded CPU tree/trunk ablation on one clean frame; does not change live weights."""
import os
os.environ['YOLO_AUTOINSTALL'] = 'False'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
import json
import time
from pathlib import Path
import cv2
import numpy as np
import torch
from ultralytics import YOLOE, __version__
from street_furniture import annotated, detections, sha, save_json

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT/'backend/data/models'
OUT = ROOT/'backend/data/obstacle_experiments/truncated-tree'
SOURCE = ROOT/'backend/data/obstacle_cases/20260926-012001-324062cf/00017327-input.png'
TARGET = [565, 0, 633, 392]  # Assistant draft matching region, never drawn as a prediction.


def target_overlap(xyxy):
    x1,y1,x2,y2=xyxy
    tx1,ty1,tx2,ty2=TARGET
    intersection=max(0,min(x2,tx2)-max(x1,tx1))*max(0,min(y2,ty2)-max(y1,ty1))
    return intersection/max(1,(x2-x1)*(y2-y1)+(tx2-tx1)*(ty2-ty1)-intersection)


def main():
    torch.set_num_threads(2)
    torch.manual_seed(0)
    os.chdir(MODELS)
    OUT.mkdir(parents=True,exist_ok=True)
    image=cv2.imread(str(SOURCE))
    assert image is not None
    assert (MODELS/'yoloe-11s-seg.pt').is_file()
    assert (MODELS/'mobileclip_blt.ts').is_file()
    baseline=MODELS/'skycompanion-yoloe-11s-v7.pt'
    report={'purpose':'one_frame_threshold_and_vocabulary_diagnostic_not_acceptance',
            'source':str(SOURCE),'source_sha256':sha(SOURCE),'input_wh':list(image.shape[1::-1]),
            'device':'cpu','torch_threads':2,'imgsz':960,'iou':.7,'agnostic_nms':True,
            'ultralytics':__version__,'torch':torch.__version__,
            'timing_scope':'post-warmup predict wall time including preprocess/inference/postprocess; not live FPS',
            'training_performed':False,'live_configuration_changed':False,
            'assistant_draft_target_xyxy':TARGET,'target_is_human_verified':False,
            'target_attributes':{'top_truncated':True,'partly_occluded':True,'visible_base':True},
            'target_match_rule':'diagnostic bbox IoU >= 0.30 with assistant draft; inspect overlay, not official AP',
            'models':{},'results':[]}
    overlays=[]
    for label,names in [('v7-115',None),('tree-only',['tree']),('trunk-only',['tree trunk'])]:
        model=YOLOE(str(baseline if names is None else MODELS/'yoloe-11s-seg.pt'))
        if names is not None:
            model.set_classes(names,model.get_text_pe(names))
        report['models'][label]={'source_sha256':sha(baseline if names is None else MODELS/'yoloe-11s-seg.pt'),
                                 'names':model.names, 'text_prompts_replaced':names is not None}
        kwargs=dict(imgsz=960,iou=.7,agnostic_nms=True,device='cpu',verbose=False)
        model.predict(image,conf=.05,**kwargs)
        for threshold in (.25,.1,.05):
            calls=[]
            for _ in range(2):
                start=time.perf_counter()
                result=model.predict(image,conf=threshold,**kwargs)[0]
                calls.append((time.perf_counter()-start)*1000)
            boxes=detections(result)
            for b in boxes:
                b['draft_target_iou']=target_overlap(b['xyxy'])
            relevant=[b for b in boxes if b['draft_target_iou']>=.30]
            tree_boxes=[b for b in boxes if b['label'] in ('tree','tree trunk')]
            heading=f'{label} | conf={threshold} | input=960x443 | imgsz=960 | CPU'
            canvas=annotated(image,boxes,heading,False)
            path=OUT/f'{label}-conf-{threshold}.png'
            cv2.imwrite(str(path),canvas)
            overlays.append(canvas)
            row={'model':label,'confidence_threshold':threshold,'predict_call_ms':calls,
                 'median_predict_ms':float(np.median(calls)),'ultralytics_speed_ms':result.speed,
                 'detections':boxes,'target_matches':relevant,'tree_or_trunk_predictions':tree_boxes,
                 'overlay':str(path)}
            report['results'].append(row)
            save_json(OUT/'results.json',report)
            print(json.dumps({k:row[k] for k in ('model','confidence_threshold','median_predict_ms','target_matches','tree_or_trunk_predictions')}),flush=True)
        del model
    cv2.imwrite(str(OUT/'comparison.png'),np.vstack([np.hstack(overlays[i:i+3]) for i in (0,3,6)]))
    print(str(OUT/'comparison.png'),flush=True)

if __name__=='__main__':main()
