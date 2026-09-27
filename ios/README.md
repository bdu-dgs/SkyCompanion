# SkyCompanion iPhone App

The current Xcode targets run Core ML and speech on the phone. Start with the [on-device implementation, build and phone guide](../docs/mobile-app-implementation.md). The material below describes the **legacy Mac receiver**, not the current installed app. Do not use its configuration generator for the current phone-only workflow.

## Legacy screen-broadcast test client

This is a native iPhone app, not a mini program. The main app checks connectivity and presents the system broadcast control; the `SkyCompanionBroadcast` extension captures the shared screen independently while VLC or another app is foreground and sends video to a Mac. Minimum iOS 18; initial device iPhone 15 Plus.

Only explicitly authorized system screen sharing is captured. It is not saved as a recording. The extension discards audio and does not call player/DJI Fly internals. In this legacy configuration, YOLO runs on Mac, not the phone.

An optional English voice receiver supports Computer / Phone / Both output. The foreground-only receiver pauses when leaving the app. A real continuous microphone/speech session, explicitly enabled by the user, attempts cross-app reception. Background stability requires device verification; the extension runs independently. See [legacy phone speech](../docs/ios-voice.md).

## 1. Legacy preparation and installation

1. Install the local service, then run from the repository root:

   ```sh
   python3 scripts/prepare_live_config.py
   ```

   This embeds `ios/Shared/LocalCaptureConfig.json` in app and extension, including Mac address and pairing credentials. Never commit, screenshot or share it. Address/key changes require reinstalling. The default address is `http://<Mac-hostname>.local:8000`.
2. Open `ios/SkyCompanionCapture.xcodeproj`, using the historical `SkyCompanionCapture` scheme in the legacy project snapshot.
3. Sign into an Apple Account under Xcode → Settings → Accounts.
4. Enable automatic signing for both historical targets, SkyCompanionCapture and SkyCompanionBroadcast, using the same Team. App Groups and additional ReplayKit entitlements are not required.
5. Default bundle IDs are `com.stanley.skycompanion.capture` and its `.SkyCompanionBroadcast` child. If unavailable to your account, change project-level `SKYCOMPANION_BUNDLE_IDENTIFIER` to a unique prefix; both targets and the picker follow it.
6. Connect/trust the iPhone, enable Developer Mode as prompted and select it as the run destination.
7. Run. If the phone asks to trust a developer app, follow Settings → General → VPN & Device Management, then open it.

Installation and device broadcasting require valid signing. Unsigned builds cannot be installed on a physical iPhone. Account validity and capabilities follow the actual Xcode signing result.

## 2. Legacy device test

1. Put phone and Mac on the same ordinary Wi-Fi. Start `scripts/run-live-dev.sh` on Mac.
2. Open the desktop `/live` page and wait for the model.
3. In the phone app, use Check connection and allow local network access. This performs a real health check and short paired WebSocket handshake, opening/closing a preflight session. Use it before broadcasting, not during an existing broadcast.
4. Start the system broadcast and choose SkyCompanionBroadcast. The microphone control is hidden and audio samples are discarded.
5. Open VLC in landscape/full screen, keep the phone unlocked and hide player controls.
6. On Mac, verify advancing timecode, select the video region and start YOLO.
7. Stop via the iPhone recording indicator or Control Center. The desktop should remove old boxes and show ended/disconnected.

Also run ten minutes unplugged and without the Xcode debugger, recording heat, black screens, network loss, extension exit and latency. Compilation and desktop diagnostics do not establish phone capture.

If permission was denied, enable the app's Local Network setting. If discovery fails, check Wi-Fi, Mac firewall, listen address and guest-network isolation. Do not expose this development service publicly.

## 3. Legacy implementation contracts

- SwiftUI uses `RPSystemBroadcastPickerView`; the extension uses `RPBroadcastSampleHandler`. The iOS 18 path exists, but SDK 27 marks these APIs deprecated; iOS 18 device results do not establish iOS 27 capture compatibility.
- Video only: submission target 15 fps, longest edge 960 px, JPEG quality .65. Fixed time slots do not replay missed frames. Actual rate is receiver/inference measurement. Rotate pixels upright while retaining original orientation metadata to prevent a second rotation.
- Encoding holds one original frame; network flow holds one unacknowledged and one newest pending frame. Replace old pending work; discard pending frames older than two seconds.
- Bearer-paired WebSocket sends hello and waits for a session before sampling. Heartbeat every second; acknowledgement timeout 2.5 seconds; handshake timeout six seconds. Clear queues and reconnect with 1/2/4/5-second delays capped at five. New sessions do not replay old data.
- Pause/resume are explicit states; the computer reconfirms analysis after resuming. Static video content alone is not disconnection.
- Browser-display acknowledgements use phone monotonic capture/receipt times, including return-trip delay; retain at most 64 entries. Never subtract Mac and phone clocks.
- Both bundles embed the same legacy configuration, without App Groups or reliance on main-app background execution.

## 4. Legacy validation commands

```sh
xcodebuild -project ios/SkyCompanionCapture.xcodeproj -scheme SkyCompanionCapture \
  -configuration Debug -destination 'generic/platform=iOS' \
  -derivedDataPath /tmp/skycompanion-ios-derived CODE_SIGNING_ALLOWED=NO build
swift test --package-path ios/CaptureCore
```

These historical commands require the legacy scheme. Use the current implementation guide's SkyCompanion scheme for the current app.

Pure Swift tests cover slow-receiver replacement, bad acknowledgements, disconnect clearing, stale frames, timeout, same-phone latency and bounded records. They do not simulate ReplayKit. For restricted local environments:

```sh
CLANG_MODULE_CACHE_PATH=/tmp/skycompanion-clang-module-cache \
SWIFTPM_MODULECACHE_OVERRIDE=/tmp/skycompanion-swift-module-cache \
swift test --disable-sandbox --package-path ios/CaptureCore \
  --scratch-path /tmp/skycompanion-capture-core-tests --cache-path /tmp/skycompanion-swift-cache \
  --config-path /tmp/skycompanion-swift-config --security-path /tmp/skycompanion-swift-security
```

The original implementation built unsigned with Xcode 27.0 / iPhoneOS 27 SDK / arm64 / deployment iOS 18 and passed six pure Swift tests. At that milestone signing, broadcasting, VLC compatibility and end-to-end device latency were still pending.

References: [ReplayKit](https://developer.apple.com/documentation/replaykit/rpbroadcastsamplehandler), [local-network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy).

## Historical risk voice v2 boundaries

- R0–R3, evidence confidence and perception health remain separate. R0 does not establish a clear road; body direction, metric distance and physical R3 urgency were not measured.
- Production events require schema v2, `camera_image`, matching local speech code and capture age ≤1500 ms. Server free text is not spoken as a hazard instruction; old production Stop events are rejected. Legacy test events use camera-qualified wording.
- `health_*` is separate; perception loss does not become high risk or a stop instruction. Test/query/health speech cannot interrupt risk speech; ordinary risk cannot interrupt urgent.
- Historical commands added SkyCompanion why / got it / quieter / normal alerts / wrong alert, retaining repeat/describe/mute/unmute, with VoiceOver-labelled controls. Acknowledgement does not resolve an obstacle. Current mobile commands use SkyCompanion instead.
- Half-duplex recognition pauses during TTS to reduce echo; voice interruption is not promised. UI controls remain available. Microphone stop, headphone removal, background termination and permission failure require device testing.
- The v2 milestone passed 27 pure Swift tests covering whitelists, coordinates, health, stale/future clocks, deduplication, commands and priority. Builds/callbacks do not establish audible onset, intelligibility, full VoiceOver, sustained background operation or walking safety.
