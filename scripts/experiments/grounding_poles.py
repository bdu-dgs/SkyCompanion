"""Offline third-party-weight diagnostic. Never trains on UI screenshots."""
import json,time
from pathlib import Path
import cv2,torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
ROOT=Path(__file__).resolve().parents[2];out=ROOT/'backend/data/obstacle_experiments/grounding';out.mkdir(parents=True,exist_ok=True)
model_id='IDEA-Research/grounding-dino-tiny'
processor=AutoProcessor.from_pretrained(model_id)
model=AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to('mps').eval()
(out/'provenance.json').write_text(json.dumps({'source':model_id,'commit':model.config._commit_hash,'device':'mps'},indent=2))
inputs=[]
for folder in ['20260925-215027-5f22ede2','20260925-215256-ad66dbd3','20260925-215445-9d1990d5']:
 d=ROOT/'backend/data/obstacle_cases'/folder;m=json.loads((d/'manifest.json').read_text());f=m['frames'][len(m['frames'])//2];p=d/f['input_file'];inputs.append((folder,Image.open(p).convert('RGB'),'clean_capture'))
for t in ['9.49.43','9.49.53','9.50.17','9.53.43']:
 p=next(Path('/Users/stanley/Desktop').glob(f'Screenshot 2026-09-25 at {t}*pm.png'))
 im=Image.open(p).convert('RGB');region=(32,356,1344,1093) if t!='9.53.43' else (32,9,1344,746)
 inputs.append((f'screenshot-{t}',im.crop(region).resize((791,443)),'overlay_diagnostic_only'))
p=Path('/var/folders/5b/h8jvf2cj5vs26dcxp6mwdgy00000gn/T/codex-clipboard-7a76fc7d-a57e-48e5-8d85-0e8515ec4e81.png')
inputs.append(('white-column',Image.open(p).convert('RGB').crop((32,9,1344,746)).resize((791,443)),'overlay_diagnostic_only'))
text='a street light pole. a sign post. a support column. a pillar. a street information kiosk. a tree trunk.'
rows=[]
for name,im,kind in inputs:
 data=processor(images=im,text=text,return_tensors='pt').to('mps')
 t=time.perf_counter()
 with torch.inference_mode():r=model(**data)
 torch.mps.synchronize();ms=(time.perf_counter()-t)*1000
 pred=processor.post_process_grounded_object_detection(r,data.input_ids,threshold=.25,text_threshold=.2,target_sizes=[im.size[::-1]])[0]
 boxes=[{'label':label,'confidence':float(score),'xyxy':xyxy.tolist()} for label,score,xyxy in zip(pred['text_labels'],pred['scores'].cpu(),pred['boxes'].cpu())]
 print(name,round(ms,1),boxes,flush=True)
 rows.append({'name':name,'kind':kind,'ms':ms,'boxes':boxes})
 import numpy as np
 preview=cv2.cvtColor(np.array(im),cv2.COLOR_RGB2BGR)
 for b in boxes:
  x1,y1,x2,y2=map(int,b['xyxy']);cv2.rectangle(preview,(x1,y1),(x2,y2),(0,220,255),2);cv2.putText(preview,b['label'],(max(0,x1),max(14,y1-5)),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,220,255),1)
 cv2.imwrite(str(out/(name+'.jpg')),preview)
 (out/'results.json').write_text(json.dumps(rows,indent=2))
