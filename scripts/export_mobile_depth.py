#!/usr/bin/env python3
"""Convert the pinned official metric Small depth model; no runtime networking."""
from pathlib import Path
import argparse, hashlib, json, os, sys, subprocess
ROOT = Path(__file__).resolve().parents[1]
os.environ['XFORMERS_DISABLED']='1'
SOURCE_REV='a561b849ebae10a6f5ef49e26c83cbbcd36c71bf'
WEIGHT_REV='c725b8589bdf6ab04072cab74c0467830db80d6d'
WEIGHT_SHA='9203e538d35255c90dda4b7fedb47ff33fe725497bcca3b1e53b3a65ee63f0cb'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--size',type=int,default=392);p.add_argument('--precision',choices=['FP16','Mixed','FP32'],default='FP32');a=p.parse_args()
 source=ROOT/'.skycompanion-live/depth-anything-v2-source';weights=ROOT/'.skycompanion-live/mobile-depth/depth_anything_v2_metric_vkitti_vits.pth'
 assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()==SOURCE_REV
 assert sha(weights)==WEIGHT_SHA
 sys.path.insert(0,str(source/'metric_depth'))
 import torch, numpy as np, coremltools as ct
 from depth_anything_v2.dpt import DepthAnythingV2
 torch.set_num_threads(2);torch.manual_seed(7)
 m=DepthAnythingV2(encoder='vits',features=64,out_channels=[48,96,192,384],max_depth=80).eval()
 m.load_state_dict(torch.load(weights,map_location='cpu',weights_only=True))
 class Wrapped(torch.nn.Module):
  def __init__(self,model):
   super().__init__();self.model=model
   self.register_buffer('mean',torch.tensor([.485,.456,.406]).reshape(1,3,1,1))
   self.register_buffer('std',torch.tensor([.229,.224,.225]).reshape(1,3,1,1))
  def forward(self,x): return self.model((x-self.mean)/self.std)
 wrapper=Wrapped(m).eval();x=torch.rand(1,3,a.size,a.size)
 with torch.no_grad():
  expected=wrapper(x)
  # Fixed input shape permits exact offline positional interpolation, avoiding runtime bicubic ops.
  tokens=torch.zeros(1,(a.size//14)**2+1,m.pretrained.embed_dim)
  pos=m.pretrained.interpolate_pos_encoding(tokens,a.size,a.size).detach()
  m.pretrained.interpolate_pos_encoding=lambda x,w,h: pos
  assert torch.allclose(expected,wrapper(x),atol=1e-5,rtol=1e-5)
  traced=torch.jit.trace(wrapper,x,check_trace=False).eval()
 name=f'SkyMetricDepthSmall_{a.size}_{a.precision}';out=ROOT/'ios/Models'/f'{name}.mlpackage'
 if out.exists(): raise SystemExit('Refusing to overwrite existing model package')
 cm=ct.convert(traced,convert_to='mlprogram',minimum_deployment_target=ct.target.iOS18,
  compute_precision=(ct.precision.FLOAT32 if a.precision=='FP32' else ct.precision.FLOAT16 if a.precision=='FP16' else ct.transform.FP16ComputePrecision(op_selector=lambda op: op.op_type not in {'layer_norm','softmax'})),
  inputs=[ct.ImageType(name='image',shape=x.shape,scale=1/255,color_layout=ct.colorlayout.RGB)],
  outputs=[ct.TensorType(name='depth_meters',dtype=np.float32)])
 cm.short_description='Experimental camera-axis metric depth. Ground-truth validation pending.'
 cm.license='Apache-2.0';cm.save(str(out));spec=cm.get_spec()
 manifest={'schemaVersion':1,'resourceName':name,'inputName':'image','inputSize':a.size,'outputName':'depth_meters',
  'outputShape':list(spec.description.output[0].type.multiArrayType.shape),'sourceRevision':SOURCE_REV,
  'weightsRevision':WEIGHT_REV,'weightsSHA256':WEIGHT_SHA,'sourceURL':'https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-VKITTI-Small',
  'license':'Apache-2.0','maxDepthMeters':80,'measurementReference':'camera_optical_axis','validationState':'unvalidated',
  'preprocessing':'upright selected ROI; centered aspect-preserving square letterbox RGB 124,116,104; CoreImage bilinear; RGB/255 then ImageNet channel mean/std inside model',
  'domain':'outdoor_virtual_kitti_training_not_validated_for_this_camera','sampleIntervalMS':2000,
  'files':{str(f.relative_to(out)):sha(f) for f in sorted(out.rglob('*')) if f.is_file()}}
 (ROOT/'ios/Models/selectedDepthModel.json').write_text(json.dumps(manifest,indent=2)+'\n')
 (ROOT/'ios/Models/DepthModelLicense.txt').write_text((source/'LICENSE').read_text())
 print(json.dumps({'model':str(out),'shape':manifest['outputShape'],'status':'unvalidated'}),flush=True)
if __name__=='__main__':main()
