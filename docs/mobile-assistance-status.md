# Voice assistance status

Implemented 2026-09-26. This answers whether the system is operating, never whether the path is safe.

## Use on iPhone

All app commands and status replies now use English. The existing Settings → English voice picker selects an installed English voice. Previously saved non-English voice preferences migrate to Automatic; end an active session before changing voices. No extra status page is required.

Say **SkyCompanion, are you working?** or **SkyCompanion status**. Say **SkyCompanion unmute** or **SkyCompanion resume alerts** to enable spoken alerts. This does not resume paused analysis or repair an interrupted video feed.

## State contract

| Actual state | English response |
| --- | --- |
| Fresh current-session analysis and available risk processing, voice unmuted | Analyzing. Obstacle alerts are on. |
| Disconnected, absent, old-session/revision or ≥1.5s-old captured frame | The video feed has stopped. Obstacle alerts are unavailable. |
| Selected user cannot be matched to the current frame | I cannot confirm your position. Direction guidance is paused. |
| Otherwise operational but spoken alerts muted | Analyzing. Spoken alerts are off. Say SkyCompanion unmute to enable them. |

Idle, waiting, intentionally paused, model/risk failure, audio-session failure and unavailable path registration have separate honest responses. The feed freshness test uses the captured timestamp, not the time a delayed packet arrived. A feed failure takes precedence over tracking and mute; tracking/path failure takes precedence over mute. Optional path guidance does not affect ordinary camera-relative operation when it has not been configured.

While user/path tracking is unavailable, automatic direction speech is gated, old guidance is cancelled on transition, and repeat/path requests report unavailability. Normal command replies are not repeatedly cancelled on every lost-tracking frame. Other people remain in obstacle processing and enabled vibration can remain available.

## Proactive notices and mute

Feed, processing, user-tracking and path failures produce a short control notice even when obstacle speech is muted. The same continuous fault is announced once, marked delivered at the system speech-start callback. If speech cannot start it can retry while still current. A different fault can be reported; a brief recovery does not reset the latch. One second of healthy observations permits a new fault episode to be announced. Explicit status queries always re-evaluate current state and can be repeated.

Queued/ongoing status speech is cancelled if it no longer matches current state. Audio interruption or a disconnected output may make any audible notice impossible; the app cannot promise a spoken answer while microphone/audio services or the background session are unavailable. Stopping listening still ends assistance. Speech callbacks are not acoustic proof.

## Validation

- 90 CaptureCore tests passed (83 previous + 7 status tests): freshness boundary, future/NaN timestamps, wrong session/revision, disconnection, muted/healthy states, lost tracking, phase/processing/audio failures, path state, per-episode deduplication, recovery and strict bilingual parsing in that historical build. The English-only update reran the full current suite; see mobile-english.md.
- Release iOS build passed; installed-bundle verification checks resources/models/icon as before.
- Physical iPhone installation/launch results: `docs/validation/mobile-2026-09-26/assistance-status.json`.
- Not yet verified acoustically: English recognition on the actual phone, voice output in DJI Fly, fault notification heard once, audio interruption behavior. No new 10fps or long-duration claim.

## Phone acceptance steps

1. End any session, select English in the existing voice picker, and enable voice assistance. Missing local resources must show an explicit error.
2. Play a local video with voice commands enabled. Ask “SkyCompanion, are you working?”; expect the healthy response only while fresh results arrive.
3. Say “SkyCompanion mute”, query again, then “SkyCompanion unmute”. Expect muted and active answers; playback should continue.
4. Confirm the followed user and let that person leave/overlap. Expect one tracking-loss notice and no continued directional movement instructions. Repeating the query must answer current failure.
5. In DJI Fly, stop the broadcast. Expect one feed-loss notice if the voice session/output remains available. Query again; never answer healthy from old frames. Repeat failures must not create a notification loop.
6. Pause analysis; query should say paused. End assistance; microphone must be off. A stopped listener cannot hear subsequent queries until restarted.
