#!/usr/bin/env python3
"""Summarize phone JSONL evidence; never substitutes local video for DJI acceptance."""
import argparse
import json
import math
import statistics
from pathlib import Path


def summarize(rows):
    samples = [r for r in rows if r.get('event') == 'sample']
    epochs = {}
    for row in samples:
        key = (row.get('sessionID'), row.get('revision'))
        epochs.setdefault(key, row['uptimeMS'])
    steady = [r for r in samples if r['uptimeMS'] - epochs[(r.get('sessionID'), r.get('revision'))] >= 5_000]

    def metric(key):
        values = sorted(r[key] for r in steady if isinstance(r.get(key), (int, float)) and math.isfinite(r[key]))
        if not values:
            return None
        return {'count': len(values), 'min': values[0], 'median': statistics.median(values),
                'p95': values[max(0, math.ceil(len(values)*0.95)-1)], 'max': values[-1]}

    starts = [i for i, r in enumerate(rows) if r.get('event') == 'stability_test_started']
    test = None
    if starts:
        run = rows[starts[-1]:]
        finish = next((i for i, r in enumerate(run) if r.get('event') == 'stability_test_finished'), None)
        if finish is not None:
            run = run[:finish+1]
        elapsed = (run[-1]['uptimeMS'] - run[0]['uptimeMS'])/1000
        run_samples = [r for r in run if r.get('event') == 'sample']
        times = [run[0]['uptimeMS']] + [r['uptimeMS'] for r in run_samples] + [run[-1]['uptimeMS']]
        gap = max((b-a for a,b in zip(times,times[1:])), default=0)/1000
        interruptions = [r for r in run if r.get('event') in ('unavailable', 'pause', 'end')]
        complete = finish is not None and elapsed >= 1800 and len(run_samples) >= 1500 and gap <= 5 and not interruptions
        test = {'recorded_elapsed_seconds': elapsed, 'completion_marker': finish is not None,
                'samples': len(run_samples), 'largest_recording_gap_seconds': gap,
                'interruptions': interruptions, 'uninterrupted_30_minute_log_evidence': complete,
                'scope': 'Local looping-video process test only; not cross-app DJI or acoustic validation'}
    return {'sources': sorted({r.get('source', 'unknown') for r in samples}), 'samples': len(samples),
            'warmup_excluded_seconds_per_revision': 5, 'steady_samples': len(steady),
            'metrics': {k: metric(k) for k in ('fps', 'inferenceMS', 'preprocessMS', 'modelMS', 'decodeMS', 'ageMS', 'visionResidentMB')},
            'steady_samples_at_least_10fps_fraction': sum(r.get('fps', 0) >= 10 for r in steady)/len(steady) if steady else None,
            'thermal_states': sorted({r['thermalState'] for r in samples if 'thermalState' in r}),
            'battery_samples': [{'uptimeMS': r['uptimeMS'], 'level': r.get('batteryLevel'), 'state': r.get('batteryState')} for r in samples[::60]],
            'long_test': test, 'limitations': ['memory is sampled resident memory, not physical peak',
                'age excludes DJI transmission; no acoustic onset measurement', 'no recognition-accuracy conclusion from performance logs']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('jsonl', type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.jsonl.read_text().splitlines() if line.strip()]
    print(json.dumps(summarize(rows), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
