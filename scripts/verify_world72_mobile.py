#!/usr/bin/env python3
"""Conversion equivalence on six training frames; never an accuracy/test-set evaluation."""
import argparse
import json
from pathlib import Path
from export_mobile_model import ROOT, sha
from export_world72_mobile import PINNED_SHA, RESOURCE
from verify_mobile_model import iou

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--resource', default=RESOURCE)
    args = parser.parse_args()
    result = json.loads(args.result.read_text())
    assert sha(result['weights']) == PINNED_SHA
    import cv2
    import numpy as np
    import torch
    import coremltools as ct
    from PIL import Image
    from ultralytics import YOLOWorld
    from ultralytics.utils.nms import non_max_suppression
    torch.set_num_threads(2)
    pt = YOLOWorld(result['weights']).model.eval()
    resource = args.resource
    cm = ct.models.MLModel(str(ROOT/'ios/Models'/f'{resource}.mlpackage'), compute_units=ct.ComputeUnit.CPU_ONLY)
    meta = json.loads((ROOT/'ios/Models'/f'{resource}.json').read_text())
    train = args.result.parent/'images/train'
    files = sorted(train.glob('*'))
    frames = []
    for video in range(1, 7):
        candidates = [p for p in files if p.name.startswith(f'video{video:02}')]
        assert candidates, f'No training frames for video {video}'
        frames.append(candidates[len(candidates)//2])
    rows = []
    def decode(pred):
        return non_max_suppression(torch.from_numpy(pred.copy()), conf_thres=.25,
            iou_thres=.7, agnostic=True, nc=72, max_det=300)[0].numpy()
    for path in frames:
        im = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        h, w = im.shape[:2]; gain = min(640/w, 640/h)
        rw, rh = round(w*gain), round(h*gain); left, top = (640-rw)//2, (640-rh)//2
        rgb = cv2.copyMakeBorder(cv2.resize(im, (rw, rh)), top, 640-rh-top,
            left, 640-rw-left, cv2.BORDER_CONSTANT, value=(114,114,114))
        with torch.inference_mode():
            raw = pt(torch.from_numpy(rgb.transpose(2,0,1).copy()).unsqueeze(0).float()/255)[0].numpy()
        converted = cm.predict({'image': Image.fromarray(rgb)})[meta['outputs'][0]['name']]
        assert raw.shape == converted.shape == (1,76,8400)
        a, b = decode(raw), decode(converted)
        used = set(); matches = []
        for x in a:
            score, j = max(((iou(x[:4], y[:4]), j) for j, y in enumerate(b)
                if j not in used and x[5] == y[5]), default=(0., -1))
            if score >= .95:
                used.add(j); matches.append({'iou': float(score), 'confidenceError': float(abs(x[4]-b[j,4]))})
        # A conversion gate, not a claim about target recall or false positives.
        passed = len(matches) == len(a) == len(b) and all(m['confidenceError'] < .03 for m in matches)
        rows.append(dict(path=str(path), imageSHA256=sha(path), pytorchCount=len(a), coreMLCount=len(b),
            matches=matches, passed=passed, coreMLDetections=b.tolist(), geometry=[gain,left,top,w,h]))
    report = dict(resource=resource, sourceSHA256=PINNED_SHA, scope=__doc__,
        heldOutTestExecuted=False, accuracyValidated=False, passed=all(r['passed'] for r in rows), frames=rows)
    (ROOT/'validation/mobile-world72'/f'{resource}-parity.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'frames'}))
    print([(Path(r['path']).name,r['pytorchCount'],r['coreMLCount'],r['passed']) for r in rows])
    assert report['passed'], 'Conversion gate failed; inspect report before selecting this model.'

if __name__ == '__main__':
    main()
