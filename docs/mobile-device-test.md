# SkyCompanion iPhone device testing

These are chronological 2026-09-26 milestone records. Later updates do not turn earlier untested items into passes. Current language/visual changes have separate reports.

## Initial installation

- User connected and authorized testing on iPhone 15 Plus, iOS 18.7.8, Developer Mode enabled, USB.
- Xcode 27.0 (27A266a), SkyCompanion scheme, Release signing build passed.
- App and extension installed; devicectl launched the main app without LLDB. A physical-device screenshot showed the home page. Both bundles passed static model/resource contracts.
- Initial profile expiry: app 2026-10-02 22:26:30 UTC; extension 22:26:52 UTC. Re-sign/reinstall as needed; later profiles may differ.
- Evidence: ignored `.skycompanion-live/device-test-2026-09-26/`, including receipts, profile audit and screenshots. Build log `/tmp/skycompanion-device-build.log`.

The user heard the sound check; a screenshot showed Listening on this iPhone · English. Logs recorded playback callbacks and DJI session preparation. At this point command accuracy, offline operation, broadcasting, device inference, rate/memory and the DJI loop were unverified. The next steps were source preview, resources/functions, 30-minute stability and ten-minute drone recording. Installation is not closed-loop acceptance.

The diagnostic connection subsequently failed and devicectl reported unavailable; this did not establish app/extension failure. Reconnecting USB could resume log export. Sound-check success was not model-inference evidence.

## Analysis-state presentation

Prepared-but-not-analyzing, waiting-for-first-frame and actual analysis became distinct. Broadcast connection, a preview or pressing prepare cannot report success. The status card retains accepted fresh-frame count and last analysis time as historical activity after pausing; a new attempt/source resets them, and they never feed speech/risk decisions.

The historical button became `Prepare to analyze in DJI Fly`, with `Ready. Not analyzing yet — open DJI Fly now.` Connection loss during start becomes unavailable; first-frame timeout is 30 seconds, running freshness 1.5 seconds.

Release signing, 49 core tests and both-target resource checks passed (`/tmp/skycompanion-status-build.log`, `/tmp/skycompanion-status-tests.log`). These core tests did not cover new SwiftUI presentation. The app reinstalled and launched on the same phone (`/tmp/skycompanion-status-install.json`, `/tmp/skycompanion-status-launch.json`). A later screenshot failed due to CoreDevice/Mercury connectivity; neither app failure nor visual/drone acceptance was inferred.

## Portrait source and first device inference

Real logs repeatedly reported `Source is not landscape`; the user confirmed DJI remained portrait. The implementation incorrectly forced landscape. A separate broadcast pause was also logged.

At 14:38:56–14:39:09 and 14:39:34–14:39:44, first-frame confirmation, continued inference and R2 events established actual extension inference/result delivery. Stable segments were about 3.8–3.9 fps and 245–255 ms/inference. They did not establish source identity, accuracy, audible latency or long stability and missed 10 fps. Raw record: `.skycompanion-live/device-test-2026-09-26/source-layout-failure-and-inference.json`.

The fix accepts portrait/landscape ROI, requiring stable dimensions/orientation for 500 ms before start; changes after acceptance still pause for reconfirmation. Error speech identifies the failure. 53 core tests, including four layout regressions, Release build and resources passed (`/tmp/skycompanion-portrait-tests.log`, `/tmp/skycompanion-portrait-build.log`). Installed receipt: `/tmp/skycompanion-portrait-install.json`. Physical DJI portrait retest remained pending.

## Repeated speech interruption

Logs showed several R2 utterances starting within one second. Equal-priority preemption (`incoming >= priority`) and event-UUID-only deduplication let new/recreated tracks repeatedly interrupt Caution.

The fix requires strictly higher automatic priority to interrupt, spaces ordinary events by eight seconds and deduplicates direction/consequence content for 20 seconds regardless of track ID. Escalation bypasses cooldown; unverified R3 remains rejected. Suppressed events are discarded, never queued for replay. Explicit repeat checks fresh evidence.

At this milestone wording became Possible obstacle … in the camera view, reducing repeated Caution/disclaimers while retaining camera-coordinate limits in calibration/help. Evidence calculations did not gain speed, distance or time-to-collision estimation. Novelty voices were excluded, automatic selection preferred Premium/Enhanced/Standard and en-US, and explicit normal-voice/rate choices persisted. The historical default rate was .44; later voice changes are documented separately.

58 core tests, including five cadence regressions, Release signing and bundle checks passed (`/tmp/skycompanion-speech-tests.log`, `/tmp/skycompanion-speech-build.log`). Audible onset and perceived naturalness still required listening.

## Quiet alerts, playback and performance

- Continuously observed same-direction/consequence hazards no longer repeat periodically, even with new track IDs. Occlusion does not mean resolved. Twenty seconds is a deduplication window after interrupted observation, not a periodic reminder timer; escalation remains.
- Camera left/center/right combined with uncertain obstacle/low/ground-level/overhead/vehicle groups. Stable class confidence ≥.55 is required; otherwise use obstacle. No approach speed, metric distance or detour claim. Group accuracy was not independently accepted.
- The device selected Samantha en-US Standard at rate .44. Enhanced/Premium availability and naturalness were not confirmed.
- After three utterances, logs showed frame invalidation within seconds without an explicit pause command. The audio-session fix stopped deactivating AVAudioSession after TTS during video playback. Actual replay confirmation was initially pending.
- Tensor-type/pointer caching, type-specific scans and CVPixelBuffer reuse retained the same 960 FP16 model, thresholds, all 115 classes and masks. Submission ceiling became 15 fps, still one processing/one latest pending frame.
- Six Mac rotation/crop cases matched value-for-value; median complete processing improved 91.06→50.08 ms. `validation/mobile-2026-09-26/typed-tensor-optimization.json`. Small parity samples are not full accuracy, and Mac speed is not phone FPS.
- 60 core tests, ten actual localhost checks, Release and bundle checks passed. An earlier wording-capitalization assertion failed, was corrected and passed on rerun.
- A 30-minute local-video loop prevents auto-lock and pauses when complete; locking, leaving, pausing or errors end the test. Per-second inference stages, FPS, player time, thermal state, battery and memory go to `Documents/SkyCompanionDiagnostics/performance-<sessionID>.jsonl`, without saving video. The long run was not completed.
- The combined version installed/launched (`/tmp/skycompanion-performance-install.json`, `/tmp/skycompanion-performance-launch.json`); at that point its phone performance and uninterrupted playback were pending.
- `python3 scripts/summarize_mobile_performance.py <exported-performance.jsonl>` excludes five seconds after configuration changes and reports stage P95, steady FPS, sampled memory and interruption evidence. Five synthetic checks reject missing completion markers/logs/errors as long-run passes; synthetic checks are not device evidence.

## Haptics and command protection

New-alert vibration defaults on, with Settings and Test vibration. The system haptic API is permitted during listening; logs do not establish physical sensation or background delivery while DJI Fly is foreground.

During a recognized Sky Companion command opening or an explicit spoken reply, ordinary R1/R2 alerts use vibration without interruption. A verified urgent R3 may interrupt. Haptics use freshness, semantic deduplication and the eight-second ordinary-event interval; no per-frame or deferred replay. Mute spoken alerts leaves enabled vibration and listening on; vibration has its own switch.

61 core tests, Release signing and bundle checks passed; installed `/tmp/skycompanion-haptic-install.json`. Actual sensation, command protection and background haptics remained unaccepted.

## Short optimized phone run

One real local-video run provided 125 one-second samples, 120 after warmup. Steady FPS median 10.028, range 9.894–10.594. Processing median 48.38 ms, P95 55.86 ms; model median 35.72 ms, postprocessing 10.37 ms. Thermal samples were nominal (0); maximum sampled resident memory 177.875 MB, not physical peak.

Frames continued after speech; the run ended by user lock, unlike the previous immediate post-speech failure pattern. Report: `validation/mobile-2026-09-26/iphone-short-video-performance.json`; raw `.skycompanion-live/device-test-2026-09-26/performance-short-local-video.jsonl`. No 30-minute start/completion markers existed, so this was a short local-video result, not long-run or extension performance acceptance.

YOLO has no depth output. A separate monocular depth model needs calibration and measurements; camera-to-obstacle distance is not user-to-obstacle distance.

## Depth and confirmed-path experiment

Installed/launched on the same iPhone 15 Plus (`00008120-001A10D002E2201E`). Settings → Depth and path testing. YOLOE 960 FP16 unchanged; Metric VKITTI Small 392 FP32 is off by default, at most once every two seconds. FP16/mixed candidates failed conversion gates and their reports remain. Four FP32 conversion cases passed, with no measured-distance labels.

A helper selects the person and quadrilateral corridor. Vision registration/tracking, YOLO matching and continuous confirmation do not automatically replace a lost identity. SkyCompanion path was added. This milestone was not automatic crosswalk detection, body-relative turning or crossing permission.

67 Swift tests, ten real localhost checks, six depth-evaluation boundary tests, Mac synthetic translation registration, both Release targets and resources passed; installation/launch passed. Phone depth-on FPS/thermal/memory, long extension execution, drone identity/deviation remained unmeasured. The user was asked to run the same video about 60 seconds with depth off/on; old ~10 fps cannot be reused for the new depth configuration.

Guide: `mobile-depth-path-testing.md`; evidence `validation/mobile-2026-09-26/depth-path-status.json`.

## Two-part rear-following prompts: historical pending-install milestone

Added Caution front. Keep left/right. and Caution left/right. Go straight. for near-side obstacles with a confirmed front corridor. These require the selected person, registered manually confirmed region and rear-following setup; unknown/blocked evidence falls back to Check your path. See `mobile-short-guidance.md`.

78 Swift tests, synthetic registration/changed-ground rejection, both Release targets and bundle checks passed. **At this milestone the build was not installed, heard or field tested** because devicectl reported the physical phone unavailable. A generic device bundle existed; the previous version's installation did not apply. Evidence: `validation/mobile-2026-09-26/short-walking-guidance.json`. Later installation records live in their own reports.
