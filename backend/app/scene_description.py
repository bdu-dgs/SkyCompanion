"""Bounded, camera-relative scene summaries, independent of collision warnings."""
from .obstacle_attention import prioritize_obstacles
from .obstacle_risk import iou, valid_box

KINDS = {'person':'person', 'car':'car', 'bicycle':'bicycle', 'motorcycle':'motorcycle',
         'bus':'bus', 'truck':'truck', 'traffic light':'traffic_light', 'chair':'chair',
         'bench':'bench', 'dining table':'table', 'table':'table', 'dog':'dog', 'potted plant':'plant'}
STRUCTURES = {'pole', 'light pole', 'tree trunk', 'fence', 'railing', 'construction barrier',
              'traffic cone', 'construction barrel', 'bollard', 'stone block', 'stone barrier',
              'rock', 'boulder', 'kiosk', 'newsstand', 'stairs', 'curb', 'pothole'}

class SceneDescription:
    def __init__(self): self.reset()
    def reset(self):
        self.tracks = []; self.updated_at = None; self.objects = []
    def update(self, boxes, now):
        if self.updated_at is not None and now <= self.updated_at:
            if now == self.updated_at: return
            self.reset()
        candidates = []
        for b in boxes:
            if not valid_box(b): continue
            threshold = .4 if b['label'] == 'traffic light' else .5
            if b['confidence'] < threshold: continue
            kind = KINDS.get(b['label'])
            if kind is None and b['label'] in STRUCTURES: kind = 'obstacle'
            if kind is not None: candidates.append({**b, 'kind':kind})
        old = [t for t in self.tracks if now-t['last'] <= .6]
        used = set(); tracks = []
        for box in sorted(candidates, key=lambda b:b['confidence'], reverse=True)[:64]:
            matches = [(iou(t['box'],box),i) for i,t in enumerate(old)
                       if i not in used and t['box']['kind']==box['kind']]
            score,index = max(matches, default=(0,None))
            if score >= .2:
                used.add(index); t = old[index]
                tracks.append({'box':box,'first':t['first'],'last':now,'n':t['n']+1})
            else:
                tracks.append({'box':box,'first':now,'last':now,'n':1})
        self.tracks = tracks; self.updated_at = now
        groups = {}
        for t in tracks:
            if t['n'] < 3 or now-t['first'] < .3: continue
            box=t['box']; cx=box['x']+box['w']/2; cy=box['y']+box['h']/2
            direction='left' if cx<.4 else 'right' if cx>.6 else 'ahead'
            attention=prioritize_obstacles([box])[0]['attention']
            if box['kind']=='obstacle' and not attention['near']: continue
            key=(box['kind'],direction)
            rank=attention['score'] + (.5 if attention['near'] else 0)
            value=groups.setdefault(key, {'kind':box['kind'],'direction':direction,'count':0,
                                         'vertical':'upper' if cy<.35 else 'lower' if cy>.7 else 'middle','rank':rank})
            value['count']=min(3,value['count']+1); value['rank']=max(value['rank'],rank)
        ordered=sorted(groups.values(),key=lambda g:g['rank'],reverse=True)
        chosen=[]; kinds=set()
        # Prefer coverage of distinct visible kinds over describing people three times.
        for value in ordered:
            if value['kind'] not in kinds:
                chosen.append(value); kinds.add(value['kind'])
            if len(chosen)==3: break
        self.objects=[{k:v for k,v in g.items() if k!='rank'} for g in chosen]
    def describe(self, now):
        if self.updated_at is None or not 0 <= now-self.updated_at < 1.5:
            return {'code':'vision_unavailable','direction':'ahead'}
        if not self.objects:
            return {'code':'no_stable_objects','objects':[]}
        return {'code':'scene_summary','objects':[dict(o) for o in self.objects]}
