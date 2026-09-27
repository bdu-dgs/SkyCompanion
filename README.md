# SkyCompanion

SkyCompanion explores an assistive walking companion that combines a following drone's view, concise audio guidance, and a searchable record of walking events.

The project theme is **“Fly Me to the Moon”**: the drone offers a different, elevated perspective, while the phone turns that view into guidance a walker can use. The long-term goal is to help blind and low-vision users notice relevant obstacles and review what happened during a walk.

> **Project status:** This repository now includes a native SwiftUI iPhone app and ReplayKit broadcast extension, on-device Core ML detection and speech, a local backend and web monitor, training tools, and a Photon/iMessage trip assistant. The latest integration passes an unsigned iOS Release build and 400 application unit tests. Sustained live DJI operation, outdoor reliability, and independent detection accuracy remain unverified. See [integration verification](docs/integration-verification.json) for the exact scope and existing test failures.

## Product direction

- **Aerial following view:** A DJI drone follows the walker and captures the scene ahead from above.
- **On-phone, real-time guidance:** A native iOS app analyzes the drone view locally and gives short spoken alerts about relevant objects on the walking path.
- **Questions and walk history:** The user can ask about the current or a recent walk. Selected alerts become structured route/obstacle records, and an iMessage Agent can answer questions and manage supported alert preferences.
- **DJI Fly and SkyCompanion:** DJI Fly supplies the camera view. The SkyCompanion ReplayKit extension captures the selected screen region, and the native app packages local inference, speech and supported questions.
- **Computer-hosted messaging Agent:** A Photon iMessage service on a computer receives selected event summaries from the phone, stores them, and answers supported questions.

The intended flow is:

    DJI drone view
        -> iOS capture app
        -> on-device vision app: model + tracking + walking-path rules
        -> brief spoken guidance + selected structured event summaries
        -> computer-hosted Photon/iMessage service
        -> trip archive, supported questions, and alert preferences

The phone app and messaging bridge are implemented; the full real-world drone-assisted walking experience is still under validation. See [Current implementation](#current-implementation) and [Known gaps and safety boundaries](#known-gaps-and-safety-boundaries).

## Current implementation

### Native iPhone application and real-time monitor

Open **ios/SkyCompanionCapture.xcodeproj** and select the **SkyCompanion** scheme.
The app includes local-video and ReplayKit input, Core ML detection, wearer tracking
and exclusion, risk processing, optional depth/path analysis, speech, recording,
walking navigation and the Photon companion interface.

The selected phone detector is **Street72, epoch 15**, exported as FP32 Core ML.
It emits boxes, not segmentation masks. The two selected Core ML packages and
desktop runtime weights exist in the development checkout but are **not included
in Git**. Model distribution has not been published; a fresh clone needs those
matching packages before building. See [model details](docs/mobile-world72.md).

- [Build and integration guide](docs/hackathon-integration.md)
- [Mobile implementation and operation](docs/mobile-app-implementation.md)
- [Backend and web monitor setup](docs/desktop-and-mobile-guide.md)
- [Photon assistant](skycompanion/README.md)
- [Verification results and limitations](docs/integration-verification.json)

The FastAPI backend, React/Vite monitor, deployment files, design assets and tests
are included under **backend/**, **frontend/**, **deploy/**, **design/** and **ios/**.

### 1. Windows video-analysis prototype

The main entry point is **sky_companion.py**. It processes a local video file with Python, OpenCV, YOLO-World, and ByteTrack.

- The checked-in detector checkpoint is **yolov8s-worldv2.pt**. It is the starting model, not a SkyCompanion fine-tuned checkpoint.
- The runtime supplies classes including person, bicycle, streetlight, railing, bus shelter, tree, red/green traffic light, utility pole, and common motor vehicles.
- ByteTrack tracks detections. A person is selected as the protagonist using position and size cues, then retained across nearby frames where possible.
- For a rear-follow video, the program scans a rectangle above the protagonist and assumes the upper part of the image is forward. This is a camera-view assumption, not a general estimate of travel direction.
- Rules combine object class, confidence, track history, and whether an object's footpoint lies in the scan region before producing a warning.
- Results are written to **run/frames.jsonl** and **run/report.json**. With audio enabled, speech events are also written to **run/audio_events.jsonl**.
- The audio cues use local, pre-rendered English WAV files. **--no-audio** disables speech; **--stdout** prints JSONL records in the terminal.

### 2. Dataset annotation and training tools

The dataset workflow is documented in [datasets/yolo_world_sidewalk/README.md](datasets/yolo_world_sidewalk/README.md). It covers frame extraction, object-box annotation, roadway-boundary polygons, correction controls, train/validation splitting, and training commands.

- The original dataset README describes the earlier 134-frame workflow. The current 72-class reviewed-video workflow and final epoch-15 result are documented in [VIDEO_TRAINING.md](VIDEO_TRAINING.md) and [TRAINING_STATUS.md](TRAINING_STATUS.md). Raw training videos and image data remain local.
- YOLO-World is trained on object bounding boxes for walking-scene classes.
- Motor-vehicle-lane boundaries use polygon masks and a separate SegFormer training script. This is an experiment separate from the YOLO-World detector.
- Generated training outputs under **run/** and **local_training/** are not checked in. The final epoch-15 checkpoint exists locally; it is not claimed to be independently validated or best on a held-out set.

### 3. Photon and iMessage event service

The service is in **skycompanion/**. It accepts authenticated trip records from
the phone, persists records and an inbox/outbox, produces trip summaries, answers
supported questions, saves unreviewed corrections, and sends iMessage replies.

- The API includes **POST /v1/sync**, **GET /v1/messages**, **GET /v1/feedback**,
  **GET /v1/preferences**, **POST /v1/preferences/applied**, and **GET /v1/delivery**.
- Answers and preference commands use bounded English parsers and evidence-based
  templates. This is not an open-ended LLM or online model-training service.
- Ordinary alert preferences persist and sync to the phone with revision
  acknowledgements. Urgent collision alerts remain enabled.
- The phone bridge is implemented and its Swift/TypeScript contract has been tested.
  Unit tests do not prove real-account delivery or background phone speech.
- See [skycompanion/README.md](skycompanion/README.md) for configuration and API details.
  Never commit or print **.env**, pairing credentials or ingest tokens.

## Quick start: run a local video

Use Windows PowerShell from the repository root. Put a video in **videos/**; the program prefers a dated **.mp4** there and otherwise looks for **videos/walking video.mp4**.

    .\start_sky.cmd --video ".\videos\walking video.mp4" --no-audio

The launcher enables a Windows OpenMP compatibility setting and opens the display. Press **q** in the video window to exit. Omit **--no-audio** to enable local spoken cues.

To choose the model and output path explicitly:

    .\start_sky.cmd --video ".\videos\walking video.mp4" --model ".\yolov8s-worldv2.pt" --output ".\run\frames.jsonl" --no-audio

The launcher already enables **--display**. Run **python sky_companion.py --help** to see all options.

## Prepare and train the walking-scene detector

The full annotation instructions and class definitions are in [datasets/yolo_world_sidewalk/README.md](datasets/yolo_world_sidewalk/README.md). In brief:

1. Place the source walking video where the preparation script can read it. The script defaults to **walking video.mp4** in the repository root.
2. Extract missing frames and open the annotation tool:

       python prepare_yolo_world_dataset.py --interval 1
       python annotate_yolo_world.py

3. Save every frame, including frames with no target objects, and annotate the motor-vehicle-lane mask where visible.
4. Split the completed dataset and train from the checked-in YOLO-World starting weights:

       $env:KMP_DUPLICATE_LIB_OK = 'TRUE'
       python split_yolo_world_dataset.py
       python train_yolo_world.py --weights .\yolov8s-worldv2.pt --epochs 50 --imgsz 640 --batch 4 --device cpu

5. Optionally train the separate roadway-mask model after its train/validation masks are ready:

       python train_road_lane_segmenter.py --epochs 20 --batch 1 --device cpu

With a compatible CUDA-enabled PyTorch installation, use **--device 0** for YOLO-World and **--device cuda** for the SegFormer script. Inspect validation results before using any resulting weights in a demo.

To try trained YOLO-World weights with the video prototype:

    .\start_sky.cmd --video ".\videos\walking video.mp4" --model ".\run\yolo_world_finetune\sidewalk_obstacles\weights\best.pt" --no-audio

The roadway SegFormer checkpoint is not currently wired into the live video-analysis path.

## Repository map

- **sky_companion.py** — local video inference, protagonist tracking, path-region rules, warning JSONL, display, and local speech.
- **start_sky.cmd** — Windows launcher for the video prototype.
- **yolov8s-worldv2.pt** — YOLO-World starting checkpoint.
- **annotate_yolo_world.py** — interactive annotation tool for object boxes and roadway masks.
- **prepare_yolo_world_dataset.py** — extracts video frames for annotation.
- **split_yolo_world_dataset.py** — creates train/validation splits by video segment.
- **train_yolo_world.py** — fine-tunes YOLO-World on annotated object boxes.
- **train_road_lane_segmenter.py** — trains a separate SegFormer roadway mask model.
- **datasets/yolo_world_sidewalk/** — dataset instructions and, when present locally, ignored image/label data.
- **skycompanion/src/** — Photon/iMessage event API, event store, and question-answering logic.
- **skycompanion/README.md** — iMessage service setup and phone API contract.
- **assets/tts/en_short/** — local English warning audio.
- **run/** — generated video records, reports, and training outputs; local generated data is not a source deliverable.

## Known gaps and safety boundaries

- **Field validation is incomplete.** The native iOS application and screen-broadcast path are implemented, but an unsigned build does not establish sustained DJI streaming, outdoor reliability or accessibility acceptance.
- **Model accuracy remains unvalidated.** The 72-class detector has conversion-equivalence evidence, not independent accuracy acceptance. Fourteen classes lack verified positive training examples; the held-out test set has not been run.
- **Model packages are local.** Matching model binaries must be supplied separately when building a fresh clone. No downloadable model release has been published.
- **Messaging is optional.** Phone perception does not wait for Photon. The service is a single-user prototype with bounded retries; exactly-once external iMessage delivery is not guaranteed.
- **Roadway recognition is experimental.** The current video pipeline reports roadway proximity as **unknown**; candidate image edges are not verified road boundaries. The separately trained SegFormer mask is not integrated into live alerts.
- **Relative image regions are not physical distances.** **near**, **medium**, and **far** are image-based heuristics, not meters.
- **Traffic-light color is not a crossing decision.** Recognizing red or green does not establish that it is a pedestrian signal or that crossing is safe.
- **The system does not verify a safe avoidance direction.** It may report **unknown** when evidence is insufficient.
- Limited device processing measurements are documented in [mobile-world72.md](docs/mobile-world72.md). They do not establish sustained end-to-end drone-to-speech latency, battery performance, outdoor reliability or accessibility user-study outcomes.

Distinguish implemented features from measured field performance. Do not describe this prototype as a replacement for a white cane, guide dog, or independent safety judgment.

## Novelty and project positioning

Assistive drones, automatic following, obstacle perception, and audio guidance have prior examples. Relevant work includes [Flying Guide Dog (2021)](https://arxiv.org/abs/2108.07007) and [EmboDrone (2026)](https://link.springer.com/article/10.1007/s44223-026-00138-2). Phone-based visual assistance and smart-cane obstacle detection/AI assistance also exist, including [Microsoft Seeing AI](https://blogs.microsoft.com/accessibility/seeing-ai-app-launches-on-android-including-new-and-updated-features-and-new-languages/) and [WeWALK Smart Cane 2](https://support.wewalk.io/en/article/wewalk-smart-cane-2-users-manual/).

Therefore, do not claim that drone-following obstacle alerts are a first or inherently novel idea. The project's differentiation hypothesis is the **combination** of a following aerial view, on-device mobile guidance, and a persistent, conversational archive of selected walking events through iMessage. The integrated implementation still needs field demonstration and evaluation; it is not a validated comparison against existing products.

For a hackathon demo, emphasize:

- **Impact:** show a concrete walking scenario and explain how a concise alert helps the intended user.
- **Creativity:** demonstrate how the aerial following view feeds an event history that can be queried later, not only a live object label.
- **User experience:** keep alerts brief, hands-free, and evidence-based; show how the user can ask about a recorded event.

## Handoff for a new Codex chat

Start by reading this README, **datasets/yolo_world_sidewalk/README.md**, and **skycompanion/README.md**. Then inspect the current files and **git status** before making changes.

- Treat the Windows prototype and native mobile runtime as separate entry points. The mobile-to-Photon bridge uses the trip-record contract in the service README.
- Confirm whether local ignored videos, extracted frames, annotations, or trained weights exist before referring to them or changing them.
- Use the current manifests and verification reports. Do not infer field reliability or independent detection accuracy from the presence of source code, a model package or a successful build.
- Keep model evidence, rule-based estimates, and unknown states distinct. Do not convert a bounding box into real-world distance, a safe route, or permission to cross.
- Never expose **.env**, Photon credentials, or the phone-ingest token.
- Preserve the existing YOLO-World path and dataset content unless the user explicitly asks to replace or remove them.
- Before claiming real-time field performance, verify the DJI capture route and measure end-to-end alert latency on the actual device and model.

## Existing checks

The Photon service defines offline checks:

    cd skycompanion
    npm test
    npm run typecheck

These checks do not send an iMessage or verify a connected phone, a DJI feed, or the outdoor mobile experience. Run them when changing the service; no test result is implied by this README.

Raw training videos, private configuration, build caches and intermediate prediction outputs are excluded from version control. All delivered source and documentation use English and SkyCompanion project naming.
