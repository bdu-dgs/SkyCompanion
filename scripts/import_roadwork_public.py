#!/usr/bin/env python3
"""Bounded, revision-pinned ROADWork core import; never download the 10 GB zip whole.

Publisher annotations stay publisher annotations. No claim of independent review,
pedestrian-path ground truth, completeness for SkyCompanion's other classes, or phone metrics.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
from pathlib import Path
import random
import struct
import time
import urllib.request
import zipfile
import zlib

REVISION = '397741364934749644e47fdc1a7bc670f830b65a'
BASE = f'https://huggingface.co/datasets/anuragxel/roadwork-dataset/resolve/{REVISION}'
IMAGE_SIZE = 10595098610
ANNOTATION_SHA = '34d54b0a68648f901ac5f5e095b0e2fa82aa8177e80bb27b28c0f9b92efdde11'
ANNOTATION_SIZE = 66903277
README_REVISION = 'f32fd3ce00acf379862d6e6abd10a015c534644b'
IMAGE_ARCHIVE_SHA = '06351c4b8c0e959cceb7dfdbe860c2a0c1d14bf9aa6df341e0a57330a5aaafc2'
CLASS_MAP = {3: 'traffic_cone', 4: 'construction_fence', 5: 'construction_barrel',
             6: 'construction_barricade', 7: 'construction_barrier'}
CLASSES = list(CLASS_MAP.values())
EXPECTED_SOURCE = {3: 'Cone', 4: 'Fence', 5: 'Drum', 6: 'Barricade', 7: 'Barrier'}
SEED = 20260926


def digest(data):
    return hashlib.sha256(data).hexdigest()


def ensure_annotation_archive(path):
    if not path.exists():
        request = urllib.request.Request(BASE+'/annotations.zip', headers={'Accept-Encoding': 'identity'})
        partial = path.with_suffix('.zip.part')
        received = 0
        with urllib.request.urlopen(request, timeout=90) as response, partial.open('wb') as target:
            while True:
                data = response.read(min(1024*1024, ANNOTATION_SIZE-received+1))
                if not data: break
                received += len(data)
                if received > ANNOTATION_SIZE:
                    raise ValueError('Annotation download exceeds pinned size')
                target.write(data)
        if received != ANNOTATION_SIZE or digest(partial.read_bytes()) != ANNOTATION_SHA:
            raise ValueError('Pinned annotation download size / hash mismatch')
        partial.replace(path)
    if path.stat().st_size != ANNOTATION_SIZE or digest(path.read_bytes()) != ANNOTATION_SHA:
        raise ValueError('Modified pinned annotation archive')


def geographic_group(image, publisher_split):
    city = image.get('city_name')
    name = image['file_name']
    info = image.get('video_info', {})
    if city and info.get('vid_id'):
        # Keep every sequence from a single video together, not just frame chunks.
        return city, f"roadwork:{city}:{info['vid_id']}"
    if publisher_split == 'train' and name.startswith(('pgh01_', 'pgh02_', 'pgh03_', 'pgh04_')):
        return 'pittsburgh', 'roadwork:cmu:' + name.split('_')[0]
    # IMG photographs have no route identifier in the publisher COCO metadata.
    return None, None


def select_subset(train, val, limits=(600, 120, 120)):
    """City-isolated split, round-robin categories/cities, at most one source row once."""
    for data in (train, val):
        names = {c['id']: c['name'] for c in data['categories']}
        if any(names.get(k) != v for k, v in EXPECTED_SOURCE.items()):
            raise ValueError('Publisher class IDs changed; refuse implicit remapping.')
    cities = sorted({im.get('city_name') for im in val['images'] if im.get('city_name')})
    # Reproducible city assignment independent of predictions and image appearance.
    random.Random(SEED).shuffle(cities)
    val_cities, test_cities = set(cities[::2]), set(cities[1::2])
    if not val_cities or not test_cities or 'pittsburgh' in val_cities | test_cities:
        raise ValueError('Invalid Pittsburgh / independent-city split.')
    pools = defaultdict(list)
    excluded_unknown = 0
    for publisher_split, data in [('train', train), ('val', val)]:
        ann_by_image = defaultdict(list)
        for ann in data['annotations']:
            ann_by_image[ann['image_id']].append(ann)
        for im in data['images']:
            city, video = geographic_group(im, publisher_split)
            if city is None:
                excluded_unknown += 1
                continue
            split = 'train' if publisher_split == 'train' else ('val' if city in val_cities else 'test')
            anns = ann_by_image[im['id']]
            present = {a['category_id'] for a in anns if a['category_id'] in CLASS_MAP and not a.get('iscrowd')}
            if present:
                pools[split].append(dict(source_image=im, source_annotations=anns,
                                         publisher_split=publisher_split, split=split, city=city,
                                         video_group=video, present=sorted(present)))
    selected = []
    for split, limit in zip(('train', 'val', 'test'), limits):
        # Balance class-containing images and cities without choosing model outcomes.
        buckets = defaultdict(list)
        for row in pools[split]:
            for category in row['present']:
                buckets[(category, row['city'])].append(row)
        rng = random.Random(SEED)
        for rows in buckets.values():
            rng.shuffle(rows)
        keys = sorted(buckets)
        used = set()
        while len(used) < limit:
            progress = False
            for key in keys:
                rows = buckets[key]
                while rows and rows[-1]['source_image']['file_name'] in used:
                    rows.pop()
                if rows and len(used) < limit:
                    row = rows.pop()
                    used.add(row['source_image']['file_name'])
                    selected.append(row)
                    progress = True
            if not progress:
                break
    return selected, dict(train_cities=['pittsburgh'], val_cities=sorted(val_cities),
                          test_cities=sorted(test_cities), excluded_unknown_route_images=excluded_unknown,
                          eligible_counts={k: len(v) for k, v in pools.items()}, seed=SEED)


def normalized_annotation(ann, image):
    if ann['category_id'] not in CLASS_MAP:
        return None
    if ann.get('iscrowd'):
        raise ValueError('Crowd annotation needs an ignore-region-aware trainer, not ordinary YOLO labels.')
    w, h = image['width'], image['height']
    x, y, bw, bh = map(float, ann['bbox'])
    left, top, right, bottom = max(0., x), max(0., y), min(float(w), x+bw), min(float(h), y+bh)
    if right <= left or bottom <= top:
        raise ValueError('Invalid publisher box.')
    return dict(label=CLASS_MAP[ann['category_id']], x=left/w, y=top/h,
                w=(right-left)/w, h=(bottom-top)/h, source_annotation_id=ann['id'],
                source_category_id=ann['category_id'], source_segmentation=ann.get('segmentation'),
                source_attributes=ann.get('attributes', {}), iscrowd=0)


class RangeReader(io.RawIOBase):
    """Minimal seekable HTTP range reader. Refuses a server's full-body fallback."""
    def __init__(self, url, size):
        self.url, self.size, self.position = url, size, 0
        self.bytes_downloaded = 0
    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.position
    def seek(self, offset, whence=0):
        self.position = offset + (0 if whence == 0 else self.position if whence == 1 else self.size)
        if self.position < 0: raise ValueError('Negative range offset')
        return self.position
    def read(self, count=-1):
        count = self.size-self.position if count < 0 else min(count, self.size-self.position)
        if count == 0: return b''
        if count < 0 or count > 32 * 1024 * 1024:
            raise ValueError('Single range exceeds 32 MB bound')
        start, end = self.position, self.position+count-1
        # Distinct resolver URLs prevent an intermediary from reusing another Range response.
        request = urllib.request.Request(self.url + f'?download=true&skycompanion_range={start}-{end}',
                                         headers={'Range': f'bytes={start}-{end}', 'Accept-Encoding': 'identity'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{self.size}':
                        raise ValueError('Server did not honor exact bounded byte range')
                    data = response.read(count+1)
                    if len(data) < count:
                        raise OSError('Truncated HTTP range; retry bounded request')
                    if len(data) > count:
                        raise ValueError('Oversized HTTP range')
                break
            except (OSError, TimeoutError):
                if attempt == 2: raise
                time.sleep(1+attempt)
        self.position += count
        self.bytes_downloaded += count
        return data


def decode_member(info, local_bytes):
    header = struct.unpack('<IHHHHHIIIHH', local_bytes[:30])
    if header[0] != 0x04034b50 or header[1] > 63 or header[2] & 1:
        raise ValueError('Unsupported local zip member')
    start = 30 + header[-2] + header[-1]
    compressed = local_bytes[start:start+info.compress_size]
    if len(compressed) != info.compress_size:
        raise ValueError('Insufficient range for compressed image')
    if info.compress_type == zipfile.ZIP_DEFLATED:
        data = zlib.decompress(compressed, -15)
    elif info.compress_type == zipfile.ZIP_STORED:
        data = compressed
    else:
        raise ValueError('Unsupported ZIP compression')
    if len(data) != info.file_size or zlib.crc32(data) & 0xffffffff != info.CRC:
        raise ValueError('Image CRC / uncompressed size mismatch')
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1]/'backend/data/obstacle_dataset/public-roadwork-v1')
    ap.add_argument('--train-limit', type=int, default=600)
    ap.add_argument('--val-limit', type=int, default=120)
    ap.add_argument('--test-limit', type=int, default=120)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--metadata-only', action='store_true')
    args = ap.parse_args()
    if not (1 <= args.train_limit <= 1000 and 1 <= args.val_limit <= 200 and 1 <= args.test_limit <= 200 and 1 <= args.workers <= 4):
        ap.error('Bounds: train 1..1000, val/test 1..200, workers 1..4')
    root = args.output.resolve(); source = root/'source'; source.mkdir(parents=True, exist_ok=True)
    archive = source/'annotations.zip'
    ensure_annotation_archive(archive)
    with zipfile.ZipFile(archive) as z:
        train = json.loads(z.read('annotations/instances_train_pittsburgh_only.json'))
        val = json.loads(z.read('annotations/instances_val_pittsburgh_only.json'))
    rows, split_info = select_subset(train, val, (args.train_limit, args.val_limit, args.test_limit))
    (source/'selection.json').write_text(json.dumps(dict(split_info=split_info, rows=rows), indent=2))
    print(json.dumps(dict(selected=Counter(r['split'] for r in rows), split_info=split_info)), flush=True)
    if args.metadata_only: return
    remote = RangeReader(BASE+'/images.zip', IMAGE_SIZE)
    with zipfile.ZipFile(remote) as z:
        members = {Path(i.filename).name: i for i in z.infolist() if not i.is_dir()}
    def acquire(row):
        from PIL import Image
        im = row['source_image']; name = im['file_name']; split = row['split']
        info = members[name]
        if not info.filename.startswith('images/') or Path(name).name != name:
            raise ValueError('Unexpected source member')
        target = root/'images'/split/name; target.parent.mkdir(parents=True, exist_ok=True)
        read_bytes = 0
        if not target.exists():
            rr = RangeReader(BASE+'/images.zip', IMAGE_SIZE); rr.seek(info.header_offset)
            data = decode_member(info, rr.read(min(info.compress_size+2048, IMAGE_SIZE-info.header_offset)))
            read_bytes = rr.bytes_downloaded
            target.write_bytes(data)
        else:
            data = target.read_bytes()
            if len(data) != info.file_size or zlib.crc32(data)&0xffffffff != info.CRC:
                raise ValueError('Existing image does not match source archive CRC')
        with Image.open(io.BytesIO(data)) as actual:
            if actual.size != (im['width'], im['height']):
                raise ValueError('Image dimensions disagree with source annotations')
            actual.verify()
        anns = [normalized_annotation(a, im) for a in row['source_annotations'] if a['category_id'] in CLASS_MAP]
        source_file = root/'source_annotations'/split/(Path(name).stem+'.json')
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text(json.dumps(dict(image=im, annotations=row['source_annotations'], categories=train['categories']), indent=2))
        result = dict(id='roadwork:'+name, path=str(target), sha256=digest(data), split=split,
                      width=im['width'], height=im['height'], video_group=row['video_group'],
                      location_group='roadwork:city:'+row['city'], review_status='published_annotations',
                      reviewed_classes=CLASSES, usage_status='public_dataset_license_verified',
                      annotation_source=f'{BASE}/annotations.zip#annotations/instances_{row["publisher_split"]}_pittsburgh_only.json',
                      annotation_license='ODC-By-1.0',
                      annotation_coverage={label: 'complete' for label in CLASSES},
                      annotation_coverage_basis='Publisher describes manually fully annotated images, scoped to its construction categories; not independently audited completeness.',
                      annotations=anns, source_annotation_path=str(source_file),
                      source_annotation_sha256=digest(source_file.read_bytes()),
                      source_image_id=im['id'], source_city=row['city'], source_video_info=im.get('video_info'),
                      source_gps=im.get('gps'), source_publisher_split=row['publisher_split'],
                      source_dataset='ROADWork original core', source_revision=REVISION,
                      source_image_archive_member=info.filename,
                      source_image_crc32=f'{info.CRC:08x}', license='ODC-By-1.0',
                      label_scope='Publisher manual instance annotations for five selected roadwork categories only; other SkyCompanion classes are unknown.',
                      independent_review_status='not_independently_reviewed', risk_annotation_status='not_annotated')
        return result, read_bytes
    images = []; downloaded = remote.bytes_downloaded
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(acquire, row) for row in rows]
        for f in as_completed(futures):
            im, count = f.result(); images.append(im); downloaded += count
            if len(images)%25 == 0 or len(images) == len(rows):
                print(json.dumps(dict(downloaded_images=len(images), requested_images=len(rows), transferred_bytes=downloaded)), flush=True)
    images.sort(key=lambda im: (im['split'], im['id']))
    # Hash/route/city isolation is checked before any usable manifest is written.
    seen = {}
    for im in images:
        for field in ('sha256', 'video_group', 'location_group'):
            key = (field, im[field])
            if key in seen and seen[key] != im['split']:
                raise ValueError(f'Cross-split leakage: {key}')
            seen[key] = im['split']
    manifest = dict(schema_version=1, name='ROADWork public construction pilot v1', classes=CLASSES,
                    source=dict(url='https://github.com/anuragxel/roadwork-dataset', revision=REVISION,
                                license_evidence_url=f'https://github.com/anuragxel/roadwork-dataset/blob/{README_REVISION}/README.md#-license',
                                license='ODC-By-1.0', citation='Ghosh et al., ROADWork, ICCV 2025',
                                annotation_archive_sha256=ANNOTATION_SHA,
                                image_archive_publisher_sha256=IMAGE_ARCHIVE_SHA,
                                image_archive_full_hash_locally_verified=False,
                                integrity='Selected uncompressed members checked by ZIP CRC32, dimensions, and locally recorded SHA256.',
                                excluded=['discovered_images.zip', 'discovered_subsets_with_annotations.zip', 'german/']),
                    split_policy=split_info,
                    annotation_policy=dict(provenance='publisher_manual_annotations',
                                           complete_only_for=CLASSES, independently_reviewed=False,
                                           fence_scope='Construction/work-zone fence only. General railings/fences may be unlabelled; do not map to generic fence or assume generic-fence negatives.',
                                           preserve_source_masks=True,
                                           no_geometric_distance_or_walkability_ground_truth=True),
                    evaluation_limitations=['Driving viewpoint; not an ego-walking near-obstacle acceptance set.',
                                            'No video temporal metrics: sparse stills and no tracked onset ground truth.',
                                            'No pole, column, tree_trunk or rock annotation completeness.',
                                            'Construction-fence labels do not establish completeness for ordinary street/park fences.',
                                            'No independent label review; published annotations are not human_verified SkyCompanion labels.'],
                    images=images)
    (root/'dataset.json').write_text(json.dumps(manifest, indent=2))
    report = dict(image_counts=dict(Counter(i['split'] for i in images)),
                  annotation_counts={s:dict(Counter(a['label'] for i in images if i['split']==s for a in i['annotations'])) for s in ('train','val','test')},
                  city_counts={s:len({i['location_group'] for i in images if i['split']==s}) for s in ('train','val','test')},
                  downloaded_bytes_this_run=downloaded, dataset_sha256=digest((root/'dataset.json').read_bytes()),
                  publisher_label_training_candidate=True, production_acceptance_passed=False)
    (root/'import-report.json').write_text(json.dumps(report, indent=2)); print(json.dumps(report), flush=True)


if __name__ == '__main__': main()
