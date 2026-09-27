# SkyCompanion

SkyCompanion explores an assistive walking companion that combines a following drone's view, concise audio guidance, and a searchable record of walking events.

The project theme is **“Fly Me to the Moon”**: the drone offers a different, elevated perspective, while the phone turns that view into guidance a walker can use. The long-term goal is to help blind and low-vision users notice relevant obstacles and review what happened during a walk.

> **Project status:** This repository currently contains a Windows video-analysis prototype, YOLO-World dataset and training tools, and a Photon-powered iMessage/event service. It does **not** contain an iOS/Xcode app or a completed live DJI video connection. The full phone experience below is a product goal, not a claim that it is already implemented.

## What the project is aiming for

- **Aerial following view:** A DJI drone follows the walker and captures the scene ahead from above.
- **On-phone, real-time guidance:** A native iOS app analyzes the drone view locally and gives short spoken alerts about relevant objects on the walking path.
- **Questions and walk history:** The user can ask about the current or a recent walk. Selected alerts become structured route/obstacle records, and an iMessage Agent can answer questions and eventually remember user preferences.
- **Two-app iOS design:** One app obtains the DJI camera view; another packages the model and inference runtime, analyzes frames, and handles spoken guidance and user questions.
- **Computer-hosted messaging Agent:** A Photon iMessage service on a computer receives selected event summaries from the phone, stores them, and answers supported questions.

The intended flow is:

    DJI drone view
        -> iOS capture app
        -> on-device vision app: model + tracking + walking-path rules
        -> brief spoken guidance + selected structured event summaries
        -> computer-hosted Photon/iMessage service
        -> event archive, questions, and future preference memory

Only parts of this flow are currently implemented. See [Current implementation](#current-implementation) and [Known gaps and safety boundaries](#known-gaps-and-safety-boundaries).

## Current implementation

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

- The dataset README describes 134 extracted frames awaiting annotation. Image data is kept locally and is not included in this repository; check the local dataset before assuming it is present.
- YOLO-World is trained on object bounding boxes for walking-scene classes.
- Motor-vehicle-lane boundaries use polygon masks and a separate SegFormer training script. This is an experiment separate from the YOLO-World detector.
- Training outputs are written under **run/** and are not checked in. No fine-tuned **best.pt** is currently included.

### 3. Photon and iMessage event service

The service is in **skycompanion/**. It provides an authenticated phone-event API, persists received event summaries as JSONL, answers supported questions from the latest recorded walk, and can optionally send an iMessage for a fresh event.

- The API supports **POST /v1/events**, **POST /v1/query**, and **GET /health**.
- The current answer logic uses fixed, evidence-based templates; it is not an open-ended LLM agent and does not yet learn or persist user preferences.
- The service can only answer about events that have been sent to it. No iOS client currently sends live phone events from this repository.
- See [skycompanion/README.md](skycompanion/README.md) for setup, environment variables, the event schema, and API details. Never commit or print **.env** values or credentials.

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

- **No iOS/Xcode project is present.** There is no implemented iOS camera capture app, on-device model packaging, or phone speech/question interface in this repository.
- **No live drone feed is connected.** The video prototype reads a file; the proposed DJI-to-iPhone capture path has not been verified here.
- **No end-to-end phone-to-Agent bridge is complete.** The iMessage service accepts a phone API schema, but the repository does not yet contain the phone client. The Python pipeline currently emits schema version **1.1**, while the legacy desktop-event parser in the service expects **1.0**; an adapter/schema decision is needed before connecting them.
- **User preference memory is not implemented.** Current iMessage answers are template-based and grounded in stored event records.
- **Roadway recognition is experimental.** The current video pipeline reports roadway proximity as **unknown**; candidate image edges are not verified road boundaries. The separately trained SegFormer mask is not integrated into live alerts.
- **Relative image regions are not physical distances.** **near**, **medium**, and **far** are image-based heuristics, not meters.
- **Traffic-light color is not a crossing decision.** Recognizing red or green does not establish that it is a pedestrian signal or that crossing is safe.
- **The system does not verify a safe avoidance direction.** It may report **unknown** when evidence is insufficient.
- No measured end-to-end phone latency, battery performance, field reliability, or accessibility user-study results are documented yet.

Do not present the planned phone features as completed or describe this prototype as a replacement for a white cane, guide dog, or independent safety judgment.

## Novelty and project positioning

Assistive drones, automatic following, obstacle perception, and audio guidance have prior examples. Relevant work includes [Flying Guide Dog (2021)](https://arxiv.org/abs/2108.07007) and [EmboDrone (2026)](https://link.springer.com/article/10.1007/s44223-026-00138-2). Phone-based visual assistance and smart-cane obstacle detection/AI assistance also exist, including [Microsoft Seeing AI](https://blogs.microsoft.com/accessibility/seeing-ai-app-launches-on-android-including-new-and-updated-features-and-new-languages/) and [WeWALK Smart Cane 2](https://support.wewalk.io/en/article/wewalk-smart-cane-2-users-manual/).

Therefore, do not claim that drone-following obstacle alerts are a first or inherently novel idea. The project's differentiation hypothesis is the **combination** of a following aerial view, on-device mobile guidance, and a persistent, conversational archive of selected walking events through iMessage. That differentiation still needs to be implemented and demonstrated; it is not yet a validated comparison against existing products.

For a hackathon demo, emphasize:

- **Impact:** show a concrete walking scenario and explain how a concise alert helps the intended user.
- **Creativity:** demonstrate how the aerial following view feeds an event history that can be queried later, not only a live object label.
- **User experience:** keep alerts brief, hands-free, and evidence-based; show how the user can ask about a recorded event.

## Handoff for a new Codex chat

Start by reading this README, **datasets/yolo_world_sidewalk/README.md**, and **skycompanion/README.md**. Then inspect the current files and **git status** before making changes.

- Treat the Windows video prototype, training tools, and Photon service as separate components until a real adapter is implemented.
- Confirm whether local ignored videos, extracted frames, annotations, or trained weights exist before referring to them or changing them.
- Do not assume a **best.pt**, iOS app, live DJI capture, user-preference memory, or measured performance exists.
- Keep model evidence, rule-based estimates, and unknown states distinct. Do not convert a bounding box into real-world distance, a safe route, or permission to cross.
- Never expose **.env**, Photon credentials, or the phone-ingest token.
- Preserve the existing YOLO-World path and dataset content unless the user explicitly asks to replace or remove them.
- When implementing the iOS path, first prove the DJI frame-capture route, then run on-device inference and measure end-to-end alert latency before claiming a real-time phone experience.

## Existing checks

The Photon service defines offline checks:

    cd skycompanion
    npm test
    npm run typecheck

These checks do not send an iMessage or verify a connected phone, a DJI feed, or the outdoor mobile experience. Run them when changing the service; no test result is implied by this README.
