"""Build local, source-linked visual review artifacts without modifying images."""
from __future__ import annotations
import argparse,json,os
from collections import defaultdict
from statistics import median
from pathlib import Path
import cv2
from video_training import CLASSES,NAMES,ROOT


def render(row):
    im=cv2.imread(row['path'])
    if im is None:raise ValueError(row['path'])
    for b in row['boxes']:
        color=(55,220,75) if row.get('annotation_status')=='assistant_reviewed_partial' or b.get('annotation_source')=='assistant_visual_track' else (30,185,255)
        x1,y1,x2,y2=map(round,b['xyxy'])
        cv2.rectangle(im,(x1,y1),(x2,y2),color,2)
        cv2.putText(im,b['label'],(max(0,x1),max(38,y1-3)),cv2.FONT_HERSHEY_SIMPLEX,.42,color,1,cv2.LINE_AA)
    cv2.rectangle(im,(0,0),(im.shape[1],29),(15,20,25),-1)
    cv2.putText(im,f"Frame {row['frame_id']:04d} / {row['timestamp_s']:.2f}s | {row.get('annotation_status','DRAFT')}",
        (8,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1,cv2.LINE_AA)
    return im


def main():
    p=argparse.ArgumentParser();p.add_argument('annotations',type=Path);p.add_argument('--video',action='store_true')
    args=p.parse_args();rows=[json.loads(s) for s in args.annotations.read_text().splitlines()]
    out=args.annotations.parent
    schema=out/'schema.json'
    classes=json.loads(schema.read_text())['classes'] if schema.exists() else CLASSES
    compact=[]
    for r in rows:
        compact.append(dict(frame_id=r['frame_id'],video_id=r.get('video_id') or 'video01',sample_id=r.get('sample_id',Path(r['path']).stem),timestamp_s=r['timestamp_s'],
            image=os.path.relpath(r['path'],out),boxes=r['boxes'],
            status=r.get('annotation_status','draft'),unknown_regions=r.get('unknown_regions',[]),
            uncertainties=r.get('uncertainties',[]),notes=r.get('review_notes'),
            all_instances_verified=r.get('all_instances_verified',False)))
    (out/'review-data.js').write_text('const frames='+json.dumps(compact,ensure_ascii=False)+';\nconst classes='+json.dumps(classes,ensure_ascii=False)+';')
    (out/'review.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><title>SkyCompanion Frame-by-frame annotation review</title>
<style>body{margin:24px;background:#10171e;color:#edf4f9;font:15px system-ui}main{max-width:1280px;margin:auto}header{display:flex;align-items:center;gap:20px}h1{font-size:24px}button,select,input{font:inherit}button,select{background:#263846;color:white;border:1px solid #547183;padding:8px;border-radius:5px}button{cursor:pointer}canvas{display:block;max-width:100%;height:auto;margin:18px 0;border:1px solid #536977}#range{width:100%}#warning{color:#ffce75;line-height:1.6}#meta{font-variant-numeric:tabular-nums}ul{columns:2}small{color:#b9c8d4}</style>
<main><header><h1>Street obstacles - frame-by-frame review</h1><span id="meta"></span></header>
<p id="warning">Green boxes are annotations visually reviewed by the assistant, including corrected tracks; yellow boxes are unconfirmed candidates. Viewing every original frame does not mean all instances have been annotated. Unconfirmed distant, occluded and small objects remain recorded separately.</p>
<label>Video <select id="clip"></select></label> <button id="prev">← Previous frame</button> <button id="next">Next frame →</button> <button id="play">Play</button>
<label> Jump to frame <input id="jump" type="number" min="0" value="0" style="width:90px"></label>
<select id="filter"><option value="">All classes</option></select><label> <input id="boxes" type="checkbox" checked>Show annotations</label><label> <input id="regions" type="checkbox">Show unconfirmed regions</label>
<input id="range" type="range" min="0" value="0"><canvas id="canvas" width="960" height="544"></canvas>
<p id="status"></p><p id="unknown"></p><ul id="legend"></ul><small>Use Left / Right to step through frames; Home / End jumps to the first or last frame. Original images contain no boxes; overlays appear only on this page.</small></main>
<script src="review-data.js"></script><script>
const $=s=>document.querySelector(s),canvas=$('#canvas'),ctx=canvas.getContext('2d');let index=0,timer=null,token=0,active=frames;
const names=Object.fromEntries(classes.map(c=>[c.name,c.zh]));
classes.forEach(c=>{const o=document.createElement('option');o.value=c.name;o.textContent=c.zh;$('#filter').append(o)});
for(const id of [...new Set(frames.map(r=>r.video_id))]){const o=document.createElement('option');o.value=id;o.textContent=id;$('#clip').append(o)}
function selectClip(){active=frames.filter(r=>r.video_id===$('#clip').value);index=0;$('#range').max=active.length-1;$('#jump').max=active.at(-1).frame_id;draw()}
$('#clip').onchange=selectClip;
function draw(){const t=++token,r=active[index];$('#range').value=index;$('#jump').value=r.frame_id;
$('#meta').textContent=`${index+1} / ${active.length} · Original frame ${r.frame_id} · ${r.timestamp_s.toFixed(2)} seconds`;
$('#status').textContent='Status: '+r.status+' · Annotated objects: '+r.boxes.length+' objects · All instances verified: '+(r.all_instances_verified?'yes':'no');
$('#unknown').textContent='Regions awaiting review: '+r.unknown_regions.map(x=>x.reason).join('; ');
const im=new Image;im.onload=()=>{if(t!==token)return;canvas.width=im.naturalWidth;canvas.height=im.naturalHeight;ctx.drawImage(im,0,0);$('#legend').replaceChildren();
if($('#regions').checked){for(const u of r.unknown_regions){const [x,y,x2,y2]=u.xyxy;ctx.fillStyle='#6cabed33';ctx.fillRect(x,y,x2-x,y2-y);ctx.strokeStyle='#6cabed';ctx.setLineDash([6,4]);ctx.strokeRect(x,y,x2-x,y2-y)}ctx.setLineDash([])}
for(const b of r.boxes){if($('#filter').value&&b.label!==$('#filter').value)continue;const color=r.status==='assistant_reviewed_partial'||b.annotation_source==='assistant_visual_track'?'#37dc4b':'#ffb91e';
if($('#boxes').checked){const [x,y,x2,y2]=b.xyxy;ctx.strokeStyle=color;ctx.lineWidth=2;ctx.strokeRect(x,y,x2-x,y2-y);ctx.font='14px system-ui';ctx.fillStyle=color;ctx.fillText(names[b.label]||b.label,Math.max(0,x),Math.max(15,y-3))}
const li=document.createElement('li');li.style.color=color;li.textContent=(names[b.label]||b.label)+' · '+(r.status==='assistant_reviewed_partial'?'Visually reviewed':b.annotation_source||b.teacher||'Candidate');$('#legend').append(li)}};im.src=r.image}
function move(n){index=Math.max(0,Math.min(active.length-1,n));draw()}
$('#prev').onclick=()=>move(index-1);$('#next').onclick=()=>move(index+1);$('#range').oninput=e=>move(+e.target.value);
$('#jump').onchange=e=>{const n=active.findIndex(r=>r.frame_id>=+e.target.value);move(n<0?active.length-1:n)};
$('#filter').onchange=draw;$('#boxes').onchange=draw;$('#regions').onchange=draw;
$('#play').onclick=()=>{if(timer){clearInterval(timer);timer=null;$('#play').textContent='Play'}else{timer=setInterval(()=>{if(index===active.length-1){clearInterval(timer);timer=null;$('#play').textContent='Play'}else move(index+1)},100);$('#play').textContent='Pause'}};
document.onkeydown=e=>{if(['INPUT','SELECT'].includes(e.target.tagName))return;if(e.key==='ArrowLeft')move(index-1);if(e.key==='ArrowRight')move(index+1);if(e.key==='Home')move(0);if(e.key==='End')move(active.length-1)};selectClip();
</script></html>''')
    groups=defaultdict(list)
    for r in rows:groups[r.get('video_id') or 'video01'].append(r)
    for vid,group in groups.items():
        for r in group[::200]:cv2.imwrite(str(out/f"preview_{vid}_{r['frame_id']:06d}.jpg"),render(r))
        if args.video:
            import subprocess
            width,height=group[0]['width'],group[0]['height']
            if any((r['width'],r['height'])!=(width,height) for r in group):raise ValueError('Mixed dimensions inside one video')
            deltas=[b['timestamp_s']-a['timestamp_s'] for a,b in zip(group,group[1:])]
            fps=round(1/median(deltas),3) if deltas else 1
            path=out/f'annotated_{vid}.mp4'
            proc=subprocess.Popen(['ffmpeg','-y','-hide_banner','-loglevel','error','-f','rawvideo','-pix_fmt','bgr24',
                '-s',f'{width}x{height}','-r',str(fps),'-i','-','-an','-c:v','libx264','-preset','veryfast','-crf','20',
                '-pix_fmt','yuv420p','-movflags','+faststart',str(path)],stdin=subprocess.PIPE)
            try:
                for r in group:proc.stdin.write(render(r).tobytes())
            finally:proc.stdin.close()
            if proc.wait()!=0:raise RuntimeError('Video rendering failed')
    print(out/'review.html')


if __name__=='__main__':main()
