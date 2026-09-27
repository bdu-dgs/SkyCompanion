"""Measure recall on reviewed training positives; this is not held-out accuracy."""
import argparse,json
from collections import Counter
from pathlib import Path
from ultralytics import YOLOWorld
from video_training import dataset_names,digest,iou,save


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,required=True)
    p.add_argument('--weights',type=Path,required=True)
    p.add_argument('--device',default='mps')
    p.add_argument('--batch',type=int,default=8)
    p.add_argument('--imgsz',type=int,default=640)
    p.add_argument('--conf',type=float,default=.25)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    out=args.output or args.data/(args.weights.stem+'_fit_check');out.mkdir(exist_ok=False)
    rows=[json.loads(s) for s in (args.data/'annotations.jsonl').read_text().splitlines()]
    model=YOLOWorld(str(args.weights))
    if [model.names[i] for i in range(len(model.names))]!=dataset_names(args.data):
        raise ValueError('Checkpoint class names differ from reviewed schema')
    gt_count=Counter();hits=Counter();false_negatives=[];negative_violations=[]
    with (out/'predictions.jsonl').open('w') as f:
        for start in range(0,len(rows),args.batch):
            chunk=rows[start:start+args.batch]
            predictions=model.predict([r['path'] for r in chunk],device=args.device,imgsz=args.imgsz,
                conf=args.conf,verbose=False,agnostic_nms=False)
            for row,result in zip(chunk,predictions):
                predicted=[dict(label=model.names[int(c)],xyxy=xy,confidence=float(score))
                    for c,xy,score in zip(result.boxes.cls.tolist(),result.boxes.xyxy.tolist(),result.boxes.conf.tolist())]
                available=set(range(len(predicted)))
                for target in row['boxes']:
                    name=target['label'];gt_count[name]+=1
                    matches=[(iou(target['xyxy'],predicted[j]['xyxy']),j) for j in available if predicted[j]['label']==name]
                    best=max(matches,default=(0,None))
                    if best[0]>=.5:hits[name]+=1;available.remove(best[1])
                    else:false_negatives.append(dict(sample_id=row.get('sample_id'),video_id=row.get('video_id'),frame_id=row['frame_id'],label=name,xyxy=target['xyxy'],best_iou=best[0]))
                for b in predicted:
                    x1,y1,x2,y2=b['xyxy'];cx=(x1+x2)/2;cy=(y1+y2)/2
                    for region in row['explicit_negative_regions']:
                        a,c,d,e=region['xyxy']
                        if b['label'] in region['classes'] and a<=cx<=d and c<=cy<=e:
                            negative_violations.append(dict(sample_id=row.get('sample_id'),video_id=row.get('video_id'),frame_id=row['frame_id'],prediction=b,reason=region['reason']))
                f.write(json.dumps(dict(sample_id=row.get('sample_id'),video_id=row.get('video_id'),frame_id=row['frame_id'],path=row['path'],timestamp_s=row['timestamp_s'],
                    boxes=predicted,annotation_status='MODEL_PREDICTIONS_NOT_LABELS'))+'\n')
            if start%200==0:print(f'Fit check {start+len(chunk)}/{len(rows)}',flush=True)
    summary=dict(scope='Reviewed positives in the same training videos; NOT independent validation, precision, or safety acceptance.',
        weights_sha256=digest(args.weights),annotations_sha256=digest(args.data/'annotations.jsonl'),
        frame_count=len(rows),confidence=args.conf,match_iou=.5,
        reviewed_positive_count=sum(gt_count.values()),matched_count=sum(hits.values()),
        per_class={name:dict(reviewed_instances=n,matched=hits[name],training_positive_recall=hits[name]/n) for name,n in gt_count.items()},
        explicit_negative_violation_count=len(negative_violations),false_negative_count=len(false_negatives),
        unreviewed_prediction_status='Not counted as false positives: annotations remain partial.')
    save(out/'metrics.json',summary);save(out/'missed_reviewed_objects.json',false_negatives)
    save(out/'explicit_negative_violations.json',negative_violations)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
