"""Render actual checkpoint predictions, with stable colors for every class."""
import argparse
import colorsys
import json
import subprocess
from collections import Counter
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLOWorld
from video_training import ROOT, digest, save


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--result',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--device',default='mps')
    parser.add_argument('--imgsz',type=int,default=640)
    parser.add_argument('--conf',type=float,default=.25)
    parser.add_argument('--batch',type=int,default=8)
    parser.add_argument('--no-audio',action='store_true')
    args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    result=json.loads(args.result.read_text())
    if result['status']!='trained_not_deployed' or result['actual_epochs']!=15:
        raise ValueError('Expected completed epoch15 checkpoint')
    weights=Path(result['weights'])
    if digest(weights)!=result['sha256']:raise ValueError('Checkpoint hash mismatch')
    schema=json.loads((args.result.parent/'schema.json').read_text())['classes']
    names=[c['name'] for c in schema]
    colors=[tuple(round(v*255) for v in colorsys.hsv_to_rgb((i*.61803398875)%1,.68+(i%3)*.12,.98-(i%2)*.12)) for i in range(len(names))]
    assert len(set(colors))==len(names)
    font=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',19)
    small=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',16)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
        'stream=width,height,avg_frame_rate,nb_frames','-of','json',str(args.video)]))['streams'][0]
    width,height=int(probe['width']),int(probe['height']);fps=probe['avg_frame_rate']
    expected=int(probe['nb_frames'])
    torch.set_num_threads(4)
    model=YOLOWorld(str(weights))
    if [model.names[i] for i in range(len(names))]!=names:raise ValueError('Checkpoint/schema name mismatch')
    target=out/'obstacles_colored.mp4'
    command=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24',
        '-s',f'{width}x{height}','-r',fps,'-i','pipe:0']
    command += ['-an'] if args.no_audio else ['-i',str(args.video),'-map','0:v:0','-map','1:a?','-c:a','copy','-shortest']
    command += ['-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(target)]
    encoder=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=(out/'ffmpeg.log').open('w'))
    capture=cv2.VideoCapture(str(args.video));frame_id=0;counts=Counter()
    source_sha=digest(args.video)
    provenance=dict(status='running',source=str(args.video),source_sha256=source_sha,
        checkpoint=str(weights),checkpoint_sha256=result['sha256'],checkpoint_epochs=15,
        confidence=args.conf,iou=.45,imgsz=args.imgsz,rect=False,device=args.device,audio_removed=args.no_audio,
        fps=fps,width=width,height=height,expected_frames=expected,
        training_video_matches=[s.get('video_id') for s in result['dataset_audit']['sources'] if s.get('video_sha256')==source_sha],
        prediction_only=True,uses_ground_truth_boxes=False,test_set_evaluation=False,
        colors={names[i]:dict(zh=schema[i]['zh'],rgb=colors[i]) for i in range(len(names))})
    save(out/'inference.json',provenance)
    try:
        with (out/'predictions.jsonl').open('w') as data:
            while True:
                frames=[]
                for _ in range(args.batch):
                    ok,im=capture.read()
                    if not ok:break
                    if im.shape[:2]!=(height,width):raise ValueError('Unexpected frame dimensions')
                    frames.append(im)
                if not frames:break
                predictions=model.predict(frames,imgsz=args.imgsz,rect=False,conf=args.conf,iou=.45,device=args.device,
                    max_det=300,agnostic_nms=False,verbose=False,save=False)
                for im,pred in zip(frames,predictions):
                    canvas=Image.fromarray(cv2.cvtColor(im,cv2.COLOR_BGR2RGB));draw=ImageDraw.Draw(canvas)
                    boxes=[];label_regions=[]
                    for xy,cls,score in zip(pred.boxes.xyxy.cpu().tolist(),pred.boxes.cls.cpu().tolist(),pred.boxes.conf.cpu().tolist()):
                        cid=int(cls);color=colors[cid];label=names[cid];counts[label]+=1
                        x1,y1,x2,y2=[max(0,min(round(v),width-1 if i%2==0 else height-1)) for i,v in enumerate(xy)]
                        draw.rectangle((x1,y1,x2,y2),outline=color,width=3)
                        title=f"{schema[cid]['zh'].split('（')[0].split('／')[0]} {score:.2f}"
                        bounds=draw.textbbox((0,0),title,font=font);tw=bounds[2]-bounds[0]+8;th=26
                        candidates=[]
                        for lx,ly in ((x1,y1-th),(x1,y1+2),(x2-tw,y1+2),(x1,y1+30),(x1,y2-th),(x1,y2+2)):
                            lx=max(0,min(lx,width-tw));ly=max(0,min(ly,height-th-28))
                            overlap=sum(max(0,min(lx+tw,b)-max(lx,a))*max(0,min(ly+th,d)-max(ly,c)) for a,c,b,d in label_regions)
                            candidates.append((overlap,lx,ly))
                        _,tx,ty=min(candidates,key=lambda item:item[0])
                        label_regions.append((tx,ty,tx+tw,ty+th))
                        draw.rectangle((tx,ty,tx+tw,ty+th),fill=(15,20,25),outline=color,width=2)
                        draw.text((tx+4,ty+3),title,font=font,fill=color)
                        boxes.append(dict(class_id=cid,label=label,confidence=score,xyxy=xy))
                    text=f'YOLOv8s - epoch 15 - predictions >= {args.conf:.2f} | {frame_id/float(Fraction(fps)):.2f}s'
                    draw.rectangle((0,height-27,590,height),fill=(15,20,25))
                    draw.text((9,height-24),text,font=small,fill=(245,245,245))
                    encoder.stdin.write(np.asarray(canvas).tobytes())
                    if frame_id in (0,400,960,1400):canvas.save(out/f'preview_{frame_id:06d}.jpg',quality=94)
                    data.write(json.dumps(dict(frame_id=frame_id,timestamp_s=frame_id/float(Fraction(fps)),boxes=boxes),ensure_ascii=False)+'\n')
                    frame_id+=1
                if frame_id%80==0 or frame_id==expected:print(f'Predicted and rendered {frame_id}/{expected}',flush=True)
        encoder.stdin.close()
        if encoder.wait()!=0:raise RuntimeError('ffmpeg failed; see ffmpeg.log')
        if frame_id!=expected:raise ValueError(f'Frame count mismatch: {frame_id} versus {expected}')
        used=[i for i,n in enumerate(names) if counts[n]]
        legend=Image.new('RGB',(960,70+40*((len(used)+1)//2)),(15,20,25));draw=ImageDraw.Draw(legend)
        draw.text((20,15),'Class color legend (only classes predicted in this video)',font=font,fill='white')
        for j,i in enumerate(used):
            x=20+(j%2)*470;y=65+(j//2)*40
            draw.rectangle((x,y,x+27,y+25),outline=colors[i],width=3)
            draw.text((x+38,y+1),f"{schema[i]['zh']} · {names[i]}",font=small,fill=colors[i])
        legend.save(out/'class_colors.png')
        provenance.update(status='completed',rendered_frames=frame_id,output=str(target),
            output_sha256=digest(target),predictions_by_class=dict(counts))
        save(out/'inference.json',provenance)
        print(json.dumps(dict(status='completed',frames=frame_id,output=str(target),detected_classes=len(counts)),ensure_ascii=False),flush=True)
    except BaseException as exc:
        if encoder.poll() is None:encoder.terminate();encoder.wait()
        provenance.update(status='failed',error=repr(exc),rendered_frames=frame_id)
        save(out/'inference.json',provenance)
        raise
    finally:capture.release()


if __name__=='__main__':main()
