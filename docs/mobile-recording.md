# Stop recording and save on iPhone

Current operation checklist: [Drone recording and voice checks](mobile-drone-recording-runbook.md).
The latest update keeps the last applied rectangle when reopening the editor in the same session, persists it for later launches, restores it after local-video testing, and waits for the recording writer's acknowledgment. A new live broadcast waits for its crop configuration before encoding its first frame. The editor preserves the last external DJI preview while SkyCompanion is foreground. Saved-file crop/audio tests are recorded in [the update report](../validation/mobile-describe-voice-fix/REPORT.md); physical phone listen-back still needs the short preflight test.

SkyCompanion now saves a screen-broadcast movie to **Photos** when the user taps
**Stop recording and save** in Connect drone, or **Stop recording and end
assistance** in Session controls. The button stops analysis and the microphone,
waits for the recording outcome, then ends assistance. English voice commands
`SkyCompanion end assistance` and `SkyCompanion stop listening` stop assistance
and its microphone, but do not stop the broadcast. Use the recording-stop button
to save. Stopping the system screen broadcast also finalizes it.

## Use

1. Open Connect drone → Enable voice assistance. Allow **Add Photos** when asked.
   This grants permission to add the recording, not browse existing photos.
2. Start the SkyCompanion screen broadcast from the system broadcast control. Recording starts in the broadcast extension; analysis does not have to be armed first.
3. Open **Choose video area** at any time. Move the box, resize its corner, or use
   **Precise adjustment**, then tap **Apply video area**. It works before a preview
   arrives using a clearly labeled phone-screen guide. Once DJI Fly has been shared,
   the last received preview is available. No overlay is drawn over DJI Fly.
4. Use DJI Fly normally. An applied area crops analysis and future saved video
   frames. **Use full image → Apply video area** restores the full screen. Local
   video tests record the full test UI. App transitions remain part of recording.
5. Return to SkyCompanion and tap **Stop recording and save**. Wait for
   **Video saved to Photos.** Find the movie in Photos' recently saved videos.

The movie includes your voice from the active voice-assistance microphone and
SkyCompanion's actual rendered answers and alerts. There is no additional system
**Microphone On** step for these two sources. ReplayKit app/device audio is also
included when provided by iOS. Keep voice assistance enabled during recording.
The microphone is captured once for both commands and recording; recognizing a
command is suspended during a spoken reply, but audio recording continues.

The new path addresses a confirmed failure in the previous build: Photos saving
succeeded, but two phone logs reported no microphone signal. The old build waited
for ReplayKit microphone buffers independently of the working command listener.
This did not establish whether the broadcast microphone was off or unavailable.
The replacement records from the existing listener instead of relying on it.

If a source has no detectable signal, the final status says so. Signal detection
is a diagnostic, not proof that a full conversation was recorded intelligibly.
Headphones, audio routes and interruptions still require physical-device checks.

## Test a conversation without a drone

1. Open **Test a video** and choose a file.
2. Under **Record this test**, tap **Enable test recording**. Allow microphone,
   speech and Add Photos permissions if asked.
3. Tap the system broadcast control and select SkyCompanion. Return to the test
   screen, then tap **Play or resume analysis**.
4. Say **SkyCompanion describe**, wait for the answer and any obstacle alert, then
   tap **Stop recording and save**. Play the saved movie in Photos with sound on.

You may also start broadcasting under Connect drone and then import a local video.
Importing a file now resets only the analysis source, retaining the broadcast and
voice assistance. The extension records the screen but does not analyze the test
UI; the main app analyzes the original video's frames. Stopping or pausing the
broadcast does not stop local analysis. The App's Stop recording and save action
stops both analysis and recording and waits for Photos confirmation.

The saved test is a new recording of the visible screen and live conversation.
The imported file is unchanged. When recording starts, the local AVPlayer is
unmuted so its original soundtrack reaches ReplayKit together with app responses.
The original soundtrack also plays outside recording; transient IPC
loss does not mute an ongoing recording.
This feature cannot recover a broadcast made before this update.

If permission is denied, analysis can continue but video saving is explicitly
shown as off. Enable Add Photos in iPhone Settings and restart the broadcast.
If Photos import fails, a completed movie is retained in the extension's private
storage and retried at the next broadcast after permission is available. No
successful-save message is shown before Photos confirms its transaction.

## Implementation

- `BroadcastMovieWriter.swift`: H.264 QuickTime movie, maximum long edge 1280,
  submission cap 15 fps, 2.5 Mbps target bitrate. One encoding frame and one latest
  pending frame bound memory independently of broadcast duration. Busy frames may
  be dropped. Pause intervals are removed; changing orientation fits into the
  initial canvas without stretching. No detection overlays are added.
- `LocalCommandListener.swift` shares the live AVAudioEngine input tap with STT
  and a bounded `RecordingAudioRelay`. Only the extension's authenticated
  recording-start message enables relay capture. Stopping, disconnecting or ending
  the recording disables it; stop-and-save drains already-copied PCM first.
- `SpeechPCMPlayer.swift` plays AVSpeechSynthesizer PCM through the same engine
  during voice assistance. A dedicated output-mixer tap captures rendered sound,
  including responses and cautions. It does not save unplayed synthesis buffers;
  cancellation stops the player and rejects stale synthesis callbacks. Normal
  selected voice, speaking rate and on-device synthesis are retained.
- `LocalRecordingAudio.swift` carries bounded mono PCM, source, recording UUID
  and host-clock timestamp through the existing authenticated phone-only channel.
  The app permits at most eight copied/converting/in-flight packets. The extension
  accepts only its own active recording UUID. No audio relay operates before the
  user starts recording. Payload duration is capped at 250 ms.
- `RecordingAudioMixer.swift` normalizes the sources to 48 kHz mono and writes
  **one 96 kbps AAC track**. Direct command-microphone samples take precedence over
  ReplayKit mic samples; in drone mode directly rendered speech takes precedence over ReplayKit
  app samples during speech, avoiding duplicate voices. In local-video recording
  mode the audible foreground system mix is preferred: it contains both the
  original soundtrack and rendered app speech. Direct speech is only a fallback
  for silent/missing system-mix blocks, never a second copy added to that mix. Other ReplayKit app audio
  remains outside those samples. Each of the two selected sources has half gain.
  A 500 ms reorder window, at most two seconds of PCM, and a 96-callback writer
  queue bound memory. Late/excess buffers can be dropped; diagnostic counts are
  logged without raw audio. Silence fills missing blocks.
- Two-second movie fragments improve resilience of partially written files, but
  force-kill, OS termination, storage exhaustion or device power loss are not
  guaranteed to produce a complete recording. Unfinalized files are not reported
  as saved. If writing can still finish after an error, a saved partial video is
  labelled as partial.
- `BroadcastRecording.swift`: writes in extension-owned storage, then imports
  directly with PhotoKit. No App Groups entitlement, computer or external server is required.
  Audio packets use loopback; complete movie files are not transferred. Ready files are removed only after Photos
  reports success. Audio is saved only as part of the user-started recording.
- `LocalSampleHandler.swift`: handles the app stop request and system broadcast
  finish. A bounded 15-second finalization window holds the stop callback; final
  status is flushed over authenticated loopback where available.
- `LocalSessionModel.swift`: keeps the local channel alive for the final result,
  disables duplicate stop actions, and reports an unconfirmed result after a
  disconnect or an 18-second timeout. A transport acknowledgment alone never means
  the movie was saved. Normal vision freshness and warning rules are unchanged.

Photos is accessed via Apple's add-only API. AVAssetWriter finalization runs only
after frame appends have stopped, following the [AVAssetWriter completion contract](https://developer.apple.com/documentation/avfoundation/avassetwriter/finishwriting(completionhandler:)).

## Verification

- Release iPhone build passed and installed/launched on the connected iPhone 15 Plus.
- Production writer tested on macOS with synthetic frames: 24 decoded frames,
  1.9667-second playable movie, portrait/landscape orientation changes,
  pause-gap removal, duplicate finish, empty recording, and unwritable output.
- Real localhost transport tests passed, including delivery of the final
  recording outcome before disconnect, authentication and backpressure checks.
- Both built targets include the add-only Photos usage description.
- Audio update: production writer/mixer synthetic test passed with app and mic
  tones present after AAC decoding, exactly one mixed audio track, microphone
  sample-rate changes from 16 kHz to 44.1 kHz, and pause/resume. The video and audio
  were decoded from the saved file, not only checked at the input buffers.
- Physical iPhone broadcast → app stop → Photos playback passed: the user
  confirmed that a playable video appeared in Photos on the installed build.
  This short functional check does not establish long-duration recording plus
  drone inference performance or behavior under OS termination.
- Actual iPhone audio capture, simultaneous voice-command recognition, both sides
  of a spoken interaction and caution playback must be confirmed separately for
  the audio update. The earlier phone acceptance was video-only.

Evidence is stored in `validation/mobile-recording/`.

### Direct conversation audio fix

- iPhone Release build passed.
- Writer test decoded both direct sources from a saved AAC movie and checked
  that competing ReplayKit tones were suppressed rather than doubled. The
  existing ReplayKit-only regression also passed.
- Offline playback test rendered 24 kHz speech PCM at 48 kHz and verified silence
  after cancellation and rejection of stale callbacks. This was not a physical
  speaker or microphone test.
- Twelve real localhost transport tests passed, including capture gating,
  recording identity, stereo microphone downmix and no new PCM after Stop.
- Phone conversation playback, speech-command continuity and interruptions are
  pending revalidation for this build. The prior video-only success does not
  validate the new microphone and speech path.

### Local-video recording lifecycle fix

The previous import flow called `endSession()`, sending Stop to the extension and
turning off the command microphone. Broadcast callbacks were also restricted to
the drone's analysis session. The updated flow uses a separate broadcast lifetime
token, preserves it during file imports, accepts recording status for either source,
and excludes extension vision results while the local file is selected. Local test
recording has its own prepare and save controls; it does not require a drone.

Release compilation is verified. Actual cross-screen broadcast continuity and
Photos conversation playback remain physical-device acceptance checks.

### Switching to DJI Fly

An authenticated IPC timeout previously called `finishBroadcastWithError`, ending
screen recording whenever the containing app became briefly unreachable. The
extension now owns recording independently of that connection. On link loss it
stops vision analysis, retains the same movie, and retries authenticated loopback
with delays capped at eight seconds. On reconnect it republishes the existing
recording ID so direct conversation audio can resume without creating a new movie.

Authenticated heartbeat timeout is eight seconds; unauthenticated connections
still expire after 2.5 seconds. Observation freshness remains 1.5 seconds and is
not extended. No background entitlement or silent playback was added. If iOS
suspends or interrupts the voice session, direct microphone/speech packets may be
absent while recording continues with the ReplayKit sources it receives. The UI
must not describe that interval as working assistance.

An explicit system broadcast stop or connected App Stop still finalizes recording.
If the app cannot reach the extension, it directs the user to the system broadcast
control instead of falsely claiming it stopped or saved. OS termination, storage
failure and locked-device behavior are not converted into successful recordings.

Verification: 13 real localhost transport checks passed, including dropped app
connection, authenticated reconnection and cancelling retries on explicit Stop.
iPhone Release build passed. DJI Fly background continuity and audio playback on
the physical phone remain separate acceptance checks.

### Audio continuity and recording-time haptics

A reported local-video recording had smooth live speech but choppy saved speech.
The exported AAC packet timestamps are continuous, with near-silent intervals in
the samples; that alone cannot distinguish lost input from actual silence.
The writer had a concrete defect: it flushed audio and ended the file according to
the latest video frame. Static screens could retain an old audio frontier until
new microphone buffers fell outside the bounded mixer window. Audio now advances
its own timestamp frontier, finalization uses the later audio/video end, and pause
removal accounts for audio recorded after the last picture. The live encoding
queue runs at user-initiated QoS and holds at most 96 audio callbacks. Relay drop
counts and mixer statistics are persisted with session diagnostics.

A six-second decoded-movie regression with only two pictures confirms both direct
audio sources remain audible beyond five seconds without new pictures; the video
tail and pause removal also pass. Moving-frame regression passes. These are
synthetic encoder checks, not the user's physical microphone acceptance.

Fresh obstacle haptics may now pass the event gate while speech is occupied,
without interrupting the protected spoken response. Deduplication, freshness and
cooldown remain enforced. Each vibration request reapplies Apple's
[recording-time haptics setting](https://developer.apple.com/documentation/avfaudio/avaudiosession/setallowhapticsandsystemsoundsduringrecording(_:))
and logs its effective value. Eighteen focused event/scene tests pass. Physical
vibration and saved conversation quality need phone confirmation.

### Original local-video soundtrack

The test player previously muted the original soundtrack deliberately. Local tests
now keep it audible, and during recording the extension switches to the full foreground output mix so
speech does not replace the music or dialogue. A decoded AAC regression contains
three distinct tones representing the original soundtrack, rendered system speech,
and the microphone. All three remain audible; the duplicate direct speech source
is suppressed. Physical-phone conversation and soundtrack playback remain pending
acceptance.

### Silent playback investigation and recovery

The user's 86.748-second follow-up had audible microphone audio but no app audio.
The matching phone log reported speech scheduling, no direct microphone/speech
samples, and no non-silent ReplayKit app signal. Previous diagnostics did not log
engine liveness or output routes, so the exact hardware/session cause remains
unproven. Synthetic mixing tests do not establish physical playback.

CommandListener now observes AVAudioEngineConfigurationChange and restarts a
stopped engine with fresh input taps while retaining the recording relay. It
cancels pending speech rather than replaying stale alerts; repeated failures stop
assistance instead of retrying forever. Calls and headphone-disconnection handling
remain explicit stop conditions. Speech and video playback also check engine
liveness. Voice-processing other-audio ducking is minimized to retain the video
soundtrack. Playback without listening reactivates the audio session without
changing its category during active video playback.

PCM speech start now requires non-silent rendered output, not scheduling a buffer.
The sound check allows ten seconds for a cold voice load; obstacle freshness limits
remain unchanged. Diagnostics capture output device, volume and engine status.
The offline render test verifies resampling, non-silent start, once-only callbacks,
cancellation and rejection of stale synthesized buffers. This does not measure
physical speaker output.

References: [Apple engine configuration notification](https://developer.apple.com/documentation/avfaudio/avaudioengineconfigurationchangenotification),
[voice-processing ducking](https://developer.apple.com/documentation/avfaudio/avaudioinputnode/voiceprocessingotheraudioduckingconfiguration).

On-device follow-up: the user confirmed the sound check is now audible. The log
shows an actual audio configuration change stopping the engine immediately after
voice assistance startup, followed by successful recovery and rendered speech.
The output route was Speaker at volume 1.0, 48 kHz. This reproduces the missing
recovery condition; the older build did not record enough state to prove every
previous silent event had the same cause. Broadcast and saved-movie acceptance
are still separate from this sound check.

The user also confirmed audible local-video obstacle alerts. The missing original
sound in this specific test is explained by the input file itself: the 52.081973s
video (SHA-256 0be80387aca832d2813a191c60d620022ad132be606ff732cb6bdb5d81ad72f6,
matching the current device session) has a stereo AAC track, but all 4,593,664
decoded float samples are exactly zero. A known-audible source is required to
validate soundtrack preservation on device. No model weights, class vocabulary
or inference settings were changed in this audio task.

## Live video-area editing and recording lifetime

The editor is available without a prior screen-switch round trip. The empty
state is a screen-coordinate guide, not a claim to show another app's live image.
Dragging or accessible sliders edits the pending rectangle; Apply updates the
recording and resets stale analysis observations. Returning to SkyCompanion or
applying a new crop pauses external analysis; Resume arms fresh analysis for
DJI Fly. None of these operations stops the broadcast.

The movie writer applies normalized top-left crop coordinates after orientation
correction. Its original output canvas and one audio/video timeline remain fixed;
new crops fit within that canvas without restarting the encoder. Earlier frames
are not changed. Invalid crop updates are rejected.

Only the explicit recording-stop method sends the application Stop packet.
Source changes, voice stop/end commands, audio failure, screen locking and region
edits do not request broadcast termination. iOS can still stop a broadcast on
lock, process termination or resource failure; the app cannot override that.
A nearly-full disk is an explicit writer error, not a successful continued recording.
ReplayKit's own Stop still finalizes the saved video.

Validation: production writer test decodes a single movie containing full-frame,
top-half and bottom-half selections, rejects an invalid mid-stream crop, and
retains the expected two-second audio/video duration and all three synthetic audio
sources. Authenticated reconnect tests pass. Model package hashes match the
existing manifest. Physical touch editing and long-running DJI recording remain
phone acceptance checks.

Phone acceptance RETRACTED: the user corrected their earlier response and reports
a crash whenever Apply video area is tapped. Direct editing and recording
continuity must be revalidated after the crash fix.

### Apply-area crash correction

The device crash report identifies `CropSlider.body` → `Slider.init` →
`Normalizing.init` → Swift assertion failure. A full-width selection produces
a zero-length horizontal range, and near-edge selections can produce a range
shorter than the former 0.01 step. Apply's view update exposed these invalid
slider parameters. The control now uses a fixed 0...1 continuous slider mapped
to the crop bounds, disabling it when no movement is possible. The six-case
offscreen native SwiftUI regression includes both degenerate and tiny ranges.
The recorded-video crop and model code were not changed for this correction.
Physical Apply acceptance is pending re-test.
