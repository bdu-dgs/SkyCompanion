# SkyCompanion Risk Assessment v2 · 2026-09-26

The current risk assessment is experimental and based on camera images. Training candidate v2 has not replaced production v7; risk rules cannot recover poles, steps, or potholes missed by the model.

## Risk and Confidence

`backend/app/obstacle_risk.py` outputs a unified event: schema_version, track_id, risk_level, reason_codes, evidence_confidence, direction_frame, observed_at_s, expires_at_s, lifecycle, and speech_code. Observation time uses the Mac monotonic clock; phone speech separately carries the phone's captured_uptime_ms. These cannot be subtracted directly across devices.

| Level | Current meaning |
|---|---|
| R0 | No confirmed image conflict currently; this does not mean safe or passable |
| R1 | An image-region conflict observed continuously |
| R2 | A stable image conflict, accompanied by a near-field proxy cue or a candidate with a particular consequence |
| R3 | Permitted only with validated path, heading, distance, relative speed, and a complete response budget tied to the same target; the current field pipeline lacks these inputs |

Confidence is separated into presence, path, category, and distance. Detection category confidence is not converted into a probability of danger. The current path is only a user-selected image region; distance, user pose, and foot/body/head clearance are unmeasured. All directions use `camera_image`; there are no user-relative directions, meter measurements, or detour instructions.

A future R3 adapter must provide validated target association, ranging, approach speed, and measurement time, and compare TTC with the budget for image age, processing/playback wait, reaction, and stopping time. Bounding-box growth alone cannot activate R3. Synthetic tests cover this interface; they do not establish validated real collision warnings.

## Lifecycle and Scheduling

- Track objects inside and outside the region, check sustained entry into/exit from the image region, and prioritize the most relevant target.
- Do not repeat the same information merely because a timer expires; deduplicate matching risk/phrase/direction across tracking IDs. Ordinary new alerts at the same level default to at least 8 seconds apart. Low-priority R1 requires 1.2 seconds of persistence; R2/R3 still require at least 3 observations and 0.4 seconds. Risk escalation and validated R3 bypass the ordinary interval. The 8-second value is an adjustable interaction parameter, not a calibrated safety threshold. Do not retain old speech while waiting; reselect the currently valid risk when playback becomes possible.
- Retain `occluded_unresolved` when a target is occluded or missed; do not claim it has been passed. Only sustained visible image separation can end an image conflict, which still does not prove the user has passed it.
- `acknowledge` changes repetition preferences without clearing risk; `quiet` suppresses only automatic R1 alerts, retaining R2/R3 and fault status.
- Visual alerts must begin playback within a maximum validity period of 1.5 seconds; the phone also rechecks using its own capture clock. Keep at most one pending alert and discard expired ones.
- Model failure, paused analysis, stream loss, or stale observations make the risk level unavailable and cancel old speech. Recovery requires brief stability; status prompts do not repeat continuously.
- Current health checks verify connectivity, inference status, and reception time, but do not establish camera clarity, reliable physical localization, or an unobstructed scene. The age shown on the Mac is not end-to-end drone video latency.

## Operation

The **Risk evidence** area at desktop `/live` separately displays the level, perception health, confidence in four evidence dimensions, and direction basis. Buttons include Explain risk, Acknowledge, Quiet mode, Repeat alert, and Report false alert. Voice output can be Mac, iPhone, or Both; browser audio requires clicking Enable voice first.

The updated phone's **Phone voice · English** provides equivalent buttons and VoiceOver labels. Use these commands in an already-started voice-assistance session:

| Command | Behavior |
|---|---|
| SkyCompanion describe | Describe objects observed in the current image without treating every object as a risk |
| SkyCompanion why | Explain current risk evidence and its limits |
| SkyCompanion repeat | Recheck fresh evidence before repeating; do not replay expired messages |
| SkyCompanion got it | Acknowledge receipt while leaving the risk unresolved |
| SkyCompanion quieter / SkyCompanion normal alerts | Reduce low-level alerts / restore them |
| SkyCompanion mute / SkyCompanion unmute | Mute / restore alerts |
| SkyCompanion wrong alert | Save the current original frame, predictions, configuration, and available surrounding clips as unreviewed feedback |

Use generic obstacle wording when the category has not passed dedicated validation, for example:

> Caution. Possible obstacle on the left in the camera view. Your direction is unverified.

Fault wording: `Visual guidance is unavailable. Check your surroundings.` The system no longer uniformly instructs the user to stop for every risk. Speech uses fixed local phrases; remote text or prediction labels cannot become speech directly. Phone STT/TTS is currently half-duplex: recognition pauses during TTS to prevent echo. Buttons remain usable during this period; voice interruption is not supported and must not be claimed.

## Validation and Outstanding Work

Automated tests cover multi-target selection, region entry/exit, retention through occlusion, acknowledgement without clearance, risk escalation, expiry, stream loss/recovery, command responses, speech priorities, and protocol rejection. Scheduling was also verified by replaying saved original predictions, with results in `backend/data/obstacle_experiments/risk-v2-20260926/`. Replay did not rerun inference and has no risk ground truth; it is therefore neither a risk-accuracy measurement nor acceptance testing of actual listening.

The desktop service loaded risk v2 in this round; phone code is implemented and passed Swift tests and an iOS build. Another task is migrating the same project to fully on-device operation, so installation must be coordinated; listening results from the old phone version cannot serve as acceptance evidence for the new version.

Real-user/device acceptance still needs to cover first actual speech onset, comprehension, interruptions per minute, timely action, fault recognition, the full VoiceOver workflow, continuous microphone/speech operation across DJI Fly, and recovery. Localization, real walking boundaries, distance, and clearance are not integrated. The project cannot currently be marked “everything complete before drone field testing” or “safe independent guidance for blind users.”

References: [W3C: Minimize interruptions](https://www.w3.org/WAI/WCAG2/supplemental/patterns/o5p01-minimal-interruptions/), [Microsoft Soundscape](https://www.microsoft.com/en-us/research/product/soundscape/). The principles of reducing unnecessary interruptions and grounding directions are adopted; no claim is made to implement Soundscape spatial audio.

### Actual Validation Results in This Round

- Backend: 103 tests; frontend: 37 tests and production build; iOS VoiceEvent validation for the new levels and Swift tests passed, and an earlier generic iOS build passed. Final installation awaits coordination.
- Three saved-prediction segments contain 335 frames in total and last approximately 7.96 / 7.94 / 7.97 seconds. Initial event counts were 8/6/12; deduplication across IDs reduced these to 4/3/3; adding the minimum ordinary-alert interval reduced each to 1. First R2 events occurred .820 / .402 / .449 seconds after segment start. These are not risk ground truth, actual phone speech-onset latency, or field interruption rates.
- Actual localhost web interaction verified Quiet mode → Normal alerts transitions and unavailable results from Explain risk without input. The page was nonempty, had no framework error overlay, and had no console errors/warnings.
- Fixed old frames/explanations persisting after channel changes, missing replies to expired queries, and a second timeout truncating the health alert after stream loss; added regression tests.

Additional integration check: with limited Mac diagnostic video input through actual production v7, the backend returned R2 / presence=supported / path=image_proxy / category=unconfirmed / distance=unknown, with perception status limited. On completion it cleared old observations and restored unavailable. Audio was disabled during replay, so there was no acoustic acceptance test. Other on-device model development was running on the Mac simultaneously, so the sampled frame rate is not a performance benchmark. Web API and risk-button checks do not depend on native desktop unlock; native/real-device operation still requires available equipment and coordination with other tasks.
