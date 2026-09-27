from __future__ import annotations

import logging
import os
import tempfile
import shutil
import threading
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env before any app imports that touch Google Cloud clients.
_backend_root = Path(__file__).resolve().parent.parent
load_dotenv(_backend_root / ".env")

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import (
    config,
    extract_frames,
    gemini_summary,
    render,
    roboflow_workflow,
)
from .detections import summarize_detections

_log = logging.getLogger("uvicorn.error")

from .live import router as live_router, hub as live_hub, read_config as read_live_config
from .receiver_discovery import receiver_discovery
from .tts import router as tts_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    _log_google_credentials_status()
    await live_hub.start()
    await receiver_discovery.start(read_live_config)
    try:
        yield
    finally:
        await receiver_discovery.stop()
        await live_hub.stop()


app = FastAPI(title="SkyCompanion Video Marker", version="1.0.0", lifespan=lifespan)
app.include_router(live_router)
app.include_router(tts_router)


def _log_google_credentials_status() -> None:
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not path:
        _log.warning(
            "GOOGLE_APPLICATION_CREDENTIALS is not set. "
            "Put it in backend/.env and run uvicorn from the backend folder "
            "(see README). Offline cloud video jobs require it; local /live YOLO does not."
        )
    elif not Path(path).is_file():
        _log.warning(
            "GOOGLE_APPLICATION_CREDENTIALS points to a missing file (%s). "
            "Fix the path in backend/.env.",
            path,
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _ensure_dirs() -> None:
    Path(config.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.FRAMES_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.FRAME_DIR).mkdir(parents=True, exist_ok=True)


def _run_pipeline(job_id: str, input_path: str) -> None:
    roboflow_annotated_frames = []
    try:
        with _lock:
            _jobs[job_id]["status"] = "extracting"
        frames_dir, frame_count = extract_frames.extract_to_dir(input_path, job_id)
        with _lock:
            _jobs[job_id]["frames_dir"] = frames_dir
            _jobs[job_id]["frame_count"] = frame_count

        with _lock:
            _jobs[job_id]["status"] = "analyzing_obstacles"
            _jobs[job_id]["obstacle_progress"] = {
                "processed_frames": 0,
                "total_frames": 0,
            }

        def _update_obstacle_progress(processed_frames: int, total_frames: int) -> None:
            with _lock:
                if job_id in _jobs:
                    _jobs[job_id]["obstacle_progress"] = {
                        "processed_frames": processed_frames,
                        "total_frames": total_frames,
                    }

        try:
            roboflow_result = roboflow_workflow.run_workflow_on_video(
                input_path,
                progress_callback=_update_obstacle_progress,
            )
            roboflow_detections = roboflow_result["detections"]
            roboflow_annotated_frames = roboflow_result["annotated_frames"]
            roboflow_error = None
        except Exception as exc:  # noqa: BLE001 - external Roboflow should not block demo output
            roboflow_detections = []
            roboflow_annotated_frames = []
            roboflow_error = str(exc)
        obstacle_detections = roboflow_detections

        detections = obstacle_detections
        summary = summarize_detections(detections)
        with _lock:
            _jobs[job_id]["summary"] = summary
            _jobs[job_id]["obstacle_summary"] = summarize_detections(obstacle_detections)
            _jobs[job_id]["roboflow_summary"] = summarize_detections(roboflow_detections)
            _jobs[job_id]["roboflow_error"] = roboflow_error
            _jobs[job_id]["roboflow_annotated_frame_count"] = len(roboflow_annotated_frames)
            _jobs[job_id]["status"] = "rendering"
        out_path = str(Path(config.OUTPUT_DIR) / f"{job_id}_marked.mp4")

        with _lock:
            _jobs[job_id]["status"] = "summarizing"
        try:
            safety_summary = gemini_summary.build_ski_safety_summary(input_path, detections)
        except Exception as exc:  # noqa: BLE001 - Gemini should not block video output
            safety_summary = {
                "hazard_level": "unknown",
                "primary_hazard": "Gemini summary failed.",
                "instruction": "Use the marked video for visual review.",
                "speak_now": False,
                "error": str(exc),
            }
        with _lock:
            _jobs[job_id]["gemini_summary"] = safety_summary

        advice = safety_summary.get("instruction") if safety_summary else None
        with _lock:
            _jobs[job_id]["status"] = "rendering"
        render.draw_detections_on_video(
            input_path,
            out_path,
            detections,
            advice,
            roboflow_annotated_frames,
        )
        with _lock:
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["output_path"] = out_path
    except Exception as exc:  # noqa: BLE001 — surface errors to client
        with _lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = str(exc)
    finally:
        try:
            Path(input_path).unlink(missing_ok=True)
        except OSError:
            pass
        for frame in roboflow_annotated_frames:
            try:
                Path(frame["image_path"]).unlink(missing_ok=True)
            except OSError:
                pass
        if roboflow_annotated_frames:
            try:
                shutil.rmtree(Path(roboflow_annotated_frames[0]["image_path"]).parent)
            except OSError:
                pass


@app.get("/api/health")
def health() -> dict:
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    creds_ok = bool(creds and Path(creds).is_file())
    return {
        "ok": True,
        "google_credentials_file_ok": creds_ok,
        "gemini_configured": gemini_summary.is_configured(),
        "roboflow_workflow_configured": roboflow_workflow.is_configured(),
    }


@app.post("/api/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> JSONResponse:
    _ensure_dirs()
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}:
        suffix = ".mp4"

    raw = await file.read()
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
        )

    job_id = uuid.uuid4().hex
    input_path = str(Path(config.UPLOAD_DIR) / f"{job_id}{suffix}")
    Path(input_path).write_bytes(raw)

    with _lock:
        _jobs[job_id] = {
            "status": "queued",
            "filename": file.filename,
            "summary": None,
            "obstacle_summary": None,
            "roboflow_summary": None,
            "roboflow_error": None,
            "roboflow_annotated_frame_count": 0,
            "obstacle_progress": None,
            "gemini_summary": None,
            "error": None,
            "output_path": None,
            "frames_dir": None,
            "frame_count": None,
        }

    background_tasks.add_task(_run_pipeline, job_id, input_path)
    return JSONResponse({"job_id": job_id})


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return {
        "job_id": job_id,
        "status": job["status"],
        "filename": job["filename"],
        "summary": job["summary"],
        "obstacle_summary": job.get("obstacle_summary"),
        "roboflow_summary": job.get("roboflow_summary"),
        "roboflow_error": job.get("roboflow_error"),
        "roboflow_annotated_frame_count": job.get("roboflow_annotated_frame_count"),
        "obstacle_progress": job.get("obstacle_progress"),
        "gemini_summary": job.get("gemini_summary"),
        "error": job["error"],
        "frame_count": job.get("frame_count"),
    }


@app.get("/api/jobs/{job_id}/download")
def download_job(job_id: str) -> FileResponse:
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    if job["status"] != "completed" or not job.get("output_path"):
        raise HTTPException(status_code=409, detail="Job is not finished yet")
    path = Path(job["output_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Output file missing")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"marked_{job['filename'] or 'output.mp4'}",
    )


@app.get("/api/jobs/{job_id}/frames.zip")
def download_frames_zip(
    job_id: str,
    background_tasks: BackgroundTasks,
) -> FileResponse:
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    frames_dir = job.get("frames_dir")
    count = job.get("frame_count")
    if not frames_dir or count is None:
        raise HTTPException(
            status_code=409,
            detail="Frames are not ready yet (still extracting or job failed early).",
        )
    root = Path(frames_dir)
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Frames folder missing")

    jpg = sorted(root.glob("*.jpg"))
    if not jpg:
        raise HTTPException(status_code=404, detail="No frame JPEGs in frames folder")

    fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in jpg:
                zf.write(p, arcname=p.name)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    path_str = tmp_path

    def _remove_tmp() -> None:
        Path(path_str).unlink(missing_ok=True)

    background_tasks.add_task(_remove_tmp)
    return FileResponse(
        path_str,
        media_type="application/zip",
        filename=f"{job_id}_frames.zip",
    )


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    with _lock:
        job = _jobs.pop(job_id, None)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    out = job.get("output_path")
    if out:
        try:
            Path(out).unlink(missing_ok=True)
        except OSError:
            pass
    frames = Path(config.FRAMES_DIR) / job_id
    if frames.is_dir():
        shutil.rmtree(frames, ignore_errors=True)
    return {"ok": True}
