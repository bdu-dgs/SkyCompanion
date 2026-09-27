"""Fixed offline warning audio; no cloud synthesis or arbitrary text endpoint.

Audio files are installed by scripts/setup_tts_assets.py. Playback, interruption,
and freshness checks belong to the selected output client, not this file server.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import wave

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response


SOURCE_URL = "https://github.com/bdu-dgs/SkyCompanion"
SOURCE_COMMIT = "e8c763f7de8f8b46ee749e3f66a704edbb141187"
ASSET_DIR = Path(__file__).resolve().parents[1] / "data" / "tts"
MAX_CLIP_BYTES = 128 * 1024
CLIPS = {
    "ahead": {
        "id": "en-obstacle-ahead", "text": "Stop. Obstacle ahead.",
        "source_file": "stop_obstacle_ahead.wav",
        "sha256": "c1f14bed369aaeb010498a005faf8df2767c6efe13018e27baf454510ca6d92a",
    },
    "left": {
        "id": "en-obstacle-left", "text": "Stop. Obstacle left.",
        "source_file": "stop_obstacle_left.wav",
        "sha256": "a3a6bccc7531630dc27c1a56f01c7e5e5710009a937229b557f86c7d54317c6b",
    },
    "right": {
        "id": "en-obstacle-right", "text": "Stop. Obstacle right.",
        "source_file": "stop_obstacle_right.wav",
        "sha256": "b0fcee4fecabeee10fa058700d756c8f408371d4339e5f55c0f30d3814514c93",
    },
}

router = APIRouter(prefix="/api/tts", tags=["offline warning audio"])


def validate_clip(data: bytes, expected_sha256: str) -> dict:
    """Validate pinned PCM bytes before serving them or reporting readiness."""
    if not data or len(data) > MAX_CLIP_BYTES:
        raise ValueError("invalid_clip_size")
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("clip_checksum_mismatch")
    try:
        with wave.open(io.BytesIO(data), "rb") as clip:
            channels = clip.getnchannels()
            sample_rate = clip.getframerate()
            sample_width = clip.getsampwidth()
            frames = clip.getnframes()
            pcm = clip.readframes(frames)
            if (
                clip.getcomptype() != "NONE" or channels != 1
                or sample_width != 2 or sample_rate != 22050
                or not frames or len(pcm) != frames * channels * sample_width
            ):
                raise ValueError("unsupported_clip_format")
    except (wave.Error, EOFError) as exc:
        raise ValueError("invalid_wav") from exc
    return {
        "duration_ms": round(frames / sample_rate * 1000, 2),
        "sample_rate": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "bytes": len(data),
    }


def _load_clip(spec: dict) -> tuple[bytes, dict]:
    # A fixed allowlist supplies every filename. Neither route nor query data
    # can select another filesystem path, voice, command, or spoken text.
    path = ASSET_DIR / f"{spec['id']}.wav"
    if path.is_symlink():
        raise ValueError("clip_symlink_not_allowed")
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_CLIP_BYTES + 1)
    except FileNotFoundError as exc:
        raise ValueError("clip_not_installed") from exc
    except OSError as exc:
        raise ValueError("clip_unreadable") from exc
    return data, validate_clip(data, spec["sha256"])


def get_tts_manifest() -> dict:
    clips = {}
    for direction, spec in CLIPS.items():
        entry = {
            "id": spec["id"], "text": spec["text"], "locale": "en-US",
            "url": f"/api/tts/clips/{spec['id']}.wav",
            "sha256": spec["sha256"], "ready": False,
        }
        try:
            _, metadata = _load_clip(spec)
            entry.update(metadata, ready=True)
        except ValueError as exc:
            entry["error"] = str(exc)
        clips[direction] = entry
    return {
        "schema_version": 1,
        "engine": "skycompanion-cached-wav",
        "ready": all(clip["ready"] for clip in clips.values()),
        "languages": ["en"],
        "clips": clips,
        "source": {"repository": SOURCE_URL, "commit": SOURCE_COMMIT},
        "playback_location": "selected_client",
        "measurement": "No acoustic onset measurement; readiness verifies audio files only.",
    }


@router.get("/manifest")
def manifest() -> dict:
    return get_tts_manifest()


@router.get("/clips/{clip_id}.wav")
def clip_audio(clip_id: str) -> Response:
    spec = next((item for item in CLIPS.values() if item["id"] == clip_id), None)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown warning clip")
    try:
        data, _ = _load_clip(spec)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="audio/wav",
        headers={
            "Cache-Control": "public, max-age=3600",
            "ETag": f'"{spec["sha256"]}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
