#!/usr/bin/env python3
"""Summarize per-class regressions; a research score never deploys a checkpoint."""
import argparse
import json
from pathlib import Path


def compare(report, baseline, candidate, required):
    before=report['models'][baseline];after=report['models'][candidate]
    rows=[];blockers=[]
    for label in required:
        b=before['evaluation']['per_class'].get(label,{});a=after['evaluation']['per_class'].get(label,{})
        positives=a.get('tp',0)+a.get('fn',0)
        delta_recall=None if b.get('recall') is None or a.get('recall') is None else a['recall']-b['recall']
        delta_fp=None if b.get('false_positives_per_reviewed_image') is None or a.get('false_positives_per_reviewed_image') is None else a['false_positives_per_reviewed_image']-b['false_positives_per_reviewed_image']
        rows.append({'class':label,'reviewed_positives':positives,'before':b,'after':a,
                     'recall_delta':delta_recall,'false_positives_per_image_delta':delta_fp})
        if positives==0:blockers.append(f'{label}: no reviewed positive examples')
        if delta_recall is not None and delta_recall < 0:blockers.append(f'{label}: recall regressed')
        if delta_fp is not None and delta_fp > 0:blockers.append(f'{label}: false positives increased')
    # Metadata and workflow evidence are mandatory independently of model metrics.
    blockers.extend(['Independent label review with truthful provenance and video/location separation need explicit acceptance.',
                     'Live capture-to-audible alert latency/FPS and temporal first-discovery tests are separate from serial still-image inference.'])
    return {'dataset_sha256':report['dataset_sha256'],'baseline':before['metadata'],
            'candidate':after['metadata'],'per_class':rows,
            'before_timing':before['timing'],'after_timing':after['timing'],
            'deployment_allowed':False,'blocking_reasons':blockers,
            'status':'review_report_only_never_changes_live_model'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('report',type=Path)
    p.add_argument('--baseline',default='yoloe-11s');p.add_argument('--candidate',default='local-candidate')
    p.add_argument('--classes',nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=compare(json.loads(a.report.read_text()),a.baseline,a.candidate,a.classes)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(a.output)
