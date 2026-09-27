#!/usr/bin/env python3
"""Create a local, self-contained annotation reviewer; no network uploads."""
import argparse
import base64
import json
from pathlib import Path

TEMPLATE = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SkyCompanion Obstacle sample annotation</title><style>
body{background:#10161d;color:#e2eaf1;font:16px system-ui;margin:24px}main{max-width:1050px;margin:auto}h1{font-size:26px}
button,select,input{font:inherit;padding:8px;margin:4px;background:#233343;color:inherit;border:1px solid #527086;border-radius:6px}
canvas{width:100%;background:#000;touch-action:none}#coverage{display:flex;flex-wrap:wrap;gap:8px}label{font-size:14px}p{color:#bbcad9;line-height:1.6}
.box{padding:16px;border:1px solid #334554;border-radius:12px;margin:16px 0}#boxes button{padding:3px 8px}#count{margin:12px}
</style><main><h1>SkyCompanion Obstacle sample annotation</h1><p>Add boxes against the original image; mark a class complete only after checking every instance. Predictions do not automatically become ground truth. Annotations exist only in this page memory. Download before leaving, then use Load annotations to restore them.</p>
<div><button id="prev">Previous image</button><strong id="count"></strong><button id="next">Next image</button><button id="save">Download annotation JSON</button><label>Load annotations <input id="load" type="file" accept="application/json"></label></div>
<div class="box"><div id="meta"></div><label>Box class <select id="label"></select></label><label>Cross-frame object ID <input id="track" placeholder="Optional; required for first-appearance evaluation"></label><p>Drag on the image to add a box around the visible part. Use the same object ID for the same entity within a clip.</p><label><input type="checkbox" id="truncated">Truncated at the top or edge</label><label><input type="checkbox" id="occluded">Occluded</label><label><input type="checkbox" id="near">Near in the image (not a metric distance)</label><canvas id="canvas"></canvas><div id="boxes"></div></div>
<div class="box"><strong>Classes fully reviewed in this image</strong><p>When checked, unboxed areas count as background for that class. Leave unchecked when uncertain. Training export is allowed only after all training classes and image instances have been manually reviewed.</p><div id="coverage"></div><label><input type="checkbox" id="verified">I have manually reviewed the checked classes and boxes in this image</label></div>
<p id="notice" role="status"></p></main><script type="application/json" id="payload">__PAYLOAD__</script><script>
let {dataset,images}=JSON.parse(document.getElementById('payload').textContent),index=0,start=null;
const el=id=>document.getElementById(id),canvas=el('canvas'),ctx=canvas.getContext('2d'),photo=new Image();
const current=()=>dataset.images[index];
function status(t){el('notice').textContent=t}
function paint(){canvas.width=photo.naturalWidth;canvas.height=photo.naturalHeight;ctx.drawImage(photo,0,0);ctx.strokeStyle='#ffd16b';ctx.fillStyle='#ffd16b';ctx.lineWidth=2;ctx.font='15px sans-serif';for(const b of current().annotations){ctx.strokeRect(b.x*canvas.width,b.y*canvas.height,b.w*canvas.width,b.h*canvas.height);ctx.fillText(b.label,b.x*canvas.width,Math.max(16,b.y*canvas.height-4));}}
function render(){const im=current();el('count').textContent=`${index+1} / ${dataset.images.length}`;el('meta').textContent=`${im.id} · ${im.video_group} · ${im.split}`;photo.src=images[im.id];el('verified').checked=im.review_status==='human_verified';el('boxes').replaceChildren();for(const [i,b]of im.annotations.entries()){const line=document.createElement('div');line.textContent=`${b.label} ${b.track_id||''} ${b.attributes ? JSON.stringify(b.attributes) : ''} `;const del=document.createElement('button');del.textContent='Delete';del.onclick=()=>{im.annotations.splice(i,1);im.review_status='unreviewed';render();paint()};line.append(del);el('boxes').append(line)}el('coverage').replaceChildren();for(const c of dataset.classes){const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=(im.reviewed_classes||[]).includes(c);input.onchange=()=>{im.reviewed_classes=input.checked?[...im.reviewed_classes,c]:im.reviewed_classes.filter(k=>k!==c);im.review_status='unreviewed';el('verified').checked=false};label.append(input,document.createTextNode(c));el('coverage').append(label)}}
photo.onload=paint;
for(const c of dataset.classes){const o=document.createElement('option');o.value=c;o.textContent=c;el('label').append(o)}
function pos(e){const r=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))]}
canvas.onpointerdown=e=>{start=pos(e);canvas.setPointerCapture(e.pointerId)};
canvas.onpointerup=e=>{if(!start)return;const end=pos(e),x=Math.min(start[0],end[0]),y=Math.min(start[1],end[1]),w=Math.abs(end[0]-start[0]),h=Math.abs(end[1]-start[1]);start=null;if(w<.003||h<.003)return;current().annotations.push({label:el('label').value,x,y,w,h,attributes:{truncated:el('truncated').checked,occluded:el('occluded').checked,near_in_image:el('near').checked,metric_distance_m:null},...(el('track').value?{track_id:el('track').value}:{})});current().review_status='unreviewed';render();paint()};
canvas.onpointercancel=()=>start=null;
el('prev').onclick=()=>{index=Math.max(0,index-1);render()};el('next').onclick=()=>{index=Math.min(dataset.images.length-1,index+1);render()};
el('verified').onchange=()=>current().review_status=el('verified').checked?'human_verified':'unreviewed';
el('save').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(dataset,null,2)],{type:'application/json'}));a.download='skycompanion-obstacle-labels.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);status('Annotation download requested; keep the original image directory.')};
el('load').onchange=async e=>{try{const d=JSON.parse(await e.target.files[0].text());if(!d.images.every(im=>images[im.id])||JSON.stringify(d.classes)!==JSON.stringify(dataset.classes))throw Error('Image or class version mismatch');dataset=d;index=0;render();status('Annotations loaded')}catch(e){status('Failed to load: '+e.message)}};
render();
</script></html>'''


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('dataset',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    data=json.loads(a.dataset.read_text())
    images={im['id']:'data:image/png;base64,'+base64.b64encode(Path(im['path']).read_bytes()).decode() for im in data['images']}
    payload=json.dumps({'dataset':data,'images':images},ensure_ascii=False).replace('<','\\u003c')
    a.output.write_text(TEMPLATE.replace('__PAYLOAD__',payload))
    print(a.output.resolve())
