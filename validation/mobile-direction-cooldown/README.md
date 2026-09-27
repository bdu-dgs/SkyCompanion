# Direction and missed-alert fix — 2026-09-27

The epoch-15, 72-class model, its confidence/NMS settings, class order, and preprocessing are unchanged. Package hashes match selectedModel.json. Native inference detections are exactly equal before and after the application-rule changes across the 126 replay frames. The source video's preferred transform is identity, not mirrored.

## Findings

- The eight-second global cooldown could discard a left pedestrian event after an unrelated front/right event.
- A nearby pedestrian outside the fixed front corridor could receive no candidate at all.
- Risk-event creation was treated as delivery, so targets suppressed by admission might never be offered again despite remaining visible.
- Deduplication by direction/consequence could merge different object categories. Conversely, fluctuating ground labels must not create repeated new ground warnings.

## Changes

- Retain epoch-15 inference unchanged; extend the existing near-image criterion to lateral people, with confidence and temporal confirmation. This is camera-relative evidence, not metric distance or verified collision urgency.
- Keep person and non-person risk tracks separate. Prioritize confirmed near-side people at the same risk level.
- Offer bounded, current-frame confirmed candidates to the guidance gate; send no delayed frame queue. Emit at most one admitted alert per frame, with existing speech-priority/command protections.
- Deduplicate by broad category for collision warnings, while preserving ground-warning deduplication across label drift. A different pedestrian track after an observation gap can be admitted; rapid track churn remains suppressed.
- New action-level content uses a 1.5-second gap. A newly confirmed passing person can bypass timing cooldown, but not the speech/command admission guards. Repeated ongoing content stays suppressed.
- Store target geometry in risk evidence, and log video playback time when alert audio starts. Incorrect-alert snapshots reference the actual spoken event rather than a different dominant assessment. No detection boxes were reintroduced into the UI.

## Validation

146 CaptureCore tests and the Release iPhone build passed. The actual native model replay admitted left person at 7.2 s, right pole at 10.4 s, and left person at 18.6 s. All three reported segment checks passed; see report.json for target coordinates and baseline decisions. These are offline admission timestamps, not measured phone acoustic onset. iPhone playback retest is still pending. No claim is made that every other detection/alert in the clip is correct.

To reproduce, compile scripts/replay_mobile_directions.swift with ios/OnDevice/VisionEngine.swift and CaptureCore. Pass a bundle containing the unchanged compiled selected model plus selectedModel.json, the original video, and an output JSON path. The script samples the first 25 seconds at 5 fps. This diagnostic replay is separate from production recording and does not require the user's phone to depend on a computer during use.
