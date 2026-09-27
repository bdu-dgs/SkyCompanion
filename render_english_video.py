"""Video-only presentation edit. Reuse saved boxes; never load or alter a model."""
import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from video_training import digest, save


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--predictions',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    info=json.loads((args.predictions.parent/'inference.json').read_text())
    if info['status']!='completed':raise ValueError('Wait for the existing predictions to finish')
    rows=[json.loads(s) for s in args.predictions.read_text().splitlines()]
    expected=info['expected_frames']
    if [r['frame_id'] for r in rows]!=list(range(expected)):raise ValueError('Missing predicted frames')
    checkpoint_before=digest(info['checkpoint'])
    if checkpoint_before!=info['checkpoint_sha256']:raise ValueError('Unexpected checkpoint change')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    target=out/'obstacles_english_silent.mp4'
    width,height=info['width'],info['height']
    font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',19)
    small=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',15)
    colors={n:tuple(c['rgb']) for n,c in info['colors'].items()}
    # Match the user's reference style while keeping one stable color per class.
    colors.update(person=(0,230,70),column=(40,70,245),tree=(25,64,153),
        tree_trunk=(255,25,135),planter=(0,218,160),bench=(138,35,255),
        bush=(226,20,181),curb=(0,205,225))
    cap=cv2.VideoCapture(info['source'])
    counts=Counter();box_counts=[];selected=[]
    with (out/'ffmpeg.log').open('w') as err:
        enc=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24',
            '-s',f'{width}x{height}','-r',info['fps'],'-i','pipe:0','-an','-c:v','libx264','-preset','fast',
            '-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],stdin=subprocess.PIPE,stderr=err)
        try:
            for row in rows:
                ok,frame=cap.read()
                if not ok:raise ValueError('Source ended early')
                # The supplied reference uses the existing 0.85 predictions.
                # Cap only unusually crowded frames to preserve similar density.
                boxes=sorted((b for b in row['boxes'] if b['confidence']>=.85),key=lambda b:b['confidence'],reverse=True)[:30]
                box_counts.append(len(boxes));selected.append(dict(row,boxes=boxes))
                canvas=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB));draw=ImageDraw.Draw(canvas)
                for b in boxes:
                    draw.rectangle(tuple(b['xyxy']),outline=colors[b['label']],width=2)
                    counts[b['label']]+=1
                occupied=[]
                for b in boxes:
                    label=f"{b['label']} {b['confidence']:.2f}";color=colors[b['label']]
                    x1,y1,x2,y2=b['xyxy'];tw=draw.textlength(label,font=font)+8;th=25
                    positions=[]
                    for x,y in ((x1,y1-th),(x1,y1+2),(x2-tw,y1+2),(x1,y1+th+2),(x1,y2-th)):
                        x=max(0,min(x,width-tw));y=max(0,min(y,height-th-24))
                        overlap=sum(max(0,min(x+tw,c)-max(x,a))*max(0,min(y+th,d)-max(y,z)) for a,z,c,d in occupied)
                        positions.append((overlap,x,y))
                    _,x,y=min(positions,key=lambda t:t[0]);occupied.append((x,y,x+tw,y+th))
                    draw.rectangle((x,y,x+tw,y+th),fill=color)
                    # Contrast follows color luminance, keeping all labels readable.
                    lum=.2126*color[0]+.7152*color[1]+.0722*color[2]
                    ink=(10,15,20) if lum>140 else (255,255,255)
                    draw.text((x+4,y+2),label,font=font,fill=ink)
                footer=f"YOLOv8s | Epoch 15 | Selected detections | {row['timestamp_s']:.2f}s"
                draw.rectangle((0,height-24,510,height),fill=(16,21,26))
                draw.text((8,height-21),footer,font=small,fill=(240,243,247))
                enc.stdin.write(np.asarray(canvas).tobytes())
                if row['frame_id'] in (0,400,960,1400):canvas.save(out/f"preview_{row['frame_id']:06d}.jpg",quality=94)
                if (row['frame_id']+1)%300==0:print(f"English silent video: {row['frame_id']+1}/{expected}",flush=True)
            if cap.read()[0]:raise ValueError('Source has additional frames')
            enc.stdin.close()
            if enc.wait()!=0:raise RuntimeError('Video encoding failed')
        except BaseException:
            if enc.poll() is None:enc.terminate();enc.wait()
            raise
        finally:cap.release()
    checkpoint_after=digest(info['checkpoint'])
    if checkpoint_after!=checkpoint_before:raise ValueError('Checkpoint changed during presentation edit')
    (out/'displayed_predictions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in selected))
    report=dict(status='completed',output=str(target),source=info['source'],
        source_predictions=str(args.predictions.resolve()),source_predictions_sha256=digest(args.predictions),
        model_unchanged=True,checkpoint_sha256_before=checkpoint_before,checkpoint_sha256_after=checkpoint_after,
        inference_rerun=False,manual_boxes_added=False,labels='English',audio_removed=True,
        confidence_display_filter=.85,max_boxes_per_frame=30,
        actual_boxes_per_frame=dict(min=min(box_counts),max=max(box_counts),mean=sum(box_counts)/len(box_counts)),
        frame_count=len(rows),fps=info['fps'],width=width,height=height,output_sha256=digest(target),
        displayed_class_counts=dict(counts),colors_rgb=colors,
        note='Presentation subset of saved model predictions, matched to user reference density; not full detection coverage or an accuracy evaluation.')
    save(out/'video_edit.json',report)
    print(json.dumps(dict(output=str(target),frames=len(rows),boxes_per_frame=report['actual_boxes_per_frame'])),flush=True)


if __name__=='__main__':main()
