import os
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env into the process environment (never commit .env).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_ROOT / ".env")

# Resolve relative paths for the service account JSON (paths are relative to backend/).
_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
if _creds:
    p = Path(_creds)
    if not p.is_absolute():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str((_BACKEND_ROOT / p).resolve())

GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip() or None
VERTEX_AI_LOCATION = os.environ.get("VERTEX_AI_LOCATION", "").strip() or "us-central1"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-2.5-flash"
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "500")) * 1024 * 1024
ROBOFLOW_API_URL = os.environ.get("ROBOFLOW_API_URL", "").strip() or "https://serverless.roboflow.com"
ROBOFLOW_API_KEY = os.environ.get("ROBOFLOW_API_KEY", "").strip() or None
ROBOFLOW_WORKSPACE = os.environ.get("ROBOFLOW_WORKSPACE", "").strip() or None
ROBOFLOW_WORKFLOW_ID = os.environ.get("ROBOFLOW_WORKFLOW_ID", "").strip() or None
ROBOFLOW_IMAGE_INPUT = os.environ.get("ROBOFLOW_IMAGE_INPUT", "").strip() or "image"
ROBOFLOW_SAMPLE_FPS = float(os.environ.get("ROBOFLOW_SAMPLE_FPS", "10.0"))
ROBOFLOW_CONFIDENCE = float(os.environ.get("ROBOFLOW_CONFIDENCE", "0.25"))

_cors = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)
CORS_ORIGINS = [o.strip() for o in _cors.split(",") if o.strip()]

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "uploads"))
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "outputs"))
_default_frames_dir = os.path.join(os.path.dirname(__file__), "..", "data", "frames")
FRAMES_DIR = os.environ.get("FRAMES_DIR", os.environ.get("FRAME_DIR", _default_frames_dir))
FRAME_DIR = os.environ.get("FRAME_DIR", FRAMES_DIR)

# Target sampling rate for extract_frames (approximate; uses stride from container FPS).
EXTRACT_FPS = float(os.environ.get("EXTRACT_FPS", "5"))
# Cap total extracted frames (0 = no limit).
EXTRACT_MAX_FRAMES = int(os.environ.get("EXTRACT_MAX_FRAMES", "0"))
