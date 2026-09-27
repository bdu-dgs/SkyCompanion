"""Generate separate, explicitly unreviewed candidates for each new source."""
import json,traceback
from pathlib import Path
from types import SimpleNamespace
from video_training import ROOT,annotate,save


def main():
    folder=ROOT/'local_training/collection_20260926'
    records=json.loads((folder/'collection.json').read_text())['new_videos']
    records.sort(key=lambda r:r['expected_frames'])
    completed=[]
    try:
        for record in records:
            data=Path(record['data_path'])
            save(folder/'annotation_queue_progress.json',dict(stage='generating_unreviewed_candidates',
                current_video=record['video_id'],current_data=str(data),completed=completed))
            annotate(SimpleNamespace(data=data,device='mps',imgsz=960,batch=4,limit=0,annotation_version='annotation_v2'))
            completed.append(record['video_id'])
        save(folder/'annotation_queue_progress.json',dict(stage='candidate_generation_complete_not_visual_review',completed=completed))
    except Exception as exc:
        save(folder/'annotation_queue_progress.json',dict(stage='failed',completed=completed,error=repr(exc)))
        raise


if __name__=='__main__':main()
