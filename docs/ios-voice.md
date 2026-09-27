# Legacy iPhone speech and mobile controls

Historical update, 2026-09-26. This document describes the former SkyCompanion/Mac receiver workflow, not the current phone-only SkyCompanion build; see [current implementation](mobile-app-implementation.md). At this milestone the user heard local/remote sound checks and received an answer to SkyCompanion describe while Bilibili was foreground in landscape. That was one preliminary cross-app STT → server → phone TTS observation. Revised structured descriptions/new voices, long silence, interruptions and recognition accuracy still required retesting.

## Two operating modes

1. **Foreground receiver:** Enable phone voice receiver starts networking/output without the microphone; it pauses when leaving SkyCompanion.
2. **Continuous voice assistance:** The user enables Continuous voice assistance · microphone while SkyCompanion is foreground and grants microphone/Speech Recognition permissions. AVAudioEngine actually records command audio; SFSpeechRecognizer requires on-device English, with playAndRecord/voiceChat and main-app background audio. Switching to Bilibili or DJI Fly does not intentionally disconnect the active session/socket. No silent loop or fake background task is used.

The microphone stays active during silence and alert muting. Audio is not saved/uploaded. ReplayKit sends video only. Missing local English recognition, denied permission or repeated recognition errors stop assistance without cloud fallback.

Apple documents continuation of already-started recording with background audio; declaring the mode alone does not guarantee perpetual execution or cross-app success. [Background recording](https://developer.apple.com/documentation/avfaudio/avaudiosession/category-swift.struct/record), [on-device recognition](https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/requiresondevicerecognition). Official documentation was checked on 2026-09-26; `requiresOnDeviceRecognition` is enabled only when supported.

## Historical phone procedure

1. Keep the receiver reachable and choose Check connection in SkyCompanionCapture.
2. Under Phone voice · English, select Play local sound check and confirm Stop. Obstacle ahead. is audible from the phone/headphones. This tests audio and does not report an actual obstacle.
3. Enable the phone voice receiver, choose Phone or Both output and Send receiver sound check. This tests server-to-phone delivery without desktop interaction.
4. Select an installed Enhanced/Premium English voice or Automatic, adjust Speech speed and audition. Download system voices in iPhone Accessibility settings, return and Refresh installed voices. The app cannot download them automatically. Enable continuous voice assistance, grant both permissions and confirm Listening on this phone. Resolve unavailable/permission errors; the ordinary receiver switch does not substitute for listening.
5. Choose Arm landscape video test · center area. This manually selects full landscape plus a central experimental corridor, not an automatically recognized road. If necessary start broadcasting within 120 seconds, then play Bilibili landscape. This legacy mode stopped on portrait to avoid interpreting the settings page as a street; each new broadcast needed reconfirmation. The current app supports portrait too.
6. Return to SkyCompanion to pause. Disabling continuous speech actually closes the microphone; stop screen sharing separately using the system indicator.

In this legacy flow **vision remains on the configured receiver**, not phone/cloud migration. Arming is for supervised recorded-video tests, not drone/body calibration or automatic path detection.

## Legacy English commands

| Command | Behavior |
|---|---|
| SkyCompanion repeat / repeat alert | Repeat only a still-valid alert; otherwise report no recent valid alert |
| SkyCompanion mute | Mute locally and request receiver mute; listening continues |
| SkyCompanion unmute | Request Phone alerts again |
| SkyCompanion describe / describe ahead | Request stable current-view objects and approximate image directions |
| SkyCompanion what is ahead / what's ahead / what obstacles are ahead | Query the same current camera view |
| SkyCompanion what is around me / what obstacles are around me | Still camera-only, not 360-degree body awareness |
| SkyCompanion stop listening | Stop continuous microphone assistance; the foreground receiver may still receive audio |

These are finite aliases, not cloud-LLM or open-ended scene questions. In the camera view limits scope; unseen surroundings cannot be declared safe. Current mobile commands use the SkyCompanion wake phrase.

Descriptions are separate from risk: stable people/cars/traffic lights may be described without a corridor risk. The server sends whitelisted kind/count/direction/vertical, and the phone forms up to three short groups, such as In the camera view: several people ahead, and a traffic light on the right. Unverified classes become possible obstacle. Traffic-light descriptions do not infer color or permission. With no stable identification, the reply is I cannot identify objects reliably in the current view; lack of risk does not mean no objects.

Only whole utterances containing SkyCompanion execute; isolated stop/mute/describe in media do not. Partial transcripts must remain stable 800 ms, or be final. Recognition renews every 50 seconds and stops on repeated failure. These safeguards are not noisy-environment/media/all-headphone accuracy acceptance.

TTS is half-duplex: suspend STT input, cancel old recognition, then resume 500 ms after speech for acoustic tail. The real microphone session remains active. Echo control is enabled but needs separate speaker/headphone tests. Voice interruption during speech is not supported; UI stop is always available.

## Expiry, coordinates and interruptions

- Risk, tests, acknowledgements and descriptions use local AVSpeechSynthesizer with installed Premium/Enhanced English preference and user voice/rate choice. Legacy Windows WAV assets are reference material only; [TTS provenance](skycompanion-tts.md) documents licensing. Old asset names act as protocol direction whitelists, not WAV playback.
- Unverified classes are not spoken as facts. Left/right/ahead are camera directions, not drone-to-user body directions.
- Risk TTL ≤1500 ms; latest event only, no audio backlog, bounded event-ID deduplication. Real risk can interrupt descriptions/tests.
- `captured_uptime_ms` uses the same phone systemUptime and maximum observation age ≤1500 ms. Late arrival grants no new lifetime; future/restarted clocks are rejected. Check expiry after audio initialization.
- HTTP descriptions and no-stable-object replies require valid capture uptime. Speech keeps original expiry while synthesis initializes; a timer cancels late speech and didStart checks again. An unconfirmed-obstacle compatibility response does not establish a clear route.
- Disconnect cancels playback and reconnects without replay. Mute discards rather than queues. Manual repeat never renews old evidence.
- Calls stop recording/output. Resume only when allowed and foreground; background interruptions may require returning to SkyCompanion. Never pretend listening continued.
- Headphone loss stops assistance/output to avoid sudden speaker playback. Recheck route and restart; force quitting cannot automatically recover.
- received/started/completed are code/synthesizer callbacks, **not measured audible output**.

## Legacy endpoints

Use the same pairing Bearer credential:

- WebSocket `/api/live/voice`: voice_event, voice_stop, voice_state, voice_ack; voice_capability is foreground_only or active_speech_session, describing software mode only.
- `GET /api/live/mobile/state`.
- `POST /api/live/mobile/command`: voice_output + output, voice_test, repeat, describe, mute, unmute, start (roi/corridor), pause.
- Speech whitelist: scene_summary, no_stable_objects, unconfirmed_obstacle, no_confirmed_obstacle, vision_unavailable, no_recent_alert. Direction ahead/left/right, vertical upper/middle/lower, count 1–3, at most three objects. Unknown/out-of-range values are rejected; arbitrary message text is display-only.

## Historical verification and field work

22 CaptureCore tests passed: queues/TTL/deduplication/whitelists, complete-command rejection, question aliases/camera boundaries, free-text rejection, structured scene bounds and monotonic late/restart protection. Generic unsigned iOS arm64 build passed (`/tmp/skycompanion-ios-scene-build.log`); it did not execute recording or background work.

Preliminary user evidence covered local/remote sound and a Bilibili-background describe reply. New voices and STT accuracy remained untested, along with prompts after 30/120 seconds or 15 minutes of silence, calls/lock/Bluetooth loss, no stale recovery speech and simultaneous broadcasting/media/speech resources.

Field order: local sound → receiver sound → each command → landscape Bilibili/background alert → 120-second silence → Wi-Fi loss/recovery → call/headphone loss → foreground restart → 15-minute record. Record what was heard separately from acknowledgements; stop a failed run and do not mark untested items passed.
