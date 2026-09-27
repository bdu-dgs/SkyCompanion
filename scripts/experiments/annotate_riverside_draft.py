#!/usr/bin/env python3
"""Serialize assistant visual annotations made from each 1080x1920 original.

These overlays are draft labels, never detector predictions. Ambiguous distant
trunks remain unknown; independent review is needed before training export.
"""
import json
from pathlib import Path
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'samples/local/external-streets-20260926'
CLASSES=['tree trunk','fence','railing','traffic cone','curb','pole']
RAIL=[(639,0,1080,1020),(557,108,1080,976),(574,159,1080,969),(585,196,1080,1134),(511,91,1080,844),(483,112,1080,1154),(483,227,1080,1462),(505,158,1080,1458),(479,287,1080,1329),(486,276,1080,1235)]
CURB=[(0,86,540,1342),(0,167,540,1370),(0,198,530,1350),(0,211,538,1405),(0,141,479,1050),(0,162,457,1210),(0,261,448,1311),(0,219,465,1480),(0,350,444,1450),(0,357,439,1533)]
CONES=[(622,0,666,117),(592,132,640,277),(610,232,680,379),(655,325,763,560),(775,701,1080,1300)]
TREES=[[],[(801,40,958,303)],[(966,171,1080,405)],[],[(552,95,649,258)],[(561,65,637,280)],[(765,220,948,662),(582,105,683,367)],[(644,11,800,312),(570,89,635,283)],[(699,0,822,464),(586,228,640,391)],[(822,0,1075,502),(618,148,723,389),(564,235,610,354)]]
PALETTE={'tree trunk':(50,210,240),'railing':(0,180,255),'traffic cone':(255,130,30),'curb':(190,90,240),'pole':(40,220,100),'fence':(255,210,100)}

def main():
    source=json.loads((OUT/'manifest.json').read_text())['sources'][1]
    result={'schema_version':1,'classes':CLASSES,'status':'assistant_reviewed_selected_class_draft',
      'reviewer':'codex-risk_guidance','human_reviewed':False,'independent_second_review_complete':False,
      'source_manifest':str(OUT/'manifest.json'),'split_policy':'Single video/location group, all unassigned; do not split adjacent frames.',
      'frozen_dataset_modified':False,'training_eligible':False,
      'training_blocker':'Independent bbox/taxonomy review and resolution of ambiguous distant tree instances needed.',
      'label_policy':{
        'railing':'One contiguous assembled guardrail instance. Upright components are not duplicate standalone pole objects.',
        'fence':'Separate enclosed fence structure; not a synonym duplicate of railing. None clearly present.',
        'curb':'Continuous visible stone edge on footpath side of drainage channel. Drain void itself is not labeled curb. Taxonomy needs second reviewer agreement.',
        'tree trunk':'Visible main woody stem, excluding tree crown. Bounding rectangle around visible stem; never complete hidden/off-image trunk. Ambiguous tiny/background stems are unknown, not negatives.',
        'pole':'Standalone utility/support pole, excluding rail posts and trunks.',
        'near':'Qualitative camera-view extent/context, not metric distance or wearer-relative collision risk.'},'images':[]}
    folder=OUT/'riverside-assistant-labels-v1';folder.mkdir(exist_ok=True)
    contact=[]
    for i, frame in enumerate(source['frames']):
        image=cv2.imread(frame['path']);h,w=image.shape[:2];assert (w,h)==(1080,1920)
        row=dict(frame);row.update(review_status='assistant_reviewed',reviewed_classes=CLASSES,
            annotation_status='assistant_visual_draft',training_eligible=False,
            review_passes=[{'reviewer':'codex-risk_guidance','method':'Viewed each original at original detail, selected-class annotation',
                           'date':'2026-09-26','scope':'Clearly separable instances of six named classes; ambiguous distant trees explicitly unknown'}],
            class_coverage={c:('partial_ambiguous_background' if c=='tree trunk' else 'reviewed_visible_instances') for c in CLASSES},
            ignore_regions=[{'xyxy_pixels':[0,0,1080,400], 'classes':['tree trunk'],
                             'reason':'Only uncertain tiny/foliage-obscured distant stems in this region; explicit annotated trunks take precedence. Do not export region as tree-negative.'}],
            annotations=[])
        items=[('railing',RAIL[i],True,True),('curb',CURB[i],True,True)]
        if i<5:items.append(('traffic cone',CONES[i],i==4,False))
        if i==0:items.append(('pole',(981,0,1033,289),False,True))
        items.extend(('tree trunk',rect,False,True) for rect in TREES[i])
        canvas=image.copy()
        for n,(label,rect,near,occluded) in enumerate(items):
            x1,y1,x2,y2=rect;assert 0<=x1<x2<=w and 0<=y1<y2<=h
            annotation={'label':label,'x':x1/w,'y':y1/h,'w':(x2-x1)/w,'h':(y2-y1)/h,
              'xyxy_pixels':list(rect),'attributes':{'truncated':any((x1==0,y1==0,x2==w,y2==h)),
                'occluded':occluded,'near_in_image':near,'metric_distance_m':None,'visible_extent_only':True},
              'review_status':'assistant_visual_draft','instance_id':f'frame-{i:02d}-{n}'}
            row['annotations'].append(annotation)
            color=PALETTE[label];cv2.rectangle(canvas,(x1,y1),(x2-1,y2-1),color,3)
            y=min(h-10,max(30,y1+26));cv2.putText(canvas,f'DRAFT {label}',(max(3,x1),y),cv2.FONT_HERSHEY_SIMPLEX,.65,color,2)
        title=np.full((100,w,3),25,np.uint8)
        cv2.putText(title,f'ASSISTANT DRAFT LABELS - NOT MODEL OUTPUT | frame {i:02d}',(12,32),cv2.FONT_HERSHEY_SIMPLEX,.68,(255,255,255),2)
        cv2.putText(title,'One visual review; ambiguous distant trunks UNKNOWN; second review pending',(12,69),cv2.FONT_HERSHEY_SIMPLEX,.60,(255,255,255),1)
        rendered=np.vstack([title,canvas]);overlay=folder/f'frame-{i:02d}-draft.png';cv2.imwrite(str(overlay),rendered)
        row['annotation_overlay']=str(overlay);result['images'].append(row)
        contact.append(cv2.resize(rendered,(270,505)))
    cv2.imwrite(str(folder/'contact-sheet-draft.png'),np.vstack([np.hstack(contact[:5]),np.hstack(contact[5:])]))
    result['image_count']=len(result['images']);result['annotation_count']=sum(len(r['annotations']) for r in result['images'])
    path=OUT/'riverside-labels-assistant-v1.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(f'{path}: {result["image_count"]} frames, {result["annotation_count"]} draft boxes')

if __name__=='__main__':main()
