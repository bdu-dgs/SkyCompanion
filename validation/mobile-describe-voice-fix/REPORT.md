# Drone voice and applied-area corrections

## Evidence and scope

The user reported audible automatic Cautions and a Listening indicator, but no describe response during a real drone session. The phone log confirmed an active microphone/audio engine and speech-start callbacks. The previous log did not record accepted voice commands, so it cannot establish the unique cause of the reported utterance failure. Do not infer an acoustic recognition success from that indicator.

Code inspection identified reproducible input and delivery failure paths: accumulated earlier speech failed the strict whole-utterance parser; duplicate identical partial results restarted the 800 ms commitment timer; descriptions could expire during synthesis and be treated as an audio-engine failure. Apple exposes transcription segment timing for utterance separation: [SFTranscriptionSegment](https://developer.apple.com/documentation/speech/sftranscriptionsegment).

The area investigation identified separate failures: no persistent applied-area storage; recordingRegion was cleared for local-video mode and not restored on entering drone mode; an unconfigured broadcast could encode full-screen initial frames; foreground preview requests could replace the saved external view with SkyCompanion's own UI. The same-session requirement now has explicit draft/applied state, rather than relying on a view-local editing state.

## Changes

- Extract a new wake utterance only after a measured pause; retain strict parsing when timing is missing and reject embedded commands without a boundary. Identical partial results do not postpone an existing commitment. No fuzzy brand spelling or bare-command activation was added.
- Log wake detection, accepted command, handler context, speech errors and description start without storing general ambient transcripts.
- Wait behind an existing higher-priority warning, then obtain a current matching scene. Preserve the 1.5-second observation deadline, retry on new evidence when synthesis misses it, and give an unavailable-view reply instead of treating stale evidence as a broken microphone.
- Keep draft and applied area separate. Reopening the editor in the same session restores the most recently applied rectangle. Persist applied values for later App launches. An unapplied full-screen edit does not overwrite the committed area.
- Restore the recording crop when switching from local video to drone, acknowledge actual writer configuration, and wait for configuration before encoding the initial live-broadcast frame. Mid-recording crop edits retain the encoder, timeline and audio.
- Retain the last full external DJI preview separately from the cropped user-selection image. Ignore preview arrivals while SkyCompanion is foreground and disable those foreground preview requests.
- Require selected user identity for drone directional alerts. Existing selected-person and duplicate-body exclusion remains unchanged. A new area clears obsolete wearer/path coordinates before sending settings; reapplying the same area preserves selection.
- No model, decoder, class map, inference threshold, alert-ranking policy or ordinary Caution cooldown changes.

## Executed checks

- 153 CaptureCore tests: speech boundaries, duplicate partials, description matching/freshness, required user identity, and the retained risk/command/navigation behavior.
- Native production crop-state harness: ten same-session reopens, draft discard, explicit full-image apply, invalid apply rejection, saved-state reload and corrupt-data rejection.
- Six native SwiftUI crop-slider boundary cases.
- Saved-movie tests using the production writer in system-mix and direct-audio fallback modes: 24 decoded frames, a 640×180 crop from a 640×360 input, no uncropped intro, pixel checks before/after a mid-recording crop change, invalid-crop rejection, and one playable mixed audio track. Tone checks verify microphone, source soundtrack and App speech as applicable. These are synthetic macOS checks, not a new iPhone Photos listening result.
- iOS Release App and broadcast-extension build.
- All 42 locked model/inference files match their recorded hashes; the two followed-user identity/tracking implementation files match the retained pre-rollback versions.

The new full-preview cache is limited to one JPEG per second during drone analysis and does not run for local-video input. Its performance impact on a physical drone session has not been measured. Phone command recognition, final acoustic continuity and Photos crop appearance still require the short real-device run in [the operation guide](../../docs/mobile-drone-recording-runbook.md).

Build/install/launch outcomes and test artifacts are recorded separately in this folder. Do not claim a field test from a successful build or installation.
