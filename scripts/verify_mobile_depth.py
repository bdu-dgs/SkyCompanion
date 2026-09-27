#!/usr/bin/env python3
"""Same-input PyTorch/Core ML conversion check. NOT metric-distance accuracy."""
from pathlib import Path
import os,sys,json,time,hashlib
os.environ['XFORMERS_DISABLED']='1'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.skycompanion-live/depth-anything-v2-source/metric_depth'))
import numpy as np, torch, coremltools as ct
from PIL import Image
from depth_anything_v2.dpt import DepthAnythingV2

def main():
 torch.set_num_threads(2)
 m=DepthAnythingV2(encoder='vits',features=64,out_channels=[48,96,192,384],max_depth=80).eval()
 manifest=json.loads((ROOT/'ios/Models/selectedDepthModel.json').read_text())
 weights=ROOT/'.skycompanion-live/mobile-depth/depth_anything_v2_metric_vkitti_vits.pth'
 assert hashlib.sha256(weights.read_bytes()).hexdigest()==manifest['weightsSHA256']
 m.load_state_dict(torch.load(weights,map_location='cpu',weights_only=True))
 cm=ct.models.MLModel(str(ROOT/'ios/Models'/f'{manifest["resourceName"]}.mlpackage'),compute_units=ct.ComputeUnit.CPU_ONLY)
 rows=[]
 for relative in ['backend/data/obstacle_dataset/regression-20260926-v1/context/20260926-012139-3adc44e2/00018789-input.png','samples/local/external-streets-20260926/commons-japan-riverside/frame-02.png']:
  original=Image.open(ROOT/relative).convert('RGB')
  for angle in [0,90]:
   im=original.rotate(angle,expand=True);im.thumbnail((392,392),Image.Resampling.BILINEAR)
   canvas=Image.new('RGB',(392,392),(124,116,104));canvas.paste(im,((392-im.width)//2,(392-im.height)//2))
   x=torch.from_numpy(np.array(canvas).transpose(2,0,1).copy()).float().unsqueeze(0)/255
   x=(x-torch.tensor([.485,.456,.406]).view(1,3,1,1))/torch.tensor([.229,.224,.225]).view(1,3,1,1)
   with torch.no_grad(): reference=m(x).numpy()
   start=time.perf_counter();result=cm.predict({'image':canvas})['depth_meters'];elapsed=(time.perf_counter()-start)*1000
   relative_error=np.abs(result-reference)/np.maximum(.1,reference)
   row={'image':relative,'rotation':angle,'relativeErrorMedian':float(np.median(relative_error)),'relativeErrorP99':float(np.percentile(relative_error,99)), 'maxAbsoluteDeltaMeters':float(np.max(np.abs(result-reference))),'macCPUInferenceMS':elapsed,'finite':bool(np.isfinite(result).all())}
   row['passed']=row['finite'] and row['relativeErrorP99']<.03
   rows.append(row); print(json.dumps(row),flush=True)
 report={'selectedModel':manifest['resourceName'],'scope':'Conversion parity only. Shared PIL input; not Swift preprocessing, phone performance or real distance validation.','cases':rows,'passed':all(r['passed'] for r in rows)}
 out=ROOT/'docs/validation/mobile-2026-09-26/depth-conversion-parity.json';out.write_text(json.dumps(report,indent=2)+'\n')
 if not report['passed']: raise SystemExit(1)
if __name__=='__main__':main()
