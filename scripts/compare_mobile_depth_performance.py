#!/usr/bin/env python3
"""Compare performance JSONL from the same local video with depth OFF versus ON."""
import argparse,json,statistics
from pathlib import Path

def summarize(path, enabled):
 rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
 samples=[r for r in rows if r.get('event')=='sample' and r.get('source')=='Local video' and r.get('depthEnabled') is enabled and not r.get('pathEnabled')]
 if enabled and sum(str(r.get('depthStatus','')).startswith('Experimental depth completed') for r in samples)<3:raise ValueError('No successful depth execution recorded')
 if len(samples)<30:raise ValueError('Need at least 30 one-second samples per run')
 modes={r.get('depthEnabled') for r in samples};clips={r.get('videoSHA256') for r in samples};models={r.get('model') for r in samples}
 if len(modes)!=1 or len(clips)!=1 or None in clips or len(models)!=1:raise ValueError('Mixed or missing mode, clip or model identity')
 samples=samples[5:]
 def med(key):return statistics.median(r[key] for r in samples if key in r)
 return {'depthEnabled':modes.pop(),'videoSHA256':clips.pop(),'model':models.pop(),'samples':len(samples),
         'fpsMedian':med('fps'),'inferenceMedianMS':med('inferenceMS'),'peakResidentMB':max(r['visionResidentMB'] for r in samples),
         'maxThermalState':max(r['thermalState'] for r in samples),'depthMedianMS':med('depthInferenceMS') if any('depthInferenceMS' in r for r in samples) else None}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('off',type=Path);p.add_argument('on',type=Path);a=p.parse_args()
 off,on=summarize(a.off,False),summarize(a.on,True)
 if off['depthEnabled'] is not False or on['depthEnabled'] is not True:raise ValueError('Expected OFF run then ON run')
 if off['videoSHA256']!=on['videoSHA256'] or off['model']!=on['model']:raise ValueError('Runs use different inputs/models')
 if on['depthMedianMS'] is None:raise ValueError('No depth execution measured')
 print(json.dumps({'off':off,'on':on,'fpsChangePercent':(on['fpsMedian']/off['fpsMedian']-1)*100,
  'memoryChangeMB':on['peakResidentMB']-off['peakResidentMB'],'scope':'Short local-video comparison, not broadcast or 30-minute acceptance.'},indent=2))
if __name__=='__main__':main()
