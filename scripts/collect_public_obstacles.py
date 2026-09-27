#!/usr/bin/env python3
"""Download a bounded, pinned public pole research set. Never invent video/location ids."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request

REPO = 'hotosm/streetlevel-poles'
REVISION = '0352f0b2b067439ca3467994cb9938a42310a09e'
SHARDS = {split: [f'data/{split}/{split}-{i:05d}-of-{n:05d}.parquet' for i in range(n)]
          for split,n in [('train',5),('val',2),('test',2)]}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=a.output.resolve();root.mkdir(parents=True,exist_ok=True)
    def download(f):
        path=root/f;path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            tmp=path.with_suffix(path.suffix+'.part')
            urllib.request.urlretrieve(f'https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{f}',tmp)
            tmp.rename(path)
        return {'path':f,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
    with ThreadPoolExecutor(max_workers=3) as pool:
        assets=list(pool.map(download,['README.md',*[f for parts in SHARDS.values() for f in parts]]))
    import pyarrow.parquet as pq
    images=[]
    for split,shards in SHARDS.items():
        rows=[row for shard in shards for row in pq.read_table(root/shard).to_pylist()]
        print(split,len(rows),'rows',flush=True)
        for row in rows:
            obj=row['objects'];width,height=row['width'],row['height']
            identifier=str(row['image_id']);name=hashlib.sha256((split+identifier).encode()).hexdigest()[:20]
            dest=root/'images'/split/(name+'.jpg');dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(row['image']['bytes'])
            boxes=[]
            for xywh,label in zip(obj['bbox'],obj['category']):
                x,y,w,h=xywh
                boxes.append({'label':['pole','tower'][label],'x':max(0.,x/width),'y':max(0.,y/height),
                              'w':min(w/width,1-max(0.,x/width)), 'h':min(h/height,1-max(0.,y/height))})
            images.append({'id':'hotosm-'+split+'-'+identifier,'path':str(dest),
                           'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'split':split,
                           'video_group':'unknown-public-stills','location_group':'unknown-public-location',
                           'review_status':'published_annotations','reviewed_classes':['pole','tower'],
                           'annotations':boxes,'annotation_source':f'https://huggingface.co/datasets/{REPO}/tree/{REVISION}',
                           'annotation_license':'CC-BY-SA-4.0',
                           'source_metadata':{k:row.get(k) for k in ('source','source_url','panoramax_id','lat','lon')},
                           'time_s':None,'time_basis':'still_image_no_temporal_evaluation'})
    data={'version':1,'classes':['pole','tower'],'images':images,
          'purpose':'public_annotation_research_pilot_not_deployment',
          'split_policy':'Pinned publisher split subset; original capture/video/geographic separation NOT verified.',
          'source':f'https://huggingface.co/datasets/{REPO}', 'source_revision':REVISION,
          'license':'CC-BY-SA-4.0','assets':assets,
          'limitations':['Utility poles/towers only; not all sidewalk posts or structural pillars.',
                         'No temporal clips or true first-detection time.',
                         'Published labels are not claimed to have been reviewed by SkyCompanion users.',
                         'Positive-sample GPS and original sequences unavailable; not geographical acceptance.']}
    (root/'dataset.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(root/'dataset.json')


if __name__=='__main__':main()
