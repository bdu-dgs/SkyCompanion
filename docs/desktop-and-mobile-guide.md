# SkyCompanion

The current phone client is a native SwiftUI app: ReplayKit capture, Core ML detection, risk processing, scene summaries, and voice all run locally on the iPhone. Select the **SkyCompanion** scheme in Xcode. The development build has been installed on an iPhone 15 Plus and passed a voice playback check; model testing and the complete drone loop remain in progress.

- [Phone implementation, build, operation, and acceptance status](mobile-app-implementation.md)
- [Model conversion and regression evidence](mobile-model-report.md)
- [Design handoff and Figma status](mobile-design.md)
- [Photon Assistant: messaging, trip summaries, and false-positive feedback](photon-assistant.md)

The earlier desktop demonstration and regression baseline material is retained below. Use the on-device instructions above for the current phone workflow.

## Legacy SkyCompanion / Gemini demo

Full-stack demo for marking ski hazards in uploaded videos. The backend sends sampled frames to a Roboflow workflow for shaded/tagged obstacle visualization, then asks Gemini on Vertex AI for a short safety summary.

## iPhone Live Screen Capture Test

The new native `SkyCompanionCapture` iPhone app and ReplayKit broadcast extension send screen frames explicitly shared by the user to local SkyCompanion Vision on the Mac (currently experimental YOLOE-11s weights), with live detections shown on the English `/live` page. This workflow does not need a cloud vision service.

- Double-click `Start SkyCompanion Live.command` in the root directory and open <http://127.0.0.1:5173/live>.
- Phone project: `ios/SkyCompanionCapture.xcodeproj`.
- [Installation, VLC transfer, and step-by-step acceptance testing](live-testing.md).
- [Test report and outstanding acceptance items](live-test-report.md).
- [Obstacle weights, failure samples, and preliminary per-class tests](obstacle-test-report.md).
- [Current nearby-object detection, 115-class vocabulary, voice on both devices, and measured limitations](vision-and-voice-update.md).

The following sections describe the original video-file and cloud-analysis workflow.

## Architecture

| Layer | Stack |
|--------|--------|
| Frontend | React + Vite — upload, job polling, progress, download |
| Backend | FastAPI — stores uploads, extracts frames, calls Roboflow, renders video |
| Visual AI | Roboflow Workflow — shaded/tagged obstacle output |
| Generative AI | Gemini on Vertex AI — safety reasoning and skier guidance |

Flow: browser uploads video -> backend extracts frames -> Roboflow returns shaded frames -> Gemini generates safety advice -> backend renders `marked_*.mp4` -> browser downloads the result.

## Backend Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env` from the example and fill in local values:

```bash
cp .env.example .env
```

Important variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_APPLICATION_CREDENTIALS` | Yes | Path to the Google service account JSON for Vertex AI / Gemini |
| `GOOGLE_CLOUD_PROJECT` | Yes | Google Cloud project ID |
| `VERTEX_AI_LOCATION` | Yes | Vertex AI region, usually `us-central1` |
| `GEMINI_MODEL` | No | Defaults to `gemini-2.5-flash` |
| `ROBOFLOW_API_KEY` | Yes | Roboflow API key |
| `ROBOFLOW_WORKSPACE` | Yes | Roboflow workspace slug |
| `ROBOFLOW_WORKFLOW_ID` | Yes | Roboflow workflow ID |
| `ROBOFLOW_IMAGE_INPUT` | No | Defaults to `image` |
| `ROBOFLOW_SAMPLE_FPS` | No | Defaults to `10.0`; higher is smoother but slower |
| `CORS_ORIGINS` | No | Defaults to local Vite dev origins |
| `MAX_UPLOAD_MB` | No | Defaults to `500` |

Run the API:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: http://127.0.0.1:8000/api/health

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend on port `8000`.

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Liveness and integration configuration |
| `POST` | `/api/jobs` | Multipart form field `file`; starts processing |
| `GET` | `/api/jobs/{job_id}` | Job status and summaries |
| `GET` | `/api/jobs/{job_id}/download` | Marked MP4 when completed |
| `GET` | `/api/jobs/{job_id}/frames.zip` | Extracted frame JPEGs |
| `DELETE` | `/api/jobs/{job_id}` | Removes job metadata and output files |

## Repository Layout

```text
backend/
  app/
    main.py              # FastAPI routes and job orchestration
    roboflow_workflow.py # Roboflow Workflow integration
    gemini_summary.py    # Gemini safety copilot
    extract_frames.py    # Frame extraction for downloads
    video_frames.py      # Sampled frame helper for Roboflow
    render.py            # OpenCV video rendering
    config.py            # Environment config
frontend/
  src/                   # React UI
```

## Notes

- Never commit `backend/.env`, Google service account JSON files, model weights, `runs/`, or generated video/frame outputs.
- Output video uses OpenCV `mp4v`. If a browser preview fails, try VLC or re-encode with FFmpeg.
- `ROBOFLOW_SAMPLE_FPS=10.0` is a practical demo default. Increase it for smoother masks, but expect slower processing and more Roboflow calls.
