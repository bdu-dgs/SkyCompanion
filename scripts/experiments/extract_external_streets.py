#!/usr/bin/env python3
"""Extract a bounded, provenance-preserving review queue from two licensed local videos."""
import hashlib
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'samples/local/external-streets-20260926'
SOURCES=[
    dict(id='commons-shibuya-crossing',file='shibuya-crossing-original.ogv',city='Tokyo',country='Japan',
         source_page='https://commons.wikimedia.org/wiki/File:Shibuya_Crossing.ogv',
         original_download_url='https://upload.wikimedia.org/wikipedia/commons/f/f5/Shibuya_Crossing.ogv',
         title='Shibuya Crossing',author='Emran Kassim',license='CC BY 2.0',
         license_url='https://creativecommons.org/licenses/by/2.0/',
         location_group='tokyo-shibuya-crossing',times=list(range(5,78,8)),
         license_evidence='Commons file page lists CC BY 2.0 and Flickr license review on 2009-12-22.',
         scene_note='Elevated stationary night crossing view; not first-person walking or suitable for near-obstacle acceptance.'),
    dict(id='commons-japan-riverside',file='japan-riverside-original.webm',city=None,country='Japan',
         source_page='https://commons.wikimedia.org/wiki/File:Walking_along_a_rural_riverside_path_in_Japan_June2025.webm',
         original_download_url='https://upload.wikimedia.org/wikipedia/commons/e/e2/Walking_along_a_rural_riverside_path_in_Japan_June2025.webm',
         title='Walking along a rural riverside path in Japan June2025',author='Shironsilentpond',license='CC BY 4.0',
         license_url='https://creativecommons.org/licenses/by/4.0/',
         location_group='japan-rural-riverside-shironsilentpond-2025',times=list(range(1,29,3)),
         license_evidence='Commons file page identifies own work and author-published CC BY 4.0.',
         scene_note='Rural walking path; city not stated by creator. Do not label this as a second verified city.')]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest={'schema_version':1,'created_date':'2026-09-26','status':'downloaded_frames_pending_annotation',
              'frozen_dataset_modified':False,'current_hot_training_included':False,'sources':[],
              'split_policy':'Whole source video and location groups kept together. No neighbor-frame split. All unassigned until reviewed.',
              'training_eligible':False,'reason':'No reviewed object annotations yet; not negative-label images.'}
    queue=[]
    for source in SOURCES:
        video=OUT/source['file']
        metadata=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
            '-show_streams','-show_format','-show_frames','-show_entries','frame=best_effort_timestamp_time,pkt_dts_time',
            '-of','json',str(video)]))
        pts=[float(f['best_effort_timestamp_time']) for f in metadata['frames']]
        selected=[min(range(len(pts)),key=lambda i:abs(pts[i]-t)) for t in source['times']]
        assert len(set(selected))==len(selected)<=10
        folder=OUT/source['id'];folder.mkdir(exist_ok=True)
        filt='select='+ '+'.join(f'eq(n\\,{i})' for i in selected)
        subprocess.run(['ffmpeg','-v','error','-threads','2','-i',str(video),'-vf',filt,'-fps_mode','vfr',
                        '-frames:v',str(len(selected)),'-start_number','0','-y',str(folder/'frame-%02d.png')],check=True)
        stream=metadata['streams'][0]
        row={k:v for k,v in source.items() if k!='times'}
        row.update(original_file=str(video),original_sha256=sha(video),original_bytes=video.stat().st_size,
                   video_group=source['id'],split='unassigned',downloaded_original=True,
                   dimensions=[stream['width'],stream['height']],duration_seconds=float(metadata['format']['duration']),
                   frame_rate=stream.get('avg_frame_rate'),license_checked_date='2026-09-26',
                   human_review_status='unreviewed',object_annotations_reviewed=False,
                   changes='Decoded 10 PNG frames at recorded source frame presentation timestamps; original video retained unmodified.',frames=[])
        thumbs=[]
        for j,(frameidx,target) in enumerate(zip(selected,source['times'])):
            path=folder/f'frame-{j:02d}.png';im=cv2.imread(str(path));assert im is not None
            frame=dict(id=f'{source["id"]}-{frameidx:06d}',path=str(path),sha256=sha(path),
                video_group=source['id'],location_group=source['location_group'],split='unassigned',
                source_frame_index_zero_based=frameidx,source_timestamp_seconds=pts[frameidx],
                requested_timestamp_seconds=target,source_file_sha256=row['original_sha256'],
                source_video=str(video),source_page=source['source_page'],author=source['author'],
                license=source['license'],license_url=source['license_url'],
                context_start_seconds=max(0,pts[frameidx]-2),context_end_seconds=min(row['duration_seconds'],pts[frameidx]+2),
                context_source='Full original video retained; context intervals reference original timestamps.',
                review_status='unreviewed',annotation_status='not_started',annotations=None,
                training_eligible=False,contains_existing_detection_overlays=False)
            row['frames'].append(frame);queue.append(frame)
            tile=np.zeros((220,300,3),np.uint8)
            scale=min(300/im.shape[1],185/im.shape[0]);small=cv2.resize(im,(round(im.shape[1]*scale),round(im.shape[0]*scale)))
            x=(300-small.shape[1])//2;tile[30:30+small.shape[0],x:x+small.shape[1]]=small
            cv2.putText(tile,f'{j:02d} | frame {frameidx} | {pts[frameidx]:.3f}s',(5,20),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1)
            thumbs.append(tile)
        cv2.imwrite(str(folder/'contact-sheet.png'),np.vstack([np.hstack(thumbs[:5]),np.hstack(thumbs[5:])]))
        manifest['sources'].append(row)
        print(source['id'],row['dimensions'],row['duration_seconds'],len(row['frames']),flush=True)
    manifest['downloaded_video_count']=len(manifest['sources']);manifest['extracted_frame_count']=len(queue)
    old=OUT/'manifest.json'
    if old.exists() and not (OUT/'pexels-not-acquired.json').exists():
        previous=json.loads(old.read_text())
        if previous.get('downloaded_video_count')==0:
            (OUT/'pexels-not-acquired.json').write_text(json.dumps(previous,ensure_ascii=False,indent=2)+'\n')
    old.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (OUT/'annotation-queue.json').write_text(json.dumps({'schema_version':1,'status':'pending_human_review',
        'not_part_of_frozen_dataset':True,'classes':[],'images':queue},ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
