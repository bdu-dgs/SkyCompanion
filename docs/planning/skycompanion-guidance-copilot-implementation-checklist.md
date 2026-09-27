# SkyCompanion Drone Guidance Copilot: Implementation Steps and Acceptance Checklist

Date: 2026-09-25.

Basis: [Complete architecture document](skycompanion-guidance-copilot-architecture.md). Target devices remain DJI Neo 2, iPhone 15 Plus, and the previously user-confirmed iOS 18.7.8; the user carries only the drone and one phone. Operations, code, and numbers in this document are plans to execute, not completed features or measured results.

**Sequence: prepare environment → direct phone connection and framing → native frame capture → background speech validation → local model → prompt rules → desktop viewing → failure/accessibility acceptance → Gemini explanations → fine-tuning as needed.**

First complete a prototype that recognizes objects, speaks a prompt, and shows the same image on a computer. Direction, distance, and path guidance are separate later research; they cannot be inferred directly from detection boxes.

## Step 0: Fix the First Deliverable and Recording Method

**What:** Fix the behavior demonstrated in version one so every later step has an acceptable result.

**How:**

1. Provisionally recognize people, chairs, and bicycles in the first round. This defines system-validation scope; categories such as steps come later.
2. Write a demo script: target enters view → phone speaks once → computer shows the same frame and detection box → target moves away → interrupt video → interface explicitly shows unavailable.
3. Initially use observational phrases such as “A chair was detected in the camera view.” Leave distance null and human-relative direction unknown; issue no turning commands or “road is safe” claims.
4. Later create `evaluation/` in the project to save device/software versions, input video, logs, actual results, and failure reasons for every test. Label recorded input, simulated events, and actual drone live video separately.
5. Use this checklist as a progress sheet, with only “Not started / In progress / Passed / Failed—action needed” for each item and a link to evidence.

**Output:** One-page first-version scope, demo script, and test-record template.

**Pass condition:** The team accepts the same set of behaviors and knows which outputs are supported by first-version evidence.

## Step 1: Prepare the Mac, iPhone, and Existing Project

**What:** First prove the computer can build and install a minimal iOS App and start the existing frontend/backend.

**Finding in this review:** The Mac's active developer directory is `/Library/Developer/CommandLineTools`, and `xcodebuild -version` failed. This shows the build environment is not pointed at full Xcode; it does not prove that no full Xcode installation exists on disk.

**How:**

1. Check for full Xcode. If absent, install a version compatible with this Mac, open it once, and complete required component setup.
2. Select full Xcode in Settings → Locations → Command Line Tools; confirm the build tools report an Xcode version.
3. Connect the iPhone by cable, trust the computer and enable Developer Mode as prompted, then select the physical iPhone as the Xcode run destination.
4. Configure signing with an available team Apple developer account and first install an App displaying only “SkyCompanion test.” Then verify that the team can configure App Groups; do not assume every free account has all capabilities. [Apple capability configuration](https://developer.apple.com/documentation/xcode/adding-capabilities-to-your-app), [App Groups](https://developer.apple.com/documentation/xcode/configuring-app-groups).
5. Check workspace state in the current SkyCompanion directory, retain video upload, and add the phone project and live interfaces.
6. Start FastAPI and React using the existing [README](../../README.md). Prefer existing virtual environments and configuration; do not overwrite `.env`.

If the backend environment does not exist, create it and install dependencies in the backend directory according to the README. Start backend and frontend in separate terminals:

```bash
# Terminal A: first activate your configured Python environment
cd /Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
# Terminal B: install frontend dependencies only on the first run
cd /Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/frontend
npm install
npm run dev
```

These are operating examples and were not executed in this round. Visiting local `/api/health` and the frontend proves reachability only; `ok=true` does not establish successful model or cloud-service calls.

**Output:** A blank App that opens on the phone; reachable frontend/backend; records of device, OS, and development-tool versions.

**Pass condition:** Physical-device installation succeeds and both services start. Record cloud capabilities as unconfigured when credentials are absent, without blocking the capture prototype.

## Step 2: Validate Drone Video and Actual Framing Without Code

**What:** Confirm that video reaches this iPhone and is useful for later recognition.

**How:**

1. Place the drone on a table without starting motors. Open DJI Fly, follow Neo 2 connection instructions, and open the phone's live view.
2. Move a card or object in front of the lens to confirm continuous updates; record DJI Fly version, video layout, and phone orientation.
3. Use iPhone Control Center screen recording for about one minute. Replay it to check for black video, freezing, and important occlusions.
4. Save this recording as later model/page test input. System recording is only preliminary evidence and does not replace custom-extension testing in Step 3.
5. After the table test passes, have a tester who can observe the surroundings inspect native-follow framing in a controlled location. Record whether the road ahead, chairs, and steps enter the image and when they are occluded. Do not validate an unfinished system through independent blind walking.

See [official DJI instructions](https://repair.dji.com/help/content?customId=01700011389&lang=en&paperDocType=ARTICLE&re=US&spaceId=17) for Neo 2 phone control and following.

**Output:** One-minute real screen recording, layout screenshot, and actual framing record.

**Pass condition:** Continuous video is visible without a controller, and the target region is actually visible.

**On failure:** For black video, investigate DJI Fly version, system recording, and video-region issues. Reassess framing if the target region is invisible. Independent software modules may still be developed with existing recordings, but the live pipeline cannot be marked passed.

## Step 3: Create the SkyCompanion iOS Project for Capture Only

**What:** Establish two runtime components: main App and broadcast extension.

**How:**

1. Create an iOS project under the proposed `/Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/ios/`, naming the main target `SkyCompanionApp`.
2. Add a sample-buffer Broadcast Upload Extension target named `SkyCompanionBroadcast`. Both targets use the same signing team and a deployment version covering the phone.
3. Configure the same valid App Group for both targets. First verify the main App writing configuration and the extension reading it; use an identifier actually registered by the team.
4. Initially give the main App four areas: instructions, system broadcast start, current diagnostics, and test-record export. Use `RPSystemBroadcastPickerView`, with the user initiating the system flow. Verify stopping through the system stop entry point; do not fake a stop button that changes UI state only.
5. Use `RPBroadcastSampleHandler` and process `.video` samples in `processSampleBuffer`; implement start, pause, resume, and finish callbacks. Ordinary in-App recording APIs are not substitutes for capturing other Apps. [Apple sample handling](https://developer.apple.com/documentation/replaykit/rpbroadcastsamplehandler).
6. Log session, frame ID, receipt time, dimensions, and orientation per frame. Start experimentally at two processed frames per second, retaining the newest pending frame and avoiding long inference/network waits in the callback.
7. Initially support one confirmed DJI Fly layout. Correct orientation, then crop the configured video region. Pause analysis and upload when layout or occlusion no longer matches configuration. Save the crop-coordinate version with test records.
8. Save only a few diagnostic images and inspect their crop after export. Observe five minutes continuously on the real device, testing rotation, popups, App switching, and manually stopping broadcast.

Proposed main files: `SampleHandler.swift`, `FramePreprocessor.swift`, `SharedModels.swift`, `DiagnosticsStore.swift`. These filenames are development-responsibility suggestions; they were not created in this round.

**Output:** Installable capture App, continuous frame logs, correctly cropped samples, and pause/finish records.

**Pass condition:** The extension continuously receives samples with DJI Fly foregrounded; moving objects appear in cropped images; incorrect layouts do not continue producing normal results.

**Note:** New screen samples do not guarantee drone video updates. Also test frozen video with continuing UI animation. A static image may only be labeled “suspected freeze”; similarity alone is insufficient.

## Step 4: Validate Background Speech Before Model Integration

**What:** Determine whether “DJI Fly in foreground + SkyCompanion speaks after new events” can remain operational on this phone.

**How:**

1. Add `SpeechCoordinator.swift` to the main App and first implement foreground speech with `AVSpeechSynthesizer`. Configure `AVAudioSession` for actual playback, enable required main-target background audio, and handle interruptions/routes. [Apple audio sessions](https://developer.apple.com/documentation/avfaudio/avaudiosession).
2. Initially generate simulated events on a test schedule while the extension receives frames, without a model: for example at seconds 10 and 30 and after three silent minutes. Include a unique ID, generation time, and expiry.
3. Atomically write events to bounded App Group storage. While running, the main App reads new events, deduplicates IDs, and requests speech. Shared storage does not wake a suspended main App; notifications or periodic reads are not keep-alive guarantees. [Apple App Groups](https://developer.apple.com/documentation/xcode/configuring-app-groups).
4. Separately log extension generation, main-App read, playback request, and speech-start callback, and actually listen. Distinguish undelivered events, an App that is not executing, and missing audio output.
5. Start the test, switch to DJI Fly, and wait for new events; do not test only a sentence that started before switching. Include new events after one and three silent minutes and about ten minutes of continuous testing.
6. Reopen and test the App detached from the Xcode debugger. Test VoiceOver and interruption/recovery. Disable unnecessary microphone capture first, then test coexistence of DJI native voice features and SkyCompanion audio.

Looping silence, blank audio, or extended background tasks are not passing evidence. The broadcast extension cannot add `UIBackgroundModes` for background audio. [Apple extension restrictions](https://developer.apple.com/library/archive/documentation/General/Conceptual/ExtensibilityPG/ExtensionCreation.html).

**Output:** Cross-process event and speech logs, listening records, and an explicit pass/fail conclusion.

**Pass condition:** With DJI Fly foregrounded, a new event after long inactivity still speaks promptly, without a debugger; this is not merely finishing prequeued speech.

**On failure:** Record the failing stage. Without a supported mechanism for sustained execution/playback, the single-phone audio design is unproven. Continue independent offline-model or desktop-page work if useful, but do not declare a complete guidance pipeline or automatically substitute a controller or second phone.

## Step 5: Recognize Images with a Pretrained Phone Model

**What:** Convert real cropped images into structured detections.

**How:**

1. Select about 30–50 meaningfully different images from Steps 2 and 3, including targets, no targets, occlusion, and blur. Manually record targets in each to form a small comparison set.
2. Use YOLO11n as a baseline in an independent computer model-development environment. Check the actual category list and enable only the first-version categories. Do not let model-development dependency changes affect the existing backend.
3. Export the same weights to Core ML on the Mac, saving weight source, tool versions, input size, and export configuration. Example to execute later:

```python
from ultralytics import YOLO

model = YOLO("yolo11n.pt")
model.export(format="coreml", imgsz=640, nms=True)
```

4. Add the exported model to the extension target. Implement `Detector.swift`, loading the model once, accepting preprocessed frames through Core ML/Vision, and parsing actual outputs. Do not assume all exports return the same Vision object type.
5. Fix rotation, scaling, padding, and box transformations. Restore all results to the cropped video frame with a top-left origin and normalized boxes.
6. Compare computer and phone results image by image: categories, rotated/shifted boxes, and duplicated NMS. Then connect live frames.
7. Use one inference task and one newest-pending slot, replacing pending frames under overload. Output `frame_id`, model version, category, score, and box. Output an error state on failure, not an empty array presented as success.
8. Run continuously inside the extension for about ten minutes and record inference-time distribution, peak memory, dropped frames, thermal state, and termination. On failure, first inspect image copying/accumulation, then lower sampling, then reassess input size or model size; change only factors related to the failure each time.

Core ML exportability does not establish sustained operation in this broadcast extension. [YOLO11](https://docs.ultralytics.com/models/yolo11), [Core ML export](https://docs.ultralytics.com/integrations/coreml).

**Output:** Model and version records, computer/phone comparisons, and extension performance logs.

**Pass condition:** Images and boxes correspond correctly, operation is stable inside the real extension, and success, no targets, and failure are distinct.

## Step 6: Turn Detections into Fresh, Nonrepetitive Prompts

**What:** Add `EventPolicy.swift` to convert per-frame detections into user events.

**How:**

1. Fix fields: `event_id`, `session_id`, `source_frame_id`, category, text, generation time, source time, expiry, and coordinate reference.
2. Associate recent detections by category/position, giving the same target a temporary ID rather than treating successive frames as new targets.
3. Use the following experimental starting values, then adjust according to misses, false alerts, and latency. They are not validated safety thresholds.

| Rule | Initial implementation |
|---|---|
| Stable confirmation | Same target in at least two of the last three processed results |
| Repeat speech for the same target | Initially a five-second cooldown; handle different new targets separately |
| Event validity | Initially a two-second budget from source-image capture; recheck before playback starts |
| Pending speech queue | At most one relevant prompt; replace expired content |
| Health | Report capture, inference, speech, and remote viewing separately |

4. Record the possibility of missing briefly appearing targets; do not hide new misses to stabilize the display.
5. Validate with recorded detection sequences: target lasting ten seconds, brief appearance/disappearance, two targets entering, no target, model failure, deliberately delayed results. Check events first, then connect the speech module validated in Step 4.
6. Generate only observational prompts. Model confidence alone cannot determine emergency priority; later danger judgments require additional path/geometric evidence.

**Output:** Reproducible rule-input/output examples and actual spoken-event records.

**Pass condition:** The same target does not flood alerts; old images do not create new speech; failure differs from no targets; a global cooldown does not suppress genuinely new targets.

## Step 7: Continuously Show Images and Recognition on the Computer

**What:** Reuse FastAPI/React with live sessions. Develop independently using recorded frames before connecting the phone.

**How:**

1. Add backend `sessions.py` with the proposed interfaces below. Existing `/api/jobs` retains offline video handling.

| Interface | Purpose |
|---|---|
| `POST /api/sessions` | An authenticated development client creates a session and limited-lifetime publishing/viewing credentials |
| `WS /api/sessions/{id}/ingest` | Phone publishes cropped previews, detections, and health events |
| `WS /api/sessions/{id}/live` | Computer subscribes to the same session |
| `GET /api/sessions/{id}` | Retrieve session status |
| `DELETE /api/sessions/{id}` | Close session and invalidate credentials |

2. Begin with one lower-resolution JPEG per second. For integration convenience, one JSON message carries `frame_id`, matching detections, orientation/crop version, and Base64 JPEG; this is only for low-frame-rate preview. Use a separate message type for health events.
3. Cache only a bounded set of latest results; replace old previews for slow clients. If sessions are initially in-process, explicitly run one worker and create new sessions after restart instead of pretending to restore old live sessions. [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/).
4. Add frontend `LiveView` showing images with boxes matching their `frame_id`, scaled to the actual display region. Include last update, four health states, and event list.
5. First integrate using a computer publisher for recorded materials, clearly labeling the page “Recorded input.” Then validate extension upload from the phone on an ordinary network.
6. Connect a phone-reachable HTTPS/WSS test endpoint, such as an authorized team development tunnel or deployed service. Backend and viewer can share the endpoint. Phone `localhost` is not the Mac; do not expose unauthenticated interfaces directly.
7. Connect Neo 2 Wi-Fi and verify whether the same iPhone still uploads through cellular. Record upload success and duration; ordinary Wi-Fi testing cannot substitute for this condition.
8. Simulate slow networks, temporary disconnection, and recovery. Use independent bounded queues for phone capture/inference and upload; upload waits must not block local processing.

**Output:** Desktop live preview, matching boxes, event stream, and real-device dual-network test records.

**Pass condition:** The computer continuously receives current images and matching detections; disconnection explicitly shows stale status; recovery does not replay a backlog of old alerts.

**Smooth video:** One or two frames per second is a preview, not smooth live video. If continuous video is required, add encoding, WebRTC media components, signaling, and necessary NAT traversal, retaining the event channel and retesting extension memory/model contention. Ordinary FastAPI JSON endpoints do not transcode video.

## Step 8: Validate Recovery and Accessibility

**What:** Test the complete start-to-stop workflow and real failure scenarios.

**How:**

1. With VoiceOver enabled, complete connecting DJI Fly, starting SkyCompanion broadcast, confirming status, stopping, and restarting. Inspect system permission pages and DJI Fly; this App's accessibility cannot substitute for whole-workflow validation.
2. Induce each condition below and record status, whether speech reaches the user, and recovery actions.

| Scenario | Expected behavior |
|---|---|
| Manual broadcast stop / drone disconnect | Stop using old images; mark capture unavailable |
| Model error or overload | Mark inference unavailable or reduce frequency; do not report obstacle-free |
| External upload alone fails | Desktop shows stale status; assess local processing independently |
| DJI Fly page or orientation changes | Pause analysis/upload until crop is confirmed |
| Audio interruption / VoiceOver / route change | Update speech status and verify recovery; discard expired events |
| System terminates extension / main App is suspended | Record which components survive, whether they detect failure, and whether they can notify the user |

3. Distinguish “interface knows about failure” from “user actually heard the fault.” When every relevant process cannot execute, immediate fault speech cannot be promised.
4. Define the shortest recovery route per recoverable state, such as “Return to SkyCompanion for status → reconfirm broadcast → return to DJI Fly,” and test it with VoiceOver.

**Output:** Failure matrix, accessibility operation records, unresolved limitations.

**Pass condition:** Defined failures are never misrepresented as normal; recoverable workflows are actually completed; unrecoverable or unannounced scenarios remain explicit failed items.

## Step 9: Complete an End-to-End Demo Acceptance Run

**What:** Combine individually successful modules and measure the whole system.

**How:**

1. Freeze versions/settings and run the Step 0 script continuously. Begin with about fifteen minutes of engineering observation, then separately assess duration under actual flight conditions; model testing does not measure battery life.
2. Manually record when targets enter the valid image, whether detected/spoken, and whether repeated. Separately count missed events and false alerts per minute.
3. Measure end-to-end latency using an external recording of target changes and actual sound; use software logs to decompose internal time. Record median, slower cases, and sample count, not just the best run.
4. An observational prompt starting within two seconds may serve as an initial demo budget, but this is an engineering goal, not a proven safety standard for real guidance. Include adjacent-frame confirmation, video transmission, queuing, and speech wait in total latency.
5. At a location not used for tuning, rerun the fixed script and one stream-loss/recovery test.
6. Organize real demo clips and a result table, distinguishing live field video, recorded replay, and simulated events.

**Output:** Frozen version, demo recording, metrics table, and failed items.

**Pass condition:** Every promised first-version behavior has evidence; subsystem success or recorded replay is not presented as complete real-device success.

## Step 10: Add Gemini Environmental Explanations

**What:** After the basic pipeline passes, add asynchronous explanations without letting cloud availability determine basic speech availability.

**How:**

1. Adapt backend [gemini_summary.py](../../backend/app/gemini_summary.py) with a live-keyframe explanation entry point, retaining the old offline skiing entry point if needed.
2. Current code uses `vertexai.generative_models`. Google says the generative module is deprecated and removed from SDK versions released after 2026-06-24. Use Google Gen AI SDK for new integration, checking models currently available to the account/region rather than relying on old defaults. This does not prove current pinned old dependencies immediately cannot call the service. [Official Google migration guide](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/deprecations/genai-vertexai-sdk).
3. Send only confirmed keyframes with their detection summary. Trigger on demand or meaningful scene changes, with timeouts, rate limits, and per-session budget; do not send every frame to a large model.
4. Define output as `source_frame_id`, `description`, `uncertainty`. Compute expiry from the source frame in code; validate JSON, length, and evidence rather than letting the model declare results never expire.
5. Restrict prompts to visible-environment descriptions and prohibit meters, turns, or safe-passage claims from unknown geometry. Enforce this with code checks and sample assessment as well; one prompt sentence is not a guarantee.
6. Initially display explanations only on the computer. Later phone playback must pass phone event rules, expiry checks, and the validated speech channel.
7. Test timeout, service error, malformed output, and stale return; retain local capability status while displaying explanations unavailable.

**Output:** Asynchronous explanation module, field validation, error examples, and real-call records.

**Pass condition:** Cloud failure does not block basic phone processing; explanations have sources, never override fault status, and never speak expired content.

## Step 11: Decide Whether to Train Based on Misses

**What:** Train only for established gaps, such as step recognition.

**How:**

1. Organize misses, false positives, and unsupported categories from first-version assessment, first choosing one category to add.
2. Collect images through actual DJI Fly capture, covering locations, lighting, occlusion, and no-target cases; remove large quantities of near-duplicate adjacent frames.
3. Label a small set to establish conventions, such as whole stair flights versus each step, before scaling. Label all visible targets of every training category in each image.
4. Split approximately 70%/15%/15% train/validation/test by location and video batch. Adjacent frames from one video must not cross subsets; test data does not participate in tuning.
5. Fine-tune pretrained weights. Record data version, category mapping, image size, training configuration, and best weights; choose compute according to actual computer hardware.
6. Compare original and fine-tuned models on the fixed test set, checking both new-category gains and old-category regression.
7. After Core ML export, repeat Step 5 coordinate/output/performance checks and affected complete scenarios; replace the phone model only when this evidence improves.

**Output:** Data/annotation notes, model versions, before/after comparison, and post-deployment retest.

**Pass condition:** Target performance improves at unseen locations, old categories have no unacceptable regression, and phone resources/latency still meet prototype needs.

## Step 12: Later Upgrade Observations to Direction and Path Prompts

This step involves unresolved inputs and cannot be promised through simply installing a model.

**Specific work:**

1. Define outputs and error bounds: user-relative front/back/left/right, distance intervals, and travel-region occupancy. Fix one controlled scenario first.
2. Validate how to obtain user position/travel heading, relative camera pose, and scale. Without DJI SDK, onboard pose and avoidance distances cannot be assumed available.
3. In a controlled location, use measured ground markers and distances as ground truth to study image-to-ground/user-coordinate mapping. State dependencies on fixed camera pose, planar ground, or persistent marker visibility.
4. Test whether mapping failure is detectable under camera motion, occlusion, and uneven ground. Revert to observational prompts on failure.
5. Only with sufficiently reliable relative position, distance, and path evidence should directional rules be integrated with separate acceptance criteria. Box size cannot replace distance ground truth.

If these inputs are unavailable with the specified hardware/framing, record a platform gap rather than giving speculative navigation commands.

## Suggested Team Responsibilities and Near-Term Priorities

With multiple teammates, work may proceed in parallel by responsibility; no team size is assumed:

| Workstream | Priority | Work independent of device results |
|---|---|---|
| iOS / devices | Steps 1–4, then phone model/audio integration | Data structures, event logs, foreground audio example |
| Vision / data | Steps 2, 5, 6, 11 | Recording baseline, model export, rule-input examples |
| Backend / web | Steps 7, 10 | Live page using explicitly labeled recorded frames |
| Integration / validation | Steps 8, 9 | Failure cases, demo script, test-record template |

**First complete three items: full-Xcode real-device installation, a one-minute direct Neo 2 recording, and simulated-event background speech through the broadcast extension.** Until capture and speech pass, large-scale training and page polishing should not consume most effort.

## What Was Actually Completed in This Round

Reread architecture/current source, inspected current Mac build-tool configuration, checked key platform documents, and generated this checklist. Development tools were not installed; no iOS project was created; SkyCompanion code was not modified; backend deployment, model training, and real-device tests were not performed.
