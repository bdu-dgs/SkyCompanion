# SkyCompanion on-device app: implementation and handoff

The in-app walking navigation and iMessage preference update is documented in [Navigation and personalization](navigation-personalization.md).

The optional Photon messaging, trip summary and correction module is described in [Photon Assistant integration](photon-assistant.md). Earlier statements about no cloud connection or historical timeline exclude this later opt-in module; detection and obstacle speech still run locally.

2026-09-26. Renamed SkyCompanion. This is a **buildable native on-device development version, not a completed field-accepted delivery**. Signing, installation and launch succeeded on iPhone 15 Plus / iOS 18.7.8; the user heard the sound check and listening started. Short phone inference and risk-event logs exist. Source identity, accuracy and sustained operation still need validation; see [device testing](mobile-device-test.md). Simulator, Mac Core ML and build results do not establish a complete phone/drone loop.

## Implemented

- Native SwiftUI home, onboarding, DJI connection/crop calibration, session controls, local video, settings and diagnostics. System typography, semantic colors, ≥44 pt ordinary controls and ≥56 pt primary controls; accessibility text sizes prioritize actions. Main copy lives in `ios/OnDevice/Localizable.xcstrings`.
- App and ReplayKit extension bundle YOLOE-11s v7, 115 classes, 960 FP16. Fixed text prompts are fused; the phone runs no Python, text encoder or remote inference call.
- The extension handles CVPixelBuffer → orientation → ROI → letterbox → Core ML → boxes/all disconnected mask contours → tracking/risk/limited scene summary. One frame processes while one latest frame waits. The 15 fps submission ceiling leaves room for a 10 fps processing target; it is not measured throughput.
- Authenticated TCP binds only to 127.0.0.1. Mutual HMAC, random nonces and role binding protect the exchange without transmitting the pairing key. Reconnection/configuration revisions invalidate old results. IPC does not wake a suspended app.
- The user starts an actual microphone session in SkyCompanion's foreground. English SFSpeechRecognizer requires on-device execution; TTS uses installed English voices. No cloud recognition fallback. Recognition pauses during TTS to reduce echo. Headphone loss, interruption, locking and stale frames invalidate observations and alerts.
- Risk and perception health are separate. Swift implements continuous evidence, cropped-image region relationships, near-field preference, stable target choice, unresolved occlusion, escalation priority and expiry. R0 is not a safety claim. R3 scheduling is tested, but the current heuristic does not emit R3.
- Local videos reuse the same vision/risk pipeline with replay, pause and seek. The inspector's JPEG, boxes, masks and risk belong to one processed frame, rather than an asynchronous overlay on another player frame. Paused snapshots are historical evidence, never live speech input.
- Bounded diagnostics are automatic. A false-alert report saves structured evidence; Include image in reports optionally adds an available same-frame still. No continuous audio/video recording. Imported temporary video copies are removed when ending or changing sources; original files are untouched.

Implementation: `ios/OnDevice/`; shared pure Swift: `ios/CaptureCore/`. Legacy Mac code remains for regression reference but is excluded from current app/extension build targets. `LocalCaptureConfig.json` must not ship.

## Software evidence

`docs/validation/mobile-2026-09-26/` and `validation.json` retain source hashes, logs and native screenshots. These original milestone counts are historical, not claims of a newly rerun suite:

| Check | Result and scope |
|---|---|
| CaptureCore | 49 Swift tests: risk, occlusion, state isolation, expiry, escalation, whole-utterance commands and R3 scheduling |
| TCP | 10 actual macOS Network.framework localhost tests: authentication, wrong key, reflection/replay, oversized/coalesced packets, reconnect isolation and timeout |
| iOS builds | Release device and Debug arm64 simulator targets; original regression bundles were unsigned. Later signing/install evidence is in the device report |
| Native UI | Actual iOS 27 simulator startup/screenshots of onboarding, home, dark and largest text; not every screen or a VoiceOver walkthrough |
| Core ML | Actual Mac execution; 960 FP16 matched 89/89 baseline detections across 15 same-frame samples, with Swift rotation/crop parity. Not 115-class accuracy or iPhone performance |

See [model report](mobile-model-report.md) for samples, versions, thresholds, misses, mask-representation differences and size/quantization comparisons. `LocalRiskEngineTests.swift` records the Python baseline hash so later backend changes are not confused with that baseline.

## Reproducible build

Run from the repository root:

```sh
python3 scripts/prepare_mobile_app.py
swift test --package-path ios/CaptureCore
zsh scripts/test-mobile-loopback.sh
xcodebuild -project ios/SkyCompanionCapture.xcodeproj -scheme SkyCompanion \
  -configuration Release -destination 'generic/platform=iOS' \
  -derivedDataPath /tmp/skycompanion-local-release CODE_SIGNING_ALLOWED=NO build
python3 scripts/verify_mobile_bundle.py /tmp/skycompanion-local-release/Build/Products/Release-iphoneos/SkyCompanion.app
```

First preparation creates a random app/extension key in `ios/Shared/DevicePairing.json`, without printing or committing it. Rebuild both targets together. If model packages are missing, rebuild from frozen weights following the model report; do not silently substitute a smaller model or remote inference. Keep export and backend environments separate.

Open `ios/SkyCompanionCapture.xcodeproj`, select SkyCompanion, assign both targets the same development Team, select the physical iPhone and Run. The initial device profile expired on 2026-10-02 at 22:26:30 UTC (app) and 22:26:52 UTC (extension), read from embedded profiles. Later signatures may differ; inspect the current bundle. Development signing is not permanent distribution.

## Phone operation

1. In Setup and sound check, verify bundled model, offline English speech and microphone permission; play the sample and confirm the intended headphones produce sound. Install missing system resources before use; no cloud fallback.
2. Connect Neo 2 in DJI Fly and show its camera. Return to SkyCompanion → Connect drone → Enable voice assistance.
3. Use the system broadcast picker, choose SkyCompanion Broadcast and start. Visit DJI Fly briefly, return, crop the saved preview to the actual video area and select Confirm video area. Portrait and landscape are supported.
4. Select Ready — open DJI Fly next, then switch to DJI Fly. Only fresh analyzed frames cause an analysis-start confirmation. Keep the phone unlocked.
5. English commands include SkyCompanion describe, repeat, mute, unmute, pause analysis, resume analysis, status, are you working, and stop listening. Prefix each action with SkyCompanion. Repeat checks current valid evidence; stopping listening ends assistance and does not promise cross-app alerts afterward.
6. Returning to SkyCompanion pauses external analysis. Recheck the source before resuming. Ending assistance stops microphone, local connection and vision processing.

For recordings, choose Test a video, import from Files, use the app's playback controls and inspect same-frame results in Frame inspector. Video audio defaults off; voice commands require explicit activation. Replay recomputes results rather than reusing old risk conclusions.

## Remaining acceptance and limits

- The complete phone/drone chain remains unaccepted: extension memory, Neural Engine execution, concurrent STT/TTS, background stability, 30-minute thermal/battery behavior, sustained 10 fps, actual acoustic P95 ≤750 ms, ten minutes of drone recording and operation without a computer/external network.
- Resident-memory samples are not physical peak/Jetsam measurements. Frame age begins at SkyCompanion capture, excluding DJI transmission. TTS callbacks do not establish audible output or acoustic latency.
- 960 FP16 preserves conversion fidelity but may still exceed extension resources. Save failures and crash logs; do not silently fall back to Mac/cloud or unvalidated candidates.
- User-calibrated ROI handles orientation/size changes and black frames but cannot reliably identify every same-sized DJI menu, layout change or other app. Source identity is not automatically verified.
- Default directions use image coordinates; metric distance is unvalidated. Later manually confirmed rear-following/path experiments are documented separately and do not establish automatic body heading or crossing permission. Risk scores are not collision probabilities.
- App-owned UI, status, guidance, speech and error templates use English. Model IDs, protocol keys and existing stored data retain their semantics. Optional Photon history is distinct from fresh risk evidence.
- Full VoiceOver, reduced motion, contrast, every screen's largest text, calls, headphone removal, echo and rotation require device checks; screenshots are not acceptance.
- [Figma file](https://www.figma.com/design/nbbKLI3KZ3GeQlUDFx24tT) contains pages/components/variables, but server font rendering and the exhausted Starter MCP quota left font repair and prototype wiring incomplete. See [design handoff](mobile-design.md). Native rendering uses system fonts and has no Figma runtime dependency.

Complete device resource feasibility first, followed by sustained operation, drone recording and accessibility acceptance. Do not mark the overall plan fully delivered yet.
