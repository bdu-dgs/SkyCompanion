# SkyCompanion Live Capture and Detection Test Report

Date: 2026-09-25 (subsequent measurements were dated 09-26 UTC, still 09-25 locally). Status: **Cross-app phone broadcasting, Wi-Fi transport, and actual YOLO inference have run; the ten-minute device stability acceptance test remains pending.**

On-site adjustment: the user requested an initial first-person video test in Bilibili. This can establish initial cross-app connectivity; the VLC timecoded media remains the source for subsequent repeatable formal acceptance testing.

## Implemented

- Native iOS 18 SkyCompanionCapture and separate SkyCompanionBroadcast extension. After system authorization, target sampling is 15 fps (5 fps in the first version), longest edge 960, JPEG quality 0.65, with no recording saved and no audio sent.
- Paired LAN input, one input/one monitoring page, separate heartbeat and frame freshness, crop invalidation on rotation, new sessions on reconnection, and a bounded latest-frame buffer.
- Local Mac YOLO11n CPU inference, input 640, confidence 0.35, with image and boxes emitted together.
- `/live` full preview, selection, save, start/pause, explicit distinction between empty detections and errors, and display-acknowledgment latency.
- Development configuration and launch scripts, real street-view test media, [step-by-step instructions](live-testing.md), and [protocol](live-protocol.md).

## Environment

| Item | Recorded for this test |
| --- | --- |
| Mac | Apple M5 Pro, macOS 27.0 / 26A428 |
| Xcode | 27.0 / 27A266a; iPhoneOS 27 SDK, minimum deployment iOS 18 |
| Target phone | User-reported: iPhone 15 Plus, iOS 18.7.8; Xcode recognized the connected device |
| Python / model dependencies | Python 3.12.6, Ultralytics 8.4.37, PyTorch 2.11.0, torchvision 0.26.0 |
| Receiver service | FastAPI 0.115.6, Uvicorn 0.32.1, WebSockets 16.0 |
| Image processing | OpenCV 4.10.0.84, Pillow 11.3.0 |
| Model | Official YOLO11n COCO pretrained weights, local CPU |
| Input | Pexels street footage by Joe Valdes, 1080p30 H.264, 26.267 seconds, timecoded; transport resized to 960×540 |
| Browser | Codex built-in browser, with actual webpage decoding, drawing, and acknowledgments |
| Device network / player | Bilibili landscape street footage; actual source connection was iPhone → Mac on the same Wi-Fi; VLC acceptance testing remains pending |

## Actual Mac Diagnostic Results

This input was explicitly tagged `diagnostic_video`: the Mac decoded the video and sent it to the local service. **It was not captured on a phone and did not pass through Wi-Fi or ReplayKit.** The actual webpage displayed model boxes such as `car` and `truck`, with visually reasonable positions. This was not a detection accuracy assessment.

Observation interval: 2026-09-25 22:24:45–22:25:45 UTC (17:24:45–17:25:45 local), 60.007 seconds, with one session and analysis enabled throughout.

| Metric | Measurement |
| --- | ---: |
| Interval average received frame rate | 4.999 fps |
| Interval average inference frame rate | 4.983 fps |
| Old frames discarded by the interval end | 0 |
| Median / maximum YOLO duration sampled once per second | 31.67 / 74.74 ms |
| Maximum queue time sampled once per second | 1.20 ms |
| Display acknowledgment P50 / P95 at interval end | 57.10 / 296.73 ms |

Frame rates use the difference in cumulative counters between interval endpoints divided by actual elapsed time. Duration values are once-per-second status snapshots and do not cover every inference frame. P50/P95 are session statistics from analysis start through interval end, including analysis frames before the measurement interval; preview latency records were cleared when analysis started. Mac diagnostic timing starts at transmission after JPEG encoding and includes webpage decoding, drawing, and acknowledgment return. It cannot establish phone capture latency.

The original 61 snapshots and calculation summary are in [mac-diagnostic.json](evidence/mac-diagnostic.json). This Mac diagnostic met the ≥3 fps and P95≤1000 ms targets; phone performance was not yet determined at that stage.

## Actual iPhone Cross-App Results at 15 fps

Observation interval: 2026-09-26T01:42:06.650261+00:00 to 2026-09-26T01:43:06.640335+00:00, totaling 59.990 seconds. Input was Bilibili street footage playing on the iPhone, passed through ReplayKit and Wi-Fi to the Mac. The same session, continuous reception, and actual YOLO analysis remained active throughout. These results are distinct from the Mac diagnostic above.

| Metric | Measurement |
| --- | ---: |
| Interval average received / inference frame rate | 15.002 / 15.002 fps |
| Additional old frames discarded during interval | 0 |
| Median / maximum inference duration sampled once per second | 23.37 / 25.16 ms |
| Maximum queue time sampled once per second | 0.66 ms |
| Display acknowledgment P50 / P95 at interval end | 79.66 / 93.78 ms |

Orientation: the landscape street scene that was previously inverted by 180° was visually confirmed upright. The actual raw orientation flag was 6. The phone sent 960×443; after the ROI removed side letterboxing, YOLO analyzed 790×443. The webpage showed vehicle and pedestrian boxes updating with the current image. Sampling changed from fixed 200 ms intervals to 15 fps time slots.

Frame rates use cumulative counter differences divided by actual duration. P50/P95 accumulate from this analysis start through interval end, including analysis frames before the measurement started. Timing starts at phone sampling and ends when the browser drawing acknowledgment returns, including the return network path. It is not full video-recording-to-display latency. Per-frame durations are once-per-second snapshots and do not cover every frame.

The original 61 snapshots are in [iphone-15fps.json](evidence/iphone-15fps.json). This minute met the 15 fps capture and at least 10 fps inference targets. It does not replace acceptance testing for ten-minute stability, the other landscape orientation, or the drone link.

## Automated Checks and Builds

| Check | Result and evidence limitations |
| --- | --- |
| Backend state/image behavior | 20/20 passed; a controlled detector verified crop, queue replacement, pause, rotation, reconnection, timeouts, and errors; this does not establish device behavior or YOLO speed |
| Frontend protocol helpers | 4/4 passed; production build succeeded |
| Swift frame window, freshness, and sampling cadence | 9/9 passed, including maintaining 15 fps with jittery 30 fps callbacks, skipping overdue frames, and immediate sampling on reconnection; ReplayKit was not simulated |
| Unsigned iPhone arm64 build | Both targets passed; `/tmp/skycompanion-ios-build.log` |
| Signed installation | Both Xcode targets were signed and installed with the same Personal Team; after trusting the certificate, the user confirmed opening SkyCompanionCapture |
| Python / launch scripts | Python compilation, shell syntax, and actual service startup passed |
| Video loop boundaries | After the fix, reads succeeded at 84 end-of-video/loop-boundary positions in the real media |

Actual browser operations verified receipt of diagnostic images, selection and saving of the full region, starting real YOLO, and displaying vehicle boxes and metrics. Old boxes and images were invalidated when input disconnected. Browser checks used Computer Use; a dedicated Browser plugin was not initially found, and actual checks were later completed through the Computer Use built-in browser.

## Findings and Fixes

1. The first diagnostic script added decoding time to its 200 ms wait, yielding only about 3.1 fps reception. It now sends by time slots, measured at about 5 fps. A preview inference rate of 0 fps means analysis has not started, not model inference failure.
2. React development-mode double initialization could briefly contend for the only monitoring connection. Connection creation is now delayed and canceled for the trial mount; an explicit manual reconnect control is retained.
3. Preview acknowledgments were mixed into analysis latency. Start/pause configuration now clears latency records and begins fresh statistics.
4. After the one-minute speed test, the diagnostic source threw “Test video decoding failed” at a loop boundary. The service and webpage correctly showed interrupted input and cleared old results. Millisecond seeking was replaced with valid integer frame seeking, and 84 boundary reads passed. This result was not claimed as a ten-minute stability pass.
   The fixed script also ran for another 45 seconds, crossed one complete video loop, and exited normally (exit status 0).
5. The first Xcode installation lacked a development team. Signing and installation completed after account login and team configuration for both targets. The user confirmed certificate trust on the device.
6. Actual WebSocket handshakes confirmed rejection of input without credentials, input with incorrect credentials, and a monitoring connection with an external Origin (HTTP 403).
7. The user's device screenshot exposed a blank broadcast button. The ReplayKit picker's zero initial size was fixed; UIKit and SwiftUI now both use 72×72 dimensions, with a light-red bordered background and explicit label. After re-signing, installation, and launch, the system recording icon was visually confirmed in the Xcode device View Hierarchy. A subsequent actual broadcast verified that the control starts screen sharing.
8. A subsequent actual Bilibili landscape broadcast confirmed a 180° inversion. The phone encoder's landscape 6/8 transforms were adjusted and orientation metadata was removed from output JPEGs. After the signed update, both the actual portrait app and `orientation=6` landscape street footage were visually verified upright. The other landscape orientation has not been separately accepted, and these local results are not generalized to every iOS version.
9. The original fixed 200 ms phone sampling capped capture at 5 fps. Sampling now uses fixed 15 fps time slots, skips old frames when encoding/networking is busy, and does not resend a backlog. The installed version actually showed 15 fps reception and inference.
10. The on-site transport connection was confirmed as Mac `192.168.4.24:8000` and phone `192.168.4.56`; Xcode also reported `localNetwork` for the device connection. This traffic used Wi-Fi and normal operation does not require USB. User-confirmed physical cable removal and ten-minute continuity have not yet been recorded.
11. A ready model does not mean analysis has started. After selecting the video region to remove side letterboxing and starting analysis, the webpage showed YOLO11n vehicle and pedestrian boxes updating with the current image.
12. The launch script's port probe now uses `SO_REUSEADDR` to avoid misreporting normal TCP wait states after shutdown as an occupied service port.

## Outstanding Acceptance Tests

| Required item | Status |
| --- | --- |
| Open app successfully after trusting the iPhone certificate | Opened; the main interface appeared in an actual screen broadcast |
| Foreground local-network permission and phone connection check | User confirmed “Connected, YOLO ready”; the backend received an authenticated preflight session that ended normally with 0 frames. See [preflight record](evidence/iphone-preflight.json) |
| VLC import and ordinary screen recording without a black image | Pending |
| Switch to another app while SkyCompanionCapture continues sampling in the background | Actually ran with Bilibili and completed YOLO inference; VLC remains pending |
| Phone landscape/portrait rotation, pause, Wi-Fi loss and recovery | Pending; only automated checks of related state logic have passed |
| Show ended status when the user stops broadcasting | Pending device verification; the extension sends an end message on a best-effort basis before exiting, while connection closure/heartbeat timeout still invalidates old boxes |
| Ten minutes continuously, unplugged and detached from debugger | Pending; record extension exits, heating, frame rate, and P95 |
| DJI Fly and drone Wi-Fi | Outside this round's scope |

Continue device testing using [instructions in sections 4–6](live-testing.md). Record actual results before marking the complete plan accepted.
