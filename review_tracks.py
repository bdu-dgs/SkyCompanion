"""Interpolate explicit visual anchors, retaining provenance and audit sheets."""
import argparse,bisect,json
from pathlib import Path
import cv2,numpy as np
from video_training import ROOT


def box_at(track,frame):
    if not track['start_frame']<=frame<=track['end_frame']:return None
    anchors=sorted(track['anchors'],key=lambda x:x['frame']); ids=[a['frame'] for a in anchors]
    j=bisect.bisect_left(ids,frame)
    if j<len(ids) and ids[j]==frame:return list(anchors[j]['xyxy'])
    if j==0 or j==len(ids):raise ValueError(f"Track {track['id']} lacks endpoint anchors for {frame}")
    a,b=anchors[j-1],anchors[j];t=(frame-a['frame'])/(b['frame']-a['frame'])
    return [x+(y-x)*t for x,y in zip(a['xyxy'],b['xyxy'])]


def main():
    p=argparse.ArgumentParser();p.add_argument('tracks',type=Path);p.add_argument('--start',type=int,required=True);p.add_argument('--end',type=int,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    tracks=json.loads(a.tracks.read_text())['tracks'];rows=[];tiles=[];group_start=a.start
    for frame in range(a.start,a.end+1):
        im=cv2.imread(str(ROOT/f'local_training/wechat-20260926/images/train/frame_{frame:06d}.png'))
        boxes=[]
        for track in tracks:
            xy=box_at(track,frame)
            if xy is None:continue
            x1,y1,x2,y2=xy
            if not 0<=x1<x2<=960 or not 0<=y1<y2<=544:raise ValueError((track['id'],frame,xy))
            boxes.append(dict(label=track['label'],track_id=track['id'],xyxy=xy,
                annotation_source='assistant_visual_track',geometry_source='visual_anchor' if any(k['frame']==frame for k in track['anchors']) else 'linear_interpolation'))
            color=(50,220,100) if track['label']!='tree_trunk' else (0,150,255)
            cv2.rectangle(im,(round(x1),round(y1)),(round(x2),round(y2)),color,2)
        rows.append(dict(frame_id=frame,boxes=boxes))
        tile=cv2.resize(im,(480,272));cv2.rectangle(tile,(0,0),(480,22),(5,10,15),-1)
        cv2.putText(tile,str(frame),(7,17),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
        tiles.append(tile)
        if len(tiles)==16 or frame==a.end:
            tiles+= [np.zeros_like(tile)]*(16-len(tiles))
            sheet=np.concatenate([np.concatenate(tiles[i:i+4],axis=1) for i in range(0,16,4)],axis=0)
            cv2.imwrite(str(a.output/f'frames_{group_start:06d}_{frame:06d}.jpg'),sheet,[cv2.IMWRITE_JPEG_QUALITY,95]);tiles=[];group_start=frame+1
    (a.output/'interpolated.json').write_text(json.dumps(rows))
    print(f'Rendered {len(rows)} frames. Rendering is not review.')


if __name__=='__main__':main()
