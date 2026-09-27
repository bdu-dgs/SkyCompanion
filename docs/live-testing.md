# SkyCompanion Cross-App Phone Capture and Live YOLO Detection: Operation and Acceptance

This round verifies: **After starting a SkyCompanion screen broadcast on an iPhone and switching to VLC to play first-person video, SkyCompanion on the Mac continuously displays the current image and local YOLO detections.**

SkyCompanionCapture is the native iPhone app that must be installed. The main app provides connection checks and the system broadcast entry point. The SkyCompanionBroadcast extension captures the screen while another app is in the foreground; SkyCompanion Vision on the Mac currently runs experimental YOLOE-11s weights. Capture, sampling, and sending happen continuously, without recording a complete video first. These instructions and the live webpage are in English.

This document contains operating steps and acceptance criteria, not a report of completed device testing. This round does not connect a drone, use cloud vision analysis, or verify background phone voice alerts. After the VLC test passes, DJI Fly compatibility and networking while connected to a drone still need separate testing.

## 1. Start on This Mac

1. Keep the iPhone and Mac on the same ordinary Wi-Fi network that permits communication between devices.
2. Open `/Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion` in Finder and double-click **Start SkyCompanion Live.command**.
3. Keep the resulting terminal window open. It starts the backend receiver and monitoring webpage services together.
4. Open **<http://127.0.0.1:5173/live>** in the Mac browser. Keep only one live monitoring page open; this version supports one input source and one monitoring page.
5. Wait for the receiver service to show “Connected” and local detection to show “Model ready.” “Waiting for phone” is normal before the phone connects.

Alternatively, start from a terminal:

```bash
cd /Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion
bash scripts/run-live-dev.sh
```

Press **Control-C** in this launch window to stop both services. Service logs are in `.skycompanion-live/backend.log` and `.skycompanion-live/frontend.log`. If port 8000 or 5173 is reported occupied, stop the previously launched SkyCompanion instance first rather than starting another copy.

**The Mac browser uses `127.0.0.1`; the phone connects to the Mac address shown in the app, typically `http://computer-name.local:8000`. Do not change the phone's receiver address to `127.0.0.1`.**

### Needed Only If the Environment Is Not Ready

Existing local environment and configuration can be reused. If the launch script explicitly reports missing dependencies, models, or configuration, run from the project root:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python scripts/setup_live.py --install
backend/.venv/bin/python -m pip install -r backend/requirements-obstacles.txt
backend/.venv/bin/python scripts/prepare_obstacle_models.py
npm --prefix frontend install
```

`setup_live.py` installs dependencies, downloads original YOLO11n baseline weights, and generates pairing configuration. `prepare_obstacle_models.py` prepares the YOLOE-11s model and fixed class prompts currently used by SkyCompanion Vision. Older weights remain for offline comparisons; the user page has only one model entry point. Live tests do not require Gemini, Vertex AI, or Roboflow account credentials.

To regenerate only the phone configuration, run:

```bash
backend/.venv/bin/python scripts/prepare_live_config.py
```

This writes `.skycompanion-live/config.json` and `ios/Shared/LocalCaptureConfig.json`. The latter is embedded in the main app and broadcast extension at build time and contains the receiver address and pairing credentials. Do not screenshot or distribute its contents. **After the address or pairing credentials change, rebuild and reinstall the phone app.**

## 2. Install SkyCompanionCapture on the iPhone with Xcode

After completing first-launch Xcode license acceptance and required component installation:

1. Connect the iPhone with a data cable and trust the Mac on the phone. Follow Xcode's instructions to enable **Settings → Privacy & Security → Developer Mode** on the phone.
2. Open `/Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/ios/SkyCompanionCapture.xcodeproj` in Xcode.
3. Sign in to an Apple Account under Xcode **Settings → Accounts**.
4. Select the project and open **Signing & Capabilities** for both **SkyCompanionCapture** and **SkyCompanionBroadcast** targets. Enable **Automatically manage signing** and select the same **Team** for both.
5. If the Bundle Identifier is already taken, change project-level **Build Settings → User-Defined → SKYCOMPANION_BUNDLE_IDENTIFIER** to an identifier unique to your account, such as your reverse domain plus `.skycompanion.capture`. The broadcast extension's child identifier and broadcast picker update with this setting; do not change only one target.
6. Select the **SkyCompanionCapture** scheme at the top, choose the connected physical iPhone as the run destination, and click **Run**.
7. If the phone reports an untrusted developer app, follow the actual prompts under **Settings → General → VPN & Device Management**, then open SkyCompanionCapture.

No additional App Groups are required. An unsigned compile pass does not establish installability; Xcode and the physical phone determine whether installation succeeds. See the [iOS README](../ios/README.md) for more project details.

## 3. Transfer the Video to VLC on the iPhone

The user's selected Bilibili video can also be used for an initial connectivity trial: start the system broadcast in SkyCompanionCapture, switch to Bilibili, and play street/walking first-person video. Select a region and analyze on the Mac as in section 4. Whether ReplayKit can capture that specific content requires an actual test; switch to local VLC media if the video is black. This trial does not complete formal acceptance using timecoded looping media. Record the player name, version, and actual video source.

Use the prepared file:

```text
/Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/samples/local/skycompanion-pov-3874684-1080p30-timecode.mp4
```

This is a 1080p, 30 fps, H.264 video with visible timecode, no audio, and a duration of about 26 seconds; it can loop. Source, author, license, hashes, and reproduction steps are in the [media notes](../samples/README.md).

Follow the [official VLC Wi-Fi transfer instructions](https://docs.videolan.me/vlc-ios-user/gettingstarted/media_synchronization.html#share-via-wi-fi):

1. Install and open **VLC media player** on the phone.
2. Open **Network** in VLC, enable **Sharing via WiFi**, and grant necessary local-network access.
3. Keep VLC in the foreground and enter **the upload address shown on VLC's screen** in the Mac browser. This address transfers files to the phone; it differs from the SkyCompanion monitoring address.
4. Drag the MP4 above into the webpage and wait for upload completion.
5. Open the video in VLC on the phone. Confirm landscape fullscreen playback and a continuously changing timecode in the upper-left corner. Enable looping/repeat for continuous testing.

Before the formal broadcast, use the iPhone's built-in screen recorder to record about 30 seconds of VLC playback. Stop it and inspect the video in Photos: both street footage and timecode should appear normally, without a black video region. **This checks only ordinary player screen recording; the SkyCompanion broadcast test below is still required.** Stop ordinary screen recording after checking it, then start the SkyCompanion broadcast.

## 4. Start the Actual Phone Broadcast and YOLO Analysis

If the Mac diagnostic sender described below was previously running, press **Control-C** in its terminal first. Wait for the monitoring page to show input disconnected/ended before connecting the phone; the diagnostic script and phone cannot occupy the single input slot together.

1. Confirm that Mac services are running, open <http://127.0.0.1:5173/live>, and verify “Model ready.”
2. Open **SkyCompanionCapture** on the iPhone, tap **Check connection**, and allow **Local Network** in the system prompt.
3. Wait for “Connected, YOLO ready.” A connection check opens and ends a brief paired preflight session, so it is normal for the webpage to briefly show connected and then ended. **Do not tap Check connection again during the actual broadcast.**
4. Tap the system broadcast button in the app. Select **SkyCompanionBroadcast** in the iPhone system dialog, personally confirm the start, and wait for the countdown to finish. The current implementation does not capture audio and hides the microphone control.
5. Manually switch to **VLC**, play the test video in landscape fullscreen, and hide playback controls. Keep the phone unlocked. The SkyCompanionCapture main app does not need to stay in the foreground.
6. On the Mac, confirm the source label is **Phone video playback test**, view the complete phone-screen preview, and verify that the timecode advances continuously.
7. Click **Select video region** and drag a rectangle around VLC's video region in the full preview. Retain the test video's own timecode, while excluding player buttons, system interface, and outer black borders as much as possible. You can also enter left, top, width, and height percentages; width and height must each be at least 2%.
8. Click **Save video region** and wait for “Region saved · Ready to analyze.” If the entire preview is the intended video, click **Use full frame**, then still click **Save video region**.
9. Separately click **Start analysis**. The page now displays the selected region and detection boxes for its corresponding frame, with classes and confidence on the right.
10. To adjust the region, click **Reselect video region**. Analysis pauses and the full preview returns. Select and save again, then click **Start analysis**.

When vehicles appear, observe whether the model produces reasonable boxes and record missed detections, wrong classes, or inaccurate positions. The model recognizes only pretrained classes. “No supported objects detected” means the frame was analyzed without suitable output; it must not be interpreted as a safe road. Model errors should show “Detection failed” or “Model unavailable.”

## 5. Check Pause, Network Loss, Rotation, and Stop in Order

| Action | Observe and record |
| --- | --- |
| Click Pause analysis on the Mac | Current boxes become invalid while the full preview continues. Start analysis again uses only new images. |
| Pause and resume the VLC video | Static video content must not immediately become “Network disconnected.” If the system stops producing new screen frames, the page may show “No new frames” and invalidate old boxes; this must be distinguished from input disconnection. After new frames resume, restart manually if analysis has paused. |
| Turn off iPhone Wi-Fi for about 5–10 seconds | Old boxes should be invalidated. About 2 seconds without new frames enters “No new frames”; about 3 seconds without heartbeat enters interrupted input. Visible page timing also includes polling and network scheduling. Record actual behavior. |
| Reconnect to the original Wi-Fi and return to VLC | The extension attempts reconnection with a new session, without catching up on pre-disconnection frames. Reconfirm/save the video region and restart analysis. If the system broadcast ended, restart it from SkyCompanionCapture. |
| Rotate from landscape to portrait and back | When the system actually changes orientation/dimensions, old boxes and crop should become invalid and analysis should pause. After returning to the desired orientation, select/save/start again; do not reuse a crop from the wrong orientation. |
| Stop broadcasting from the iPhone's red recording indicator or Control Center | The Mac invalidates old boxes, shows broadcast ended or input disconnected, and no longer presents valid live detections. |

Pausing the player, pausing webpage analysis, and pausing the system broadcast are different actions. Users do not need to search for a nonexistent “Pause broadcast” button for this test. If the system triggers broadcast pause/resume during an interruption, record whether the page correctly reflects that state, and restart analysis after recovery.

Perform fault tests such as network loss and rotation separately. Afterward, start a clean broadcast session for the ten-minute stability test below.

## 6. Ten-Minute Device Acceptance Without the Debugger

1. Stop debugging in Xcode, unplug the data cable, and reopen SkyCompanionCapture from the iPhone home screen.
2. Start broadcasting as in section 4 and switch to looping VLC playback. Keep the phone unlocked, the Mac monitoring webpage visible, and the computer awake.
3. Confirm the source is “Phone video playback test,” complete cropping, and start analysis. Once image and model operation stabilize, record the start time and save start metrics.
4. Run continuously for 10 minutes without deliberately disconnecting or rotating in this round. Record black images, timecode progress, extension exits, automatic stops, stream interruptions, noticeable phone heating, and whether boxes consistently correspond to the current image.
5. At 10 minutes, **save end metrics while the broadcast is still running and the monitoring webpage is still open**, then stop the broadcast. Reconnection resets counters in a new session; record any interruption rather than treating post-reconnection counters as a complete ten-minute result.

Save metrics in another Mac terminal window:

```bash
cd /Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion
curl --fail http://127.0.0.1:8000/api/live/report \
  --output .skycompanion-live/iphone-10min-start.json
```

At the end of ten minutes:

```bash
cd /Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion
curl --fail http://127.0.0.1:8000/api/live/report \
  --output .skycompanion-live/iphone-10min-end.json
```

Run these commands at the start and end respectively, not immediately back-to-back. You may also view current JSON at <http://127.0.0.1:8000/api/live/report> in the Mac browser; this endpoint permits local reads only.

Metric interpretation:

- `source` should be `screen_video_test`; the start and end `session_id` should match.
- `received_frames` and `processed_frames` are cumulative session counters. Calculate stable-interval average inference rate as the end-minus-start `processed_frames` difference divided by actual elapsed seconds. The page's `received_fps` and `processed_fps` are recent-window rates, not ten-minute averages.
- `dropped_frames` counts older frames discarded to stay current. Drops alone do not imply failure; also check update speed and backlog.
- `queue_ms` and `inference_ms` are the queue and inference durations of the latest processed frame.
- `roundtrip_p50_ms` and `roundtrip_p95_ms` are timings measured when the sender receives webpage display acknowledgments, using the same sending device's clock and including acknowledgment return transport. The backend retains at most the latest 4096 latency records. With no records they are `null`, not 0 ms.

The current performance target is **at least 10 fps average inference in a stable interval with capture configured at 15 fps, and display-acknowledgment P95 no greater than 1000 ms**. This is a target to measure, not a speed guarantee. Earlier 5 fps capture/at least 3 fps inference results remain the baseline. Record functional acceptance and performance-target attainment separately, preserving failures and raw metrics. This is not full drone-to-user-alert latency.

Acceptance records must include at least: iPhone model and actual iOS version, Mac model and OS version, VLC version, Wi-Fi used, start/end times, model, crop region, the metric files above, each fault-test result, and items still unverified.

## 7. Optional: Mac-Only Diagnostics First

To first check Mac reception, YOLO, and webpage integration, use the same actual video as diagnostic input. **This does not start an iPhone or pass through ReplayKit. The page labels it “Diagnostic video · Not phone capture,” and report `source` is `diagnostic_video`. Its results cannot be described as a passed phone-link test.**

Ensure no phone broadcast is active. Run the services from section 1 in one terminal. In another, run:

```bash
cd /Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion
backend/.venv/bin/python scripts/live_diagnostic.py \
  --video samples/local/skycompanion-pov-3874684-1080p30-timecode.mp4 \
  --fps 5 --seconds 0
```

`--seconds 0` runs continuously and loops the media. Open <http://127.0.0.1:5173/live> on the Mac and follow the same “Select video region → Save video region → Start analysis” sequence. For a one-minute run, use `--seconds 60`.

When diagnostics finish, press **Control-C** in **the diagnostic script's terminal** and wait for the page to show input ended/disconnected. Keep the separate SkyCompanion service window running, then proceed with the phone connection check and system broadcast. Until the diagnostic source stops, the phone cannot connect because the only input channel is occupied.

## 8. Troubleshooting

| Symptom | Next step |
| --- | --- |
| Mac webpage will not open | Check that the launch window is still running, ports do not conflict, and `.skycompanion-live/frontend.log` has no relevant error. Use the explicit `/live` URL. |
| Model unavailable | Read the page error and `.skycompanion-live/backend.log`; confirm `setup_live.py` ran and the weights exist. Restart the service after fixing the issue. |
| Phone connection check fails | Check same Wi-Fi, SkyCompanionCapture local-network permission, Mac services/firewall inbound prompts, and guest isolation. Stop any running diagnostic source or other broadcast. |
| Mac address or pairing configuration changed | Regenerate configuration and reinstall the main app and extension through Xcode. The previously installed phone build does not automatically read changed files on the Mac. |
| SkyCompanionBroadcast missing from the system list | Confirm Xcode installed SkyCompanionCapture including its extension and both targets signed successfully. Check project configuration using `ios/README.md`. |
| Phone reports connection success but Mac has no VLC image | Confirm broadcast start in the system dialog, completed countdown, VLC in foreground, and unlocked phone. Check screen-capture state, then distinguish black images, no new frames, and disconnected input. |
| Start analysis unavailable | Requires a healthy connection, current image, ready model, and a saved valid video region. Select the region again after rotation or reconnection. |
| Video works but no boxes appear | Check whether current-frame detection says not yet analyzed, no supported objects detected, or detection failed. First check a frame with an obvious car; do not interpret zero detections as safety. |
| P95 has no value | Keep the single monitoring page visible and confirm new frames are received/displayed. Without webpage display acknowledgments, this latency statistic is unavailable. |

After this round, retain actual device acceptance records before deciding whether the capture approach is viable. Desktop diagnostics, automated state tests, and unsigned compilation provide different evidence; none replaces actual cross-app phone broadcasting and the ten-minute run.
