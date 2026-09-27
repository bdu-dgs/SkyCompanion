"""Compare source-frame teacher predictions before producing training labels."""
import json,time
from pathlib import Path
import cv2,torch
from PIL import Image
from transformers import AutoProcessor,AutoModelForZeroShotObjectDetection
from ultralytics import YOLOWorld,YOLOE
from video_training import ROOT,ALIASES,NAMES,save,consolidate

data=ROOT/'local_training/wechat-20260926'
out=data/'teacher_probe_v2';out.mkdir(exist_ok=True)
torch.set_num_threads(4)
cache=str(ROOT / 'backend/data/models/hf-cache/hub')
mid='IDEA-Research/grounding-dino-tiny'
processor=AutoProcessor.from_pretrained(mid,cache_dir=cache,local_files_only=True)
dino=AutoModelForZeroShotObjectDetection.from_pretrained(mid,cache_dir=cache,local_files_only=True).to('mps').eval()
world=YOLOWorld(str(ROOT/'yolov8s-worldv2.pt'))
skycompanion=YOLOE(str(ROOT / 'backend/data/models/skycompanion-yoloe-11l-v4-candidate.pt'))
prompts={'street light pole':'streetlight','utility pole':'utility_pole','traffic light pole':'traffic_light_pole',
 'sign post':'signpost','tree trunk':'tree_trunk','tree':'tree','bollard':'bollard',
 'potted plant':'planter','bench':'bench','railing':'railing','fence':'fence',
 'building column':'column','concrete block':'concrete_block','fire hydrant':'fire_hydrant',
 'trash can':'trash_can','bicycle':'bicycle','street kiosk':'street_kiosk'}
caption='. '.join(prompts)+'.'
rows=[json.loads(s) for s in (data/'frames.jsonl').read_text().splitlines()][::200]
start=time.time();result=[]
for row in rows:
    im=Image.open(row['path']).convert('RGB');boxes=[]
    inp=processor(images=im,text=caption,return_tensors='pt').to('mps')
    t=time.time()
    with torch.inference_mode():pred=dino(**inp)
    det=processor.post_process_grounded_object_detection(pred,inp.input_ids,threshold=.3,text_threshold=.25,target_sizes=[im.size[::-1]])[0]
    elapsed=time.time()-t
    for name,xy,score in zip(det['text_labels'],det['boxes'].cpu().tolist(),det['scores'].cpu().tolist()):
        if name in prompts:boxes.append(dict(label=prompts[name],xyxy=xy,confidence=score,teacher='grounding_dino'))
    for tag,model in [('coco_world',world),('skycompanion_yoloe_11l',skycompanion)]:
        pred=model.predict(row['path'],device='mps',imgsz=960,conf=.25,verbose=False)[0]
        for cls,xy,score in zip(pred.boxes.cls.cpu().tolist(),pred.boxes.xyxy.cpu().tolist(),pred.boxes.conf.cpu().tolist()):
            name=pred.names[int(cls)];name=ALIASES.get(name,name.replace(' ','_'))
            if name in NAMES:boxes.append(dict(label=name,xyxy=xy,confidence=score,teacher=tag))
    boxes=consolidate(boxes);result.append(dict(**row,boxes=boxes))
    canvas=cv2.imread(row['path'])
    for b in boxes:
        x1,y1,x2,y2=map(int,b['xyxy']);color=(30,220,255) if b['teacher']=='grounding_dino' else (0,255,70)
        cv2.rectangle(canvas,(x1,y1),(x2,y2),color,2)
        cv2.putText(canvas,f"{b['label']} {b['confidence']:.2f}",(max(0,x1),max(14,y1)),cv2.FONT_HERSHEY_SIMPLEX,.4,color,1)
    cv2.imwrite(str(out/f"{row['frame_id']:06d}.jpg"),canvas)
    print(row['frame_id'],round(elapsed,2),[(b['label'],round(b['confidence'],2)) for b in boxes],flush=True)
save(out/'predictions.json',result)
save(out/'provenance.json',dict(dino_commit=dino.config._commit_hash,elapsed_s=time.time()-start,caption=caption))
