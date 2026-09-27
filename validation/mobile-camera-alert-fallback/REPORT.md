# Camera obstacle alerts during wearer/path uncertainty

Date: 2026-09-27

## Request and observed evidence

The user reported that local-video Cautions worked while real DJI Fly Cautions did not, despite selecting the followed user. The requested change explicitly excludes modifying the model.

The earlier phone session showed continuing inference and accepted describe/speech-start callbacks, but no Caution. Its performance log lacked wearer/risk/admission state, so it does not prove the unique cause of that specific field run. The saved Photon preferences were revision 0, standard verbosity, no muted categories and an eight-second interval.

Code inspection established two blanket blockers: selected-user loss reset the entire obstacle risk engine on each frame, and the session controller suppressed all directional speech/haptics when wearer/path status failed. The drone requires wearer identity, while ordinary unselected local-video testing does not. This patch removes those broad blockers while preserving the narrower requirements for walking instructions and people alerts.

## Behavior implemented

- Detection outputs are unchanged. A small risk-input wrapper continues excluding the selected person and weaker duplicate body detections when identity is reliable. During identity uncertainty it excludes every person, while fresh non-person detections still pass through the unchanged risk heuristic.
- Camera alert availability now checks the actual session, revision, source, frame freshness, analysis, risk health and required voice session. Walking availability additionally checks wearer and configured path status.
- Camera-only speech uses `Caution. Camera left/right/front.` It does not provide Keep left/right or Go straight instructions. Existing normal speech, confirmation/ranking, reduced curb alerts, preferences and default eight-second cadence remain intact.
- On entering/leaving walking or person-exclusion modes, incompatible risk tracks are cleared. Obstacles must be freshly confirmed after the scope change.
- A camera-only event blocked by the tracking notice or a protected command response can be retried for at most eight seconds from the original event. The same obstacle must remain observed with the same track, class and direction in fresh current frames. A retry carries the current observation timestamp and its normal 1.5-second expiry. Occlusion, stale frames, source/revision changes and leaving camera-only mode clear pending evidence. Ordinary alert admission is unchanged.
- Status responses and the existing status text distinguish camera alerts from paused walking/people capability. No extra UI controls were introduced.
- Diagnostics now record wearer/risk states, camera/walking capability, mute, speech occupancy, admission decisions and speech acceptance. Software acceptance and start callbacks are distinct from actual audible output.

## Preserved scope

No changes to model weights, class order, inference preprocessing/thresholds/decoder, the wearer tracker, recording/video crop/audio implementation, navigation, command parser, or ordinary alert cadence. The session controller changes only risk delivery, operational status, current-alert repeat handling and diagnostics; recording and crop methods are untouched in the before/after diff.

Before-source archive: `.skycompanion-live/camera-alert-fallback-20260927/source-before.tar.gz`.

## Executed checks

| Check | Result | Evidence |
| --- | --- | --- |
| CaptureCore regression suite | 162 tests, 0 failures; native Swift execution | [core-tests.log](core-tests.log) |
| New fallback cases | Nine tests: person exclusion/recovery, ordinary-local compatibility, fresh confirmation after walking failure, capability gates, waiting behind status speech, stale/occluded/source-changed retry rejection, camera wording | `ios/CaptureCore/Tests/CaptureCoreTests/MobileCameraObstacleTests.swift` |
| Release iPhone build | Exit 0, BUILD SUCCEEDED | [release-build.log](release-build.log) |
| Model and inference source lock | All 42 protected files match the prior SHA-256 lock | [model-integrity.json](model-integrity.json) |
| Packaged model in App and broadcast extension | Both manifests and compiled weight bytes match the original epoch-15 FP32 model | [bundled-model-integrity.json](bundled-model-integrity.json) |
| Preinstall recording check | Phone process listing succeeded; no SkyCompanion broadcast extension running | [preinstall-recording-check.json](preinstall-recording-check.json) |
| Connected iPhone installation | Successful | [install.json](install.json) |
| Installed App launch | Successful | [launch.json](launch.json) |

Installed model: `SkyWorld72_epoch15_640_FP32` / Street72 epoch 15. A successful launch does not establish a completed drone/audio field test.

## Remaining device acceptance

The user has been asked to start the normal voice-assistance/broadcast workflow, keep DJI Fly in front, query `Sky Companion, status.`, and report whether Cautions are audible during ordinary testing. This new build's real-drone acoustic result is pending.

If silence remains, read the matching session's new wearerState/riskState/riskHealth/cameraAlertsAvailable samples plus alert_decision, alert_delivery and speech-start events. Do not infer a model problem or lower detection thresholds from silence alone. Camera-only mode intentionally does not warn about people whose identity is uncertain, and a curb rectangle alone remains ineligible.
