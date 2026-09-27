# Current mobile alert policy: selective command-era rollback

This version restores the application-side recognition processing and alert scheduling associated with the command-list response at **2026-09-27 03:14:52 UTC**, with the exceptions explicitly requested by the user below. It is not a model rollback.

## Restored

- The original risk monitor, image corridor eligibility, confirmation, winner selection and content deduplication.
- The original eight-second default alert cadence and speech/command priority behavior. Explicit supported Photon preferences remain intact.
- Later general candidate retries, followed-user neighborhood ranking, paired-passage events and the four-second default were removed. Followed-user identity fixes are retained as requested below. A bounded retry now applies only to degraded camera alerts that wait behind a tracking notice or command response, as described below.
- Generic Caution speech and repeat responses. Standard examples: `Caution left. Check your path.`, `Caution right. Check your path.`, `Caution front. Check your path.` No appended detected class names such as Person, Car or Pole.
- Walking guidance still uses the existing direction/action phrases, such as `Caution front. Keep left.` It no longer inserts a detected object name.

## Explicitly retained

- Stop recording and save to Photos.
- Microphone, system/App speech and original-video soundtrack recording, including the current audio routing and fallback implementation.
- Direct video-area adjustment, mid-recording crop changes, and the Apply-area slider crash fix.
- Walking navigation UI and navigation voice commands.
- The current curb-context correction: a curb rectangle alone does not trigger an automatic obstacle caution. Curb hints can still block an unverified walking route; independently confirmed path-boundary warnings remain enabled.
- Followed-user exclusion: after explicit selection, the selected person and weaker duplicate detections of the same body are excluded from obstacle alerts, walking obstacle candidates and scene descriptions. Other pedestrians remain eligible. Optical tracking corrections are retained. Identity uncertainty pauses walking instructions and all people alerts, resets incompatible risk tracks, and never switches automatically to another person. Fresh, confirmed non-person obstacles remain eligible for camera-relative speech and haptics.
- Drone people alerts and walking guidance require confirmed user identity. Before selection or during tracking loss, all person candidates are excluded from automatic obstacle risk; non-person camera alerts remain available. Applying a different crop clears old user/path coordinates; applying the identical crop preserves selection.
- Existing appearance, setup and recording screens, including the accessible followed-user selection link.
- All model weights, class order, preprocessing, inference settings and decoder code.

## Camera-only fallback during user/path uncertainty

- The detection model, input/output processing, risk thresholds, confirmation, ranking, curb filter and default eight-second cadence are unchanged.
- A fresh analyzed view can support camera-relative obstacle warnings even when user tracking or the configured walking path is unavailable. Example: `Caution. Camera left.` Camera left/right/front describes the image; it is not a user-relative movement instruction.
- While identity is unconfirmed, all people are excluded from automatic obstacle risk. After the selected user is reliably matched again, the selected body stays excluded and other pedestrians become eligible again. Losing path confirmation alone does not exclude other people if user identity remains reliable.
- Walking instructions remain paused until their identity/path requirements are satisfied. Muting, source loss, stale frames, paused analysis, voice-session failure, and existing alert admission preferences still apply.
- The first fallback warning can wait behind the tracking notice or a protected command response. It is reconsidered only while the same track, class and direction remain observed in current fresh frames, for at most eight seconds from the original event. Occlusion, a source/revision change or mode change clears it. The original 1.5-second frame validity applies to each delivery; there is no stale speech queue.
- `status` and the one-time interruption notice explain the remaining camera capability and paused walking/people capability. The existing status area shows camera-only operation without new controls.
- Diagnostic samples include wearer/risk states and camera/walking capability. Alert decisions include cooldown, mute and speech occupancy; speech admission is recorded separately from the speech-start callback. Neither software event proves acoustic output.

See [the camera fallback report](../validation/mobile-camera-alert-fallback/REPORT.md) for regression evidence and remaining real-drone verification.

## Commands

Enable voice commands and wait for Listening for commands. English commands begin with SkyCompanion.

| Command | Behavior |
| --- | --- |
| describe / what is ahead | Describe objects and camera directions in a fresh view; object names remain in this explicit response. |
| status / are you working | Report actual assistance availability, not path safety. |
| repeat | Repeat a currently valid alert with generic caution wording. |
| why | Explain the current alert evidence. |
| mute / unmute | Disable / enable automatic voice alerts. |
| quieter / normal alerts | Reduce / restore low-level reminders, not playback volume. |
| got it | Acknowledge hearing an alert, without declaring the obstacle resolved. |
| wrong alert | Save feedback without changing the model. |
| pause analysis / resume analysis | Pause / resume analysis and local video; keep command listening available. |
| path | Report configured user/path status. |
| end assistance / stop listening | End assistance and close the microphone. |
| trip summary / ask assistant why | Use the configured Photon assistant service; these are not offline-only features. |

Explicit scene descriptions and assistant responses may still name objects. Removing class names applies to the added automatic Caution naming feature, not to the describe command.

## Verification and limitations

See [the selective rollback report](../validation/mobile-selective-command-rollback/REPORT.md). Source backups preserve the previous implementation. Five implementation files exactly match the saved command-era reference; the remaining differences retain curb handling, user identity fixes and their pipeline/delivery integration. Recording/audio/crop/navigation support files are unchanged, and the mixed session controller's recording, crop and navigation methods are unchanged.

That source comparison describes the rollback checkpoint. The subsequent [drone voice and applied-area update](../validation/mobile-describe-voice-fix/REPORT.md) changes command input/delivery, crop persistence, preview retention and recording configuration. It retains the model, risk ranking, generic Caution wording and eight-second default cadence. Follow the [current recording runbook](mobile-drone-recording-runbook.md) for phone operation.

For the rear-following reference video, select the black-shirted central walker once: **Test a video → Start analysis → Select followed user → Use latest analyzed view and pause → select the walker → Confirm followed user → Resume video analysis**. This only requires person selection, not optional path configuration. Selection is needed for each new source/selection reset; central position alone does not establish identity. Raw YOLO detections remain intact for inspection and tracking.

Because curb filtering is intentionally retained, this build is not expected to reproduce the old version's curb alerts or every historical speech timestamp. Live sampling, speech occupancy and saved preferences can also affect the spoken sequence. The rollback does not assert that the old rules always select the most important obstacle. Physical iPhone listening is separate from compilation, synthetic recording checks and cached-detection replay.
