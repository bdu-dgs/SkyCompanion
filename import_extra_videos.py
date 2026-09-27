"""Retain supplied videos and extract every decoded frame without sampling."""
import argparse,json,shutil,subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from video_training import ROOT,digest,index_frames,save


def import_video(record):
    src=Path(record['source_path']);out=Path(record['data_path'])
    out.mkdir(parents=True,exist_ok=True)
    retained=out/'source.mp4'
    sha=digest(src)
    if retained.exists():
        if digest(retained)!=sha:raise ValueError(f'Existing retained source differs: {out}')
    else:shutil.copy2(src,retained)
    if digest(retained)!=sha:raise ValueError(f'Retained source checksum failure: {out}')
    save(out/'retained_video.json',dict(original_path=str(src),retained_path=str(retained),sha256=sha))
    images=out/'images/train';images.mkdir(parents=True,exist_ok=True)
    if not (out/'frames.jsonl').exists():
        if any(images.iterdir()):raise ValueError(f'Partial extraction exists; inspect before retry: {images}')
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(retained),'-map','0:v:0',
            '-fps_mode','passthrough','-start_number','0','-threads','2','-compression_level','2',
            str(images/'frame_%06d.png')],check=True)
        index_frames(SimpleNamespace(data=out,video=retained))
    rows=[json.loads(s) for s in (out/'frames.jsonl').read_text().splitlines()]
    if len(rows)!=record['expected_frames']:raise ValueError(f'Frame count mismatch: {out}: {len(rows)}')
    result=dict(**record,frame_count=len(rows),sha256=sha,frames_manifest_sha256=digest(out/'frames.jsonl'),
        retained_path=str(retained),status='all_frames_extracted_unannotated')
    save(out/'import_result.json',result)
    print(json.dumps(dict(video_id=record['video_id'],frame_count=len(rows),status=result['status'])),flush=True)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);a=p.parse_args()
    records=json.loads(a.manifest.read_text())['new_videos']
    # Retain all small source MP4s before any lengthy frame extraction.
    for r in records:
        src=Path(r['source_path']);out=Path(r['data_path']);out.mkdir(parents=True,exist_ok=True)
        target=out/'source.mp4'
        if not target.exists():shutil.copy2(src,target)
        if digest(target)!=digest(src):raise ValueError(f'Copy mismatch: {src}')
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(import_video,records))
    save(a.manifest.parent/'extra_import_results.json',dict(videos=results,total_new_frames=sum(r['frame_count'] for r in results)))


if __name__=='__main__':main()
