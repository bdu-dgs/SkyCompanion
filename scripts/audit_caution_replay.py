#!/usr/bin/env python3
"""Compare offline speech schedules with independently reviewed event windows.

Usage: audit_caution_replay.py reviewed-events.json schedules.json output.json
This checks reviewed event coverage, not collision risk or physical safety.
"""
import json
import sys
from pathlib import Path

events = json.loads(Path(sys.argv[1]).read_text())["events"]
runs = json.loads(Path(sys.argv[2]).read_text())
results = []
for run in runs:
    coverage = []
    for event in events:
        hits = [s for s in run["speech"]
                if event["window"][0] <= s["second"] <= event["window"][1]
                and s["label"] in event["labels"]
                and s["direction"] in event["directions"]]
        coverage.append({"event": event["id"], "covered": bool(hits), "matches": hits})
    results.append({"scenario": run["scenario"], "coverage": coverage})
repeats = [r["speech"] for r in runs if r["scenario"].startswith("repeat-")]
report = {
    "fixed_input_repeats_identical": len(repeats) >= 2 and all(r == repeats[0] for r in repeats),
    "all_reviewed_events_covered": all(c["covered"] for r in results for c in r["coverage"]),
    "results": results,
    "limitation": "Coverage does not certify every spoken object, metric danger, or unseen-video generalization."
}
Path(sys.argv[3]).write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k != "results"}))
sys.exit(0 if report["fixed_input_repeats_identical"] and report["all_reviewed_events_covered"] else 1)
