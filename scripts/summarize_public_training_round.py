#!/usr/bin/env python3
"""Assemble completed frozen public evaluations; never select settings or deploy."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path)
    a=p.parse_args();root=a.run.resolve()
    summary={'deployment_allowed':False,'models':{},'local_regressions':{},'original_input_transfer':None}
    for dataset,train in [('roadwork','roadwork'),('ade','ade-regions')]:
        report=json.loads((root/(dataset+'-evaluation/report.json')).read_text())
        result=json.loads((root/train/'result.json').read_text())
        path=Path(result['weights']);sha=hashlib.sha256(path.read_bytes()).hexdigest()
        if sha!=result['sha256'] or sha!=report['candidate_sha256'] or set(report['test'])!={'baseline_v7','candidate'}:
            raise ValueError('Incomplete or inconsistent evaluation: '+dataset)
        summary['models'][dataset]={'weights':str(path),'sha256':sha,
            'scope':'Construction publisher instance boxes' if dataset=='roadwork' else 'Rendered known-pixel semantic connected regions; not original full-frame detection',
            'settings':report['locked_settings'],'vocabulary_coverage':report['output_vocabulary_coverage'],
            'test':{name:{'per_class':{c:{k:m[k] for k in ('tp','fp','fn','precision','recall')} for c,m in values['evaluation']['per_class'].items()},'timing':values['timing']} for name,values in report['test'].items()},
            'report':str(root/(dataset+'-evaluation/report.json'))}
        if dataset=='roadwork':
            revised_path=root/'roadwork-evaluation/source-deduplicated-v1/fixed-test-recount.json'
            revised=json.loads(revised_path.read_text())
            if revised['locked_settings'] != report['locked_settings'] or revised['new_holdout']:
                raise ValueError('Recount changed frozen settings or claims a new holdout')
            model=summary['models'][dataset]
            model['test_original_annotations']=model['test']
            model['test']={}
            for name,values in revised['models'].items():
                if values['model_fingerprint']!=report['model_fingerprints'][name]:
                    raise ValueError('Recount model differs')
                model['test'][name]={'per_class':{c:{k:m[k] for k in ('tp','fp','fn','precision','recall')} for c,m in values['deduplicated']['per_class'].items()},
                                     'timing':model['test_original_annotations'][name]['timing']}
            model['annotation_revision_report']=str(revised_path)
            model['annotation_revision_note']='Same test images and stored predictions, exact duplicate source annotations removed; original validation settings unchanged. Not a new holdout or a weight improvement.'
    for name in ('local-poles-ade','local-street-ade','local-street-roadwork'):
        report=json.loads((root/name/'report.json').read_text())
        summary['local_regressions'][name]={model:values['selected_target_results'] for model,values in report['models'].items()}
    report=json.loads((root/'ade-original-transfer/report.json').read_text())
    summary['original_input_transfer']={model:values['splits']['test']['known_target_recall'] for model,values in report['models'].items()}
    summary['limitations']=['Public source annotations, not independent human acceptance.','Local clean frames are previously inspected selected targets, not an independent holdout; no full-scene precision.',
        'ADE complete-region scores use void-filled input. Original JPEG transfer recall is separate, with unknown labels kept unknown.',
        'Public image scores cannot establish phone FPS, first-discovery time, continuous misses, path occupancy, audio latency or interruptions.',
        'Tree-trunk data remain quarantined due to partial annotations; no new trunk specialist was trained.',
        'Four/five-class specialists do not preserve the online model\'s complete 115-class vocabulary.']
    (root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    def percent(x):return '—' if x is None else f'{100*x:.1f}%'
    lines=['# Public-data training result','', 'Candidate weights only; no deployment.','']
    for dataset,values in summary['models'].items():
        lines.extend(['## '+dataset,'',values['scope'],'','| Class | Baseline precision | Candidate precision | Baseline recall | Candidate recall | Candidate TP / FP / FN |','|---|---:|---:|---:|---:|---:|'])
        for cls,new in values['test']['candidate']['per_class'].items():
            old=values['test']['baseline_v7']['per_class'][cls]
            lines.append(f"| {cls} | {percent(old['precision'])} | {percent(new['precision'])} | {percent(old['recall'])} | {percent(new['recall'])} | {new['tp']} / {new['fp']} / {new['fn']} |")
        missing=values['vocabulary_coverage']['baseline_v7']['missing_exact_or_approved_alias']
        if missing:lines.extend(['','Baseline has no approved output alias for: '+', '.join(missing)+'. Zero recall here includes vocabulary mismatch.'])
        if values.get('annotation_revision_note'):lines.extend(['',values['annotation_revision_note']])
        lines.extend(['',f"Weights: {values['weights']}",f"SHA256: {values['sha256']}",''])
    lines.extend(['## Unmodified original ADE input (known-region recall only)','','| Class | Baseline recall | Candidate recall | Candidate hits / known targets |','|---|---:|---:|---:|'])
    for cls,new in summary['original_input_transfer']['candidate'].items():
        old=summary['original_input_transfer']['baseline_v7'][cls]
        lines.append(f"| {cls} | {percent(old['recall'])} | {percent(new['recall'])} | {new['tp']} / {new['tp']+new['fn']} |")
    lines.extend(['','## Selected clean-frame regression',''])
    for name,models in summary['local_regressions'].items():
        lines.append(f'- {name}: '+ '; '.join(model+' '+', '.join(f"{cls} {r['hits']}/{r['targets']}" for cls,r in metrics.items()) for model,metrics in models.items()))
    lines.extend(['','Only compare classes actually trained by each specialist; zeros in unsupported classes are not preservation tests.','','## Limits',''])
    lines.extend('- '+limitation for limitation in summary['limitations'])
    (root/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    print(root/'RESULTS.md')

if __name__=='__main__':main()
