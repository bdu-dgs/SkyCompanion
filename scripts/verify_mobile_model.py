#!/usr/bin/env python3
"""Mac conversion/candidate regression. Never labels Mac timing as iPhone evidence."""
from __future__ import annotations
import argparse, hashlib, json, os, time, platform
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('YOLO_AUTOINSTALL','false')
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'.skycompanion-live/mobile-export/ultralytics'))

def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def iou(a,b):
    x1,y1=max(a[0],b[0]),max(a[1],b[1]);x2,y2=min(a[2],b[2]),min(a[3],b[3])
    inter=max(0,x2-x1)*max(0,y2-y1)
    return inter/max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--models',nargs='+',default=['SkyCompanionYOLOE_v7_960_FP16','SkyCompanionYOLOE_v7_640_FP16','SkyCompanionYOLOE_v7_480_FP16'])
    p.add_argument('--output',type=Path,default=ROOT/'ios/Models/parity-report.json')
    p.add_argument('--manifest',type=Path,default=ROOT/'samples/local/external-streets-20260926/riverside-labels-reviewed-v2.json')
    p.add_argument('--limit',type=int,default=10)
    args=p.parse_args()
    import cv2,numpy as np,torch,coremltools as ct
    from PIL import Image
    from ultralytics import YOLOE
    from ultralytics.utils import ops
    from ultralytics.utils.nms import non_max_suppression
    torch.set_num_threads(2)
    source=ROOT/'backend/data/models/skycompanion-yoloe-11s-v7.pt'
    pt=YOLOE(str(source));pt.model.eval()
    data=json.loads(args.manifest.read_text());images=data['images'][:args.limit]
    report={'sourceSHA256':digest(source),'datasetSHA256':digest(args.manifest),'datasetManifest':str(args.manifest),'frameCount':len(images),'hardware':platform.platform(),
            'scope':'Mac CPU_ONLY Core ML; conversion equivalence + selected-class regression, NOT phone runtime or 115-class acceptance',
            'limitations':['Development frames with assistant reviewed selected targets, not human-reviewed or independent holdout.',
             'Model-to-model agreement is not ground truth accuracy.', 'Partial annotations: no false-positive gate computed.',
             'Input intentionally uses fixed square letterbox; desktop rect=True padding has a different shape.'], 'models':{}}
    def preprocess(image,size):
        h,w=image.shape[:2];gain=min(size/w,size/h);rw,rh=round(w*gain),round(h*gain)
        left,top=round((size-rw)/2-.1),round((size-rh)/2-.1)
        rgb=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
        rgb=cv2.copyMakeBorder(cv2.resize(rgb,(rw,rh)),top,size-rh-top,left,size-rw-left,cv2.BORDER_CONSTANT,value=(114,114,114))
        return rgb,(gain,left,top,w,h)
    def decode(pred,proto,size,geo):
        tensor=torch.from_numpy(pred.copy());proto=torch.from_numpy(proto.copy())
        out=non_max_suppression(tensor,conf_thres=.25,iou_thres=.7,agnostic=True,nc=115,max_det=300)[0]
        boxes=[]; masks=[]
        for row in out:
            xy=row[:4].numpy();g,l,t,w,h=geo
            box=np.clip((xy-np.array([l,t,l,t]))/g/np.array([w,h,w,h]),0,1).tolist()
            boxes.append({'classID':int(row[5]),'label':pt.names[int(row[5])],'confidence':float(row[4]),'xyxy':box})
        if len(out):
            masks=ops.process_mask(proto[0],out[:,6:],out[:,:4],(size,size),upsample=False).numpy().astype(bool)
        return boxes,masks
    for name in args.models:
        meta=json.loads((ROOT/'ios/Models'/f'{name}.json').read_text());size=meta['inputSize']
        start=time.perf_counter();cm=ct.models.MLModel(str(ROOT/'ios/Models'/f'{name}.mlpackage'),compute_units=ct.ComputeUnit.CPU_ONLY)
        load=time.perf_counter()-start
        predname=next(o['name'] for o in meta['outputs'] if len(o['shape'])==3)
        protoname=next(o['name'] for o in meta['outputs'] if len(o['shape'])==4)
        rows=[];timings=[];allious=[];maskious=[];agreements=[];selected={}
        for im in images:
            assert digest(im['path'])==im['sha256']
            image=cv2.imread(im['path']);rgb,geo=preprocess(image,size)
            x=torch.from_numpy(rgb.transpose(2,0,1).copy()).unsqueeze(0).float()/255
            # Export uses fuse + export=True. Raw forward still returns identical prediction/proto tensors.
            with torch.inference_mode(): raw=pt.model(x)
            ptpred=raw[0][0].numpy();ptproto=raw[0][1].numpy()
            pyboxes,pymasks=decode(ptpred,ptproto,size,geo)
            if not rows: cm.predict({'image':Image.fromarray(rgb)})
            t=time.perf_counter();out=cm.predict({'image':Image.fromarray(rgb)});elapsed=(time.perf_counter()-t)*1000;timings.append(elapsed)
            boxes,masks=decode(out[predname],out[protoname],size,geo)
            used=set();matches=[]
            for i,a in enumerate(pyboxes):
                options=[(iou(a['xyxy'],b['xyxy']),j) for j,b in enumerate(boxes) if j not in used and b['classID']==a['classID']]
                overlap,j=max(options,default=(0,-1))
                if overlap>=.5:
                    used.add(j);allious.append(overlap)
                    mi=float(np.logical_and(pymasks[i],masks[j]).sum()/max(1,np.logical_or(pymasks[i],masks[j]).sum()));maskious.append(mi)
                    matches.append({'pytorch':i,'coreml':j,'boxIoU':overlap,'maskIoU':mi})
            agreements.append(1.0 if not pyboxes and not boxes else len(matches)/max(1,len(pyboxes)))
            for gt in im.get('annotations',[]):
                label=gt['label'];a=[gt['x'],gt['y'],gt['x']+gt['w'],gt['y']+gt['h']]
                hit=any(b['label']==label and iou(a,b['xyxy'])>=.5 for b in boxes)
                entry=selected.setdefault(label,{'targets':0,'hits':0});entry['targets']+=1;entry['hits']+=hit
            rows.append({'id':im['id'],'imageSHA256':im['sha256'],'pytorchDetections':pyboxes,'coremlDetections':boxes,'matches':matches,'macPredictionMS':elapsed})
        report['models'][name]={'inputSize':size,'packageBytes':meta['packageBytes'],'loadSeconds':load,
                'macPredictionP50MS':float(np.percentile(timings,50)), 'macPredictionP95MS':float(np.percentile(timings,95)),
                'meanBoxIoU':float(np.mean(allious)) if allious else None,'meanMaskIoU':float(np.mean(maskious)) if maskious else None,
                'meanDetectionAgreement':float(np.mean(agreements)), 'selectedTargetRecallCounts':selected,'frames':rows}
        args.output.write_text(json.dumps(report,indent=2)+'\n')
        print(name,{k:v for k,v in report['models'][name].items() if k!='frames'},flush=True)
if __name__=='__main__':main()
