# Caution selection and repeatability review

Status: revised App built, installed and launched on the connected iPhone. Native offline reference-video tests passed the event-coverage checks below. Physical iPhone speech timing and repeated full-video playback have not yet been verified for this build.

## Scope and model integrity

The exact supplied video is identified in `manifest.json`: 52.081995 seconds, 1280 × 720, SHA-256 `667eb9dc0d4ff22ebfbe5d5d6527cb7407d24bb3ebf4235492b611f79ab6e4fa`.

YOLO remains `SkyWorld72_epoch15_640_FP32`. All 42 files in the existing model lock, including the inference implementation, matched their previous SHA-256 values. No weights, class order, input size, preprocessing, model confidence threshold, NMS or decoder were changed. `model-integrity.json` records every comparison. Changes described here are downstream tracking, risk selection and speech scheduling.

Recording, audio mixing, microphone/system/original-video sound, video-area controls and walking-navigation entry points were retained. Their physical operation was not re-certified by this offline experiment.

## What the independent visual review found

The central black-shirted person is the followed user. The user confirmed that they had not selected this person in the App. Without explicit selection, a camera-only detector cannot know which detected person to exclude.

The most relevant dynamic encounter is the green-shirted pedestrian approaching on the left around 15–19 seconds. Around 19.5–20 seconds that person has passed the walker and becomes closer to the trailing camera; a larger box then is not evidence of a new obstacle ahead of the walker.

The clearest static route constraint is the round tree planter on the left and traffic cone on the right around 27–31 seconds. Both sides matter. A steering instruction based only on the cone could disregard the planter.

The blue pedestrian on the left and stone column on the right are useful side-awareness events. Parked road vehicles, distant objects, and continuously visible side boundaries are not automatically the most dangerous objects. This video does not provide calibrated distance, collision time or physical clearance. None of these observations proves an emergency or a safe route.

See `independent-visual-review.md` for the original independent review. It inspected one frame per second plus denser samples around the green pedestrian and cone, rather than claiming every source frame was manually labeled. The detector calls the round tree planter `potted plant`; spoken names remain model predictions.

## Causes and implemented changes

1. **Unselected user.** The wearer can be announced as a person. The existing explicit selection link is now next to local playback controls, with a short explanation. No central-person auto-selection was introduced.
2. **Consumed but unheard events.** Previously a risk transition could be consumed while speech was busy or the cooldown was active. Current confirmed candidates remain eligible on subsequent fresh frames. The speech gate commits only when audio starts. Haptic admission has a separate gate. Expired observations are never replayed.
3. **Unstable winner selection.** Current spoken candidates are ordered by risk level, followed-user neighborhood priority, first observation, and deterministic geometry/track tie breakers. Same-class duplicate evidence is consolidated downstream; class changes no longer silently turn one risk track into another class.
4. **Camera foreground versus walker foreground.** When the selected user is tracked, image foot positions and lateral gaps restrict candidate relevance to the walker's neighborhood. Objects already behind the selected user cannot win merely because they are large near the camera. These are rear-following image heuristics, not calibrated ground geometry.
5. **Two-sided passage.** Two confirmed nearby boundary objects can form one named caution. The message names both; it does not claim measured narrowness, free passage or an authorized turn.
6. **Wearer tracker drift.** Weaker near-coincident person hypotheses and gradual optical box shrinkage could end tracking. The tracker corrects its box only after optical tracking and an unambiguous detector match agree. A new Vision sequence is used when reseeding to avoid accumulating trackers. Brief uncertainty may retain the same optical track for up to 800 ms, but authorizes no directional alert or wearer exclusion during that interval. Low confidence is not accepted as a valid identity. Persistent uncertainty requires reselection.
7. **Cadence.** The uncustomized ordinary reminder default is 4 seconds instead of 8. Confirmed action reminders retain a 4-second gap; a newly confirmed paired passage can use a 2-second minimum, still waiting for equal-priority speech and command responses. Repeated observations of the same track stay deduplicated. Explicitly customized Photon ordinary intervals are preserved; this change neither edits a server preference nor trains the model.
8. **Evidence alignment.** The saved spoken-alert snapshot now contains the selected spoken event's evidence, even when another object is the assessment's overall winner.

Apple documents that a newly supplied observation begins a new tracker, while a tracker-produced observation continues the existing one: [VNTrackingRequest inputObservation](https://developer.apple.com/documentation/vision/vntrackingrequest/inputobservation).

## Executed comparison

The shipping native inference implementation processed 261 source frames at 5 fps on the Mac using CPU-only Core ML. Its raw detections are preserved in `native-detections.json`. Rule comparisons reuse those exact detections. The followed-user tracker processes the actual source images, seeded with the explicitly reviewed first-frame person index 3, using a 640-pixel JPEG preview at quality 0.6 as in the App.

Baseline without selection produced six simulated cautions: left curb (0.4 s), right generic obstacle (8.8 s), front curb (17 s), right pole (25.2 s), left table (33.2 s), left awning (44.2 s). Merely shortening the gap produced more cautions and incorrectly included the central person at 4.4 s. That candidate was rejected. Both schedules are retained, including failures.

The final comparison includes explicit wearer selection as well as changed rules. It is not a claim that cooldown alone caused the improvement.

| Reviewed event | Final 5 fps simulated onset | Result across 5 fps and both 2.5 fps phases |
| --- | --- | --- |
| Blue pedestrian, left | 4.4 s | Left person at 4.4–5.0 s |
| Stone column, right | 8.4 s | Right pole at 8.4–9.0 s |
| Green pedestrian, left before passing | 16.4 s | Left person at 16.4–17.0 s |
| Planter before passage | 24.4 s | Planter alone or paired with cone within the reviewed window |
| Cone before passing | 27.8 s | Right cone or front planter-and-cone at 27.6–27.8 s |

These onsets assume 2.5-second speech with immediate software start. Repeating with 3.5-second speech still covers all five reviewed events; the cone/pair starts at 28.0–28.6 seconds. The comparison does not measure acoustic onset or live iPhone performance.

Three identical-input runs produce identical speech sequences. Independently rerun wearer tracking at 5 fps and both 2.5 fps phases yields 258/261, 128/131 and 129/130 tracked samples respectively. Remaining sampled frames report temporary uncertainty and pause directions; all recover the existing optical track in this clip. Visual identity outside this clip is not certified.

The final 5 fps schedule has 14 cautions; the full list is in `revised-schedules.json`. Not all are the most important hazards. The beginning and end include secondary boundaries, some with unverified detector names. Changing the sampling phase can select a curb instead of a column, a road car, or a different distant boundary. Therefore **arbitrary real-time playback is not guaranteed to produce an identical complete list**, and **the reference clip has not proven general safety or perfect object naming**.

## Checks and delivery

- 149 Swift core tests passed, including stale events, command protection, haptic/speech separation, distinct people on the same side, passed-object exclusion, duplicate wearer evidence, paired boundaries and cooldown behavior.
- Both reviewed-event coverage reports passed: `event-coverage.json` and `long-speech-coverage.json`.
- Xcode Release build passed for the App and broadcast extension: `xcodebuild.log`.
- 42 model-related hashes unchanged: `model-integrity.json`.
- Installation and launch succeeded: `install.json`, `launch.json`. Installation occurred after confirming that no SkyCompanion broadcast extension process was running.
- New physical iPhone playback, live drone testing, end-to-end audio onset, long-duration performance and new-scene accuracy remain unverified.

## How to test a new video

The App does not contain this clip's filename, timestamps, expected labels or acceptance windows. `reviewed-events.json` is an offline evaluation fixture only. New videos use the same frozen general rules without retraining or per-video tuning.

For a rear-following video, open **Test a video → Choose a video → Start analysis → Select followed user**. A sighted helper freezes the latest analyzed view, selects the followed person, presses **Confirm followed user**, then **Resume video analysis**. Optional path setup is not needed for this caution-only comparison. Seeking, restarting and importing another video clear earlier identity observations; select again. A video without a visible followed person can run in camera-only mode but does not establish walker-relative relevance.

For engineering evaluation, review a new video before looking at model output. Record event time windows, obstacle identity, camera direction, whether the walker has already passed, and which objects actually constrain the route. Keep unseen clips separate from the reference used to adjust rules. Include other people crossing the user, occlusion, turns, columns, poles, cones, parked vehicles, a clear path, and a different rear-following camera height. Only validated independent clips can support wider performance claims.

1. `scripts/replay_caution_video.swift` accepts any video duration and records native detections at 5 fps using the existing compiled model bundle. It performs no conversion or training.
2. `scripts/track_followed_user.swift` accepts the cache, original video, output path and an explicitly reviewed first-frame person index, with optional stride and phase. It never selects a user automatically.
3. `scripts/evaluate_caution_schedule.swift` compares repeated fixed input and two sampling phases with supplied tracking results; optional speech duration tests scheduler sensitivity. No audio is generated.
4. `scripts/audit_caution_replay.py` compares schedules with separate reviewed event windows. A missed important event, wrong side, wearer-as-obstacle or late warning remains a failure to investigate; do not just lower all cooldowns until a clip passes.
5. Finally replay the same clip on the disconnected iPhone several times, keeping voice settings and user selection consistent. Log actual started speech separately from candidate detections. Deliberately ask `SkyCompanion describe` once to check that a protected response does not revive an obstacle after it has passed.

Example coverage command:

```sh
python3 scripts/audit_caution_replay.py \
  validation/mobile-caution-consistency/reviewed-events.json \
  validation/mobile-caution-consistency/revised-schedules.json \
  /tmp/coverage.json
```

Passing this command means the reviewed event windows are covered in the recorded simulation. It does not mean the sidewalk is safe or that every future scene will be interpreted correctly.
