"""Local all-frame annotation and reviewed-training workflow for SkyCompanion.

Keeps source timestamps, raw predictions and annotation provenance. Does not
assert human review, independent validation, or deployment acceptance.
"""
from __future__ import annotations
import argparse
from collections import Counter
import functools
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'street_classes.json').read_text())
CLASSES = SCHEMA['classes']
NAMES = [c['name'] for c in CLASSES]
os.environ.setdefault('YOLO_CONFIG_DIR', str(ROOT / 'local_training' / 'ultralytics'))
os.environ.setdefault('HF_HOME', str(ROOT / 'backend/data/models/hf-cache'))
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    tmp.replace(path)


def clip_cache():
    # Process-local configuration: never change SkyCompanion's environment or library.
    import clip
    clip.load = functools.partial(clip.load, download_root=str(ROOT / 'weights/clip'))


def index_frames(args):
    import cv2
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames',
        '-show_entries', 'frame=best_effort_timestamp_time,width,height', '-of', 'json', str(args.video)]))
    frames = probe['frames']
    paths = sorted((args.data / 'images/train').glob('frame_*.png'))
    if len(paths) != len(frames):
        raise ValueError(f'Decoded {len(paths)} images; expected {len(frames)} source frames')
    source_sha = digest(args.video)
    with (args.data / 'frames.jsonl').open('w') as out:
        for i, (path, source) in enumerate(zip(paths, frames)):
            if path.stem != f'frame_{i:06d}':
                raise ValueError('Missing or unordered frame')
            im = cv2.imread(str(path))
            if im is None or im.shape[:2] != (source['height'], source['width']):
                raise ValueError(f'Invalid image {path}')
            row = dict(frame_id=i, timestamp_s=float(source['best_effort_timestamp_time']),
                       path=str(path.resolve()), width=source['width'], height=source['height'],
                       sha256=digest(path), video_group=source_sha, split='train')
            out.write(json.dumps(row) + '\n')
    save(args.data / 'source.json', dict(video=str(args.video.resolve()), sha256=source_sha,
        frame_count=len(paths), decoded_lossless_png=True, frame_sampling_stride=1,
        repo_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        schema_sha256=digest(ROOT / 'street_classes.json'), use='user_authorized_local_training',
        independent_validation=False, annotation_status='pending'))
    (args.data / 'classes.txt').write_text('\n'.join(NAMES)+'\n')
    print(f'Indexed and checked {len(paths)} frames', flush=True)


ALIASES = {
    'light pole':'streetlight', 'potted plant':'planter', 'tree trunk':'tree_trunk',
    'signpost':'signpost','pillar':'column', 'stone barrier':'concrete_block',
    'concrete block':'concrete_block','concrete barrier':'construction_barrier',
    'traffic light':'traffic_light_unknown','fire hydrant':'fire_hydrant',
    'traffic cone':'traffic_cone','construction barrel':'construction_barrel',
    'construction barrier':'construction_barrier','trash can':'trash_can',
    'boulder':'rock','street kiosk':'street_kiosk','kiosk':'street_kiosk',
    'newsstand':'street_kiosk','news kiosk':'street_kiosk','booth':'street_kiosk',
    'outdoor table':'table','dining table':'table','scaffolding pole':'pole',
}
POLES = {'streetlight','utility_pole','traffic_light_pole','signpost','pole'}


def iou(a, b):
    x1,y1,x2,y2 = a; u1,v1,u2,v2 = b
    inter = max(0,min(x2,u2)-max(x1,u1))*max(0,min(y2,v2)-max(y1,v1))
    union = (x2-x1)*(y2-y1)+(u2-u1)*(v2-v1)-inter
    return inter/union if union>0 else 0.


def consolidate(boxes):
    kept=[]
    for b in sorted(boxes,key=lambda x:x['confidence'],reverse=True):
        if any((b['label']==k['label'] or b['label'] in POLES and k['label'] in POLES)
               and iou(b['xyxy'],k['xyxy'])>.55 for k in kept):
            continue
        kept.append(b)
    return kept


def to_label_line(box, width, height, names=None):
    names = NAMES if names is None else names
    x1,y1,x2,y2=box['xyxy']
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError(f'Invalid box: {box}')
    return f"{names.index(box['label'])} {(x1+x2)/2/width:.7f} {(y1+y2)/2/height:.7f} {(x2-x1)/width:.7f} {(y2-y1)/height:.7f}"


def dataset_names(data):
    """Read the export's own vocabulary; legacy exports retain their 72 IDs."""
    import yaml
    data = Path(data)
    audit = json.loads((data/'dataset_audit.json').read_text())
    schema_path = data/audit['schema_file'] if audit.get('schema_file') else ROOT/'street_classes.json'
    if digest(schema_path) != audit['schema_sha256']:
        raise ValueError('Dataset schema changed after export')
    names = [c['name'] for c in json.loads(schema_path.read_text())['classes']]
    configured = yaml.safe_load((data/'data.yaml').read_text())['names']
    if isinstance(configured, dict):
        if set(configured) != set(range(len(names))):
            raise ValueError('Dataset class IDs must be contiguous')
        configured = [configured[i] for i in range(len(names))]
    if configured != names or len(set(names)) != len(names):
        raise ValueError('Dataset YAML names differ from its schema')
    return names


def annotate(args):
    import cv2
    import torch
    from ultralytics import YOLOE, YOLOWorld
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    from PIL import Image
    torch.set_num_threads(4)
    clip_cache()
    rows=[json.loads(line) for line in (args.data/'frames.jsonl').read_text().splitlines()]
    if args.limit: rows=[rows[round(i*(len(rows)-1)/max(1,args.limit-1))] for i in range(args.limit)]
    label_dir=args.data/('labels_probe' if args.limit else 'labels/train')
    label_dir.mkdir(parents=True,exist_ok=True)
    output=args.data/args.annotation_version
    output.mkdir(exist_ok=True)
    if (output/'annotations.jsonl').exists():
        raise ValueError('Refusing to overwrite prior annotation run')
    world=YOLOWorld(str(ROOT/'yolov8s-worldv2.pt'))
    prompted=[c for c in CLASSES if c['prompt'] is not None]
    # Keep the repository checkpoint's original COCO embeddings. Broad custom
    # prompting was rejected after a real first-frame false-positive audit.
    snapshot=next(Path(os.environ['HF_HOME']).glob('hub/models--IDEA-Research--grounding-dino-tiny/snapshots/*'))
    processor=AutoProcessor.from_pretrained(str(snapshot),local_files_only=True)
    dino=AutoModelForZeroShotObjectDetection.from_pretrained(str(snapshot),local_files_only=True).to(args.device).eval()
    caption=''; spans=[]
    for c in prompted:
        start=len(caption);caption+=c['prompt'];spans.append((start,len(caption)));caption+='. '
    tokenized=processor.tokenizer(caption,return_offsets_mapping=True)
    if len(tokenized['input_ids'])>256:raise ValueError('Grounding prompt exceeds model token capacity')
    tokens_by_class=[[i for i,(a,b) in enumerate(tokenized['offset_mapping']) if b>a and a<end and b>start]
                     for start,end in spans]
    skycompanion_path=(ROOT / 'backend/data/models/skycompanion-yoloe-11l-v4-candidate.pt')
    skycompanion=YOLOE(str(skycompanion_path))
    provenance=dict(status='running', method='independent_per_frame_three_model_predictions_then_class_nms',
        label_status='pseudo_label_unreviewed', human_reviewed=False, all_frames_visual_reviewed=False,
        device=args.device,imgsz=args.imgsz,world_conf=.25,skycompanion_conf=.25,dino_conf=.28,
        grounding_caption=caption,grounding_commit=dino.config._commit_hash,
        grounding_class_assignment='mean probability over exact prompt token span; no decoded phrase dropping',
        teachers=[dict(path=str(p),sha256=digest(p)) for p in [ROOT/'yolov8s-worldv2.pt',skycompanion_path]],
        schema_sha256=digest(ROOT/'street_classes.json'), source_sha256=digest(args.data/'source.json'))
    save(output/'provenance.json',provenance)
    counts=Counter(); empty=[]; start=time.time()
    with (output/'raw_predictions.jsonl').open('w') as raw, (output/'annotations.jsonl').open('w') as out:
        for offset in range(0,len(rows),args.batch):
            chunk=rows[offset:offset+args.batch]
            ims=[cv2.imread(r['path']) for r in chunk]
            predictions=[]
            for model in (world,skycompanion):
                predictions.append(model.predict(ims,imgsz=args.imgsz,device=args.device,conf=.25,
                    iou=.6,max_det=150,verbose=False))
            inp=processor(images=[Image.fromarray(cv2.cvtColor(im,cv2.COLOR_BGR2RGB)) for im in ims],
                text=[caption]*len(ims),return_tensors='pt',padding=True,
                size={'shortest_edge':640,'longest_edge':1067}).to(args.device)
            with torch.inference_mode():grounded=dino(**inp)
            probs=grounded.logits.sigmoid()
            class_scores=torch.stack([probs[:,:,ts].mean(-1) for ts in tokens_by_class],dim=-1)
            gd_scores,gd_classes=class_scores.max(-1)
            gd_scores=gd_scores.cpu().tolist();gd_classes=gd_classes.cpu().tolist();gd_boxes=grounded.pred_boxes.cpu().tolist()
            for j,r in enumerate(chunk):
                boxes=[]; raw_boxes=[]; w,h=r['width'],r['height']
                for teacher,results in zip(('yolo_world','skycompanion_yoloe_11l'),predictions):
                    result=results[j]
                    for xyxy,cls,conf in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.cls.cpu().tolist(),result.boxes.conf.cpu().tolist()):
                        original=result.names[int(cls)]
                        name=ALIASES.get(original,original.replace(' ','_'))
                        raw_boxes.append(dict(label=original,mapped_label=name,confidence=conf,xyxy=xyxy,teacher=teacher))
                        if name not in NAMES: continue
                        x1,y1,x2,y2=xyxy
                        xyxy=[max(0.,x1),max(0.,y1),min(float(w),x2),min(float(h),y2)]
                        if xyxy[2]-xyxy[0]<2 or xyxy[3]-xyxy[1]<2: continue
                        boxes.append(dict(label=name,confidence=conf,xyxy=xyxy,teacher=teacher,
                            truncated=xyxy[0]<2 or xyxy[1]<2 or xyxy[2]>w-2 or xyxy[3]>h-2))
                for cls,conf,coords in zip(gd_classes[j],gd_scores[j],gd_boxes[j]):
                    if conf<.28:continue
                    name=prompted[cls]['name'];cx,cy,bw,bh=coords
                    xyxy=[max(0.,(cx-bw/2)*w),max(0.,(cy-bh/2)*h),min(float(w),(cx+bw/2)*w),min(float(h),(cy+bh/2)*h)]
                    raw_boxes.append(dict(label=name,mapped_label=name,confidence=conf,xyxy=xyxy,teacher='grounding_dino'))
                    if xyxy[2]-xyxy[0]<2 or xyxy[3]-xyxy[1]<2:continue
                    # Pole function is not established by a weak text match.
                    if name in POLES and conf<.45:name='pole'
                    boxes.append(dict(label=name,confidence=conf,xyxy=xyxy,teacher='grounding_dino',
                        truncated=xyxy[0]<2 or xyxy[1]<2 or xyxy[2]>w-2 or xyxy[3]>h-2))
                boxes=consolidate(boxes)
                counts.update(b['label'] for b in boxes)
                if not boxes: empty.append(r['frame_id'])
                raw.write(json.dumps(dict(frame_id=r['frame_id'],boxes=raw_boxes))+'\n')
                out.write(json.dumps(dict(**r,boxes=boxes,annotation_status='pseudo_label_unreviewed',
                    human_reviewed=False,coverage='unknown',verified_negative=False))+'\n')
                (label_dir/(Path(r['path']).stem+'.txt')).write_text('\n'.join(to_label_line(b,w,h) for b in boxes)+'\n')
            if offset%80==0 or offset+len(chunk)==len(rows):
                progress=dict(processed=offset+len(chunk),total=len(rows),elapsed_s=round(time.time()-start,1),boxes=sum(counts.values()))
                save(output/'progress.json',progress); print(json.dumps(progress),flush=True)
    provenance.update(status='complete',frame_count=len(rows),box_count=sum(counts.values()),
        counts=dict(counts),zero_prediction_classes=[n for n in NAMES if not counts[n]],
        empty_prediction_frame_ids=empty,elapsed_s=round(time.time()-start,1))
    save(output/'provenance.json',provenance)
    print(json.dumps(provenance,ensure_ascii=False),flush=True)


def export_dataset(args):
    from assemble_reviewed_dataset import assemble
    assemble(args.data)


def train(args):
    import torch
    from ultralytics import YOLOWorld
    from reviewed_loss import ReviewedWorldTrainer
    clip_cache(); torch.set_num_threads(4)
    if (args.data/(args.name+'_result.json')).exists():
        raise ValueError('Training run name already exists; choose a new --name to preserve its evidence')
    audit=json.loads((args.data/'dataset_audit.json').read_text())
    if audit.get('training_mode')!='assistant_reviewed_partial_labels_with_ignored_unknowns':
        raise ValueError('Raw pseudo labels are not authorized as final training annotations; complete the visual review stage first')
    if audit['annotation_sha256']!=digest(args.data/'annotations.jsonl'):
        raise ValueError('Annotations changed after audit')
    names=dataset_names(args.data)
    resume_checkpoint=getattr(args,'resume_checkpoint',None)
    if resume_checkpoint and getattr(args,'weights',None):
        raise ValueError('Choose true resume or weight initialization, not both')
    initial_weights=Path(resume_checkpoint or getattr(args,'weights',None) or ROOT/'yolov8s-worldv2.pt').resolve()
    checks={'training_review_sha256':args.data/'training_review.json',
            'labels_manifest_sha256':args.data/'labels_manifest.json',
            'data_yaml_sha256':args.data/'data.yaml'}
    for key,path in checks.items():
        if audit.get(key)!=digest(path):raise ValueError(f'Dataset changed or unaudited: {path}')
    for record in json.loads((args.data/'labels_manifest.json').read_text()):
        path=args.data/record['path']
        if digest(path)!=record['sha256']:raise ValueError(f'Label changed after review: {path}')
    project=args.data/'runs'
    config=dict(data=str(args.data/'data.yaml'),epochs=args.epochs,imgsz=args.imgsz,batch=args.batch,
        device=args.device,workers=0,project=str(project),name=args.name,exist_ok=False,
        optimizer='AdamW',lr0=.0003,weight_decay=.0005,patience=0,seed=20260926,
        mosaic=0.,scale=0.,translate=0.,fliplr=0.,close_mosaic=0,amp=False,cache=False,
        freeze=10,plots=False,save_period=5,val=False)
    if resume_checkpoint:config['resume']=str(initial_weights)
    provenance=dict(status='running',training_mode='assistant_reviewed_partial_labels_with_ignored_unknowns',
        independent_validation=False,test_set_executed=False,run_test_after_training=False,
        deployed=False,config=config,dataset_audit=audit,class_names=names,
        mps_assignment='Detached TAL target assignment on CPU; model forward/backward remains on MPS.',
        training_code_sha256={name:digest(ROOT/name) for name in ('video_training.py','reviewed_loss.py')},
        initial_weights=str(initial_weights),initial_weights_sha256=digest(initial_weights),
        continuation_mode='restore_epoch_optimizer_and_ema' if resume_checkpoint else 'weight_initialization',
        selection='Fixed final epoch (last.pt); no independent validation or mAP claim.')
    save(args.data/(args.name+'_result.json'),provenance)
    try:
        model=YOLOWorld(str(initial_weights))
        if (resume_checkpoint or getattr(args,'weights',None)) and [model.names[i] for i in range(len(model.names))]!=names:
            raise ValueError('Warm-start checkpoint vocabulary differs from this dataset')
        model.train(trainer=ReviewedWorldTrainer,**config)
        last=Path(model.trainer.save_dir)/'weights/last.pt'
        candidate=args.data/(args.name+'_candidate.pt')
        # Preserve the checkpoint's canonical vocabulary and saved text features.
        import shutil
        shutil.copy2(last,candidate)
        provenance.update(status='trained_not_deployed',weights=str(candidate),sha256=digest(candidate),
            actual_epochs=model.trainer.epoch+1,run_dir=str(model.trainer.save_dir))
        save(args.data/(args.name+'_result.json'),provenance)
    except KeyboardInterrupt:
        provenance.update(status='interrupted',error='Training interrupted; saved checkpoints retained.')
        save(args.data/(args.name+'_result.json'),provenance)
        raise
    except Exception as exc:
        provenance.update(status='failed',error=repr(exc));save(args.data/(args.name+'_result.json'),provenance)
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['index','annotate','export','train'])
    p.add_argument('--data',type=Path)
    p.add_argument('--video',type=Path)
    p.add_argument('--weights',type=Path,help='Optional reviewed checkpoint initialization; a new run, not optimizer resume')
    p.add_argument('--resume-checkpoint',type=Path,help='Restore saved epoch, optimizer and EMA; --epochs is total, not additional')
    p.add_argument('--device',default='mps')
    p.add_argument('--imgsz',type=int,default=960)
    p.add_argument('--batch',type=int,default=8)
    p.add_argument('--limit',type=int,default=0)
    p.add_argument('--annotation-version',default='annotation_v2')
    p.add_argument('--epochs',type=int,default=15)
    p.add_argument('--name',default='all_frames_v1')
    args=p.parse_args()
    if args.data is None:
        active=ROOT/'active_training.json'
        args.data=(Path(json.loads(active.read_text())['dataset'])
            if args.stage=='train' and active.exists() else ROOT/'local_training/wechat-20260926')
    args.data=args.data.resolve()
    {'index':index_frames,'annotate':annotate,'export':export_dataset,'train':train}[args.stage](args)


if __name__=='__main__':main()
