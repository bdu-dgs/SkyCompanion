from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import cv2

from . import config

try:
    import vertexai
    from vertexai.generative_models import GenerationConfig, GenerativeModel, Part
except Exception:  # noqa: BLE001 - allow the app to run before deps are installed
    vertexai = None
    GenerationConfig = None
    GenerativeModel = None
    Part = None


def is_configured() -> bool:
    return bool(vertexai and config.GOOGLE_CLOUD_PROJECT and config.VERTEX_AI_LOCATION)


def _choose_key_time(detections: list[dict]) -> float:
    if not detections:
        return 0.0
    buckets = Counter(int(round(float(d.get("time_offset_sec", 0.0)))) for d in detections)
    return float(buckets.most_common(1)[0][0])


def _extract_key_frame(video_path: str, time_offset_sec: float) -> str:
    out_dir = Path(config.FRAME_DIR) / "gemini_keyframes"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{Path(video_path).stem}_{int(time_offset_sec * 1000):08d}.jpg"

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video for Gemini key frame: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps < 1:
        fps = 25.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(int(time_offset_sec * fps), 0))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("Could not extract key frame for Gemini summary.")
    if not cv2.imwrite(str(out_path), frame):
        raise RuntimeError(f"Could not write Gemini key frame: {out_path}")
    return str(out_path)


def _compact_detections(detections: list[dict], limit: int = 25) -> list[dict]:
    out: list[dict] = []
    for det in detections[:limit]:
        bbox = det.get("bbox") or {}
        out.append(
            {
                "label": det.get("label", "object"),
                "source": det.get("source", "unknown"),
                "confidence": det.get("score"),
                "time_offset_sec": round(float(det.get("time_offset_sec", 0.0)), 2),
                "bbox": {
                    "left": round(float(bbox.get("left", 0.0)), 3),
                    "top": round(float(bbox.get("top", 0.0)), 3),
                    "right": round(float(bbox.get("right", 0.0)), 3),
                    "bottom": round(float(bbox.get("bottom", 0.0)), 3),
                },
            }
        )
    return out


def _parse_json_response(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "hazard_level": "unknown",
            "primary_hazard": "Gemini returned an unstructured response.",
            "instruction": cleaned[:500],
            "speak_now": False,
        }


def build_ski_safety_summary(video_path: str, detections: list[dict]) -> dict | None:
    if not is_configured():
        return None

    key_time = _choose_key_time(detections)
    key_frame_path = _extract_key_frame(video_path, key_time)

    vertexai.init(project=config.GOOGLE_CLOUD_PROJECT, location=config.VERTEX_AI_LOCATION)
    model = GenerativeModel(config.GEMINI_MODEL)
    frame_bytes = Path(key_frame_path).read_bytes()

    prompt = f"""
You are SkyCompanion, a ski safety copilot for a hackathon demo.
Use the image and the detector output to reason about near-term skiing risk.
Focus on actionable safety guidance, not a long scene caption.

Return only valid JSON with this exact shape:
{{
  "hazard_level": "low" | "medium" | "high" | "unknown",
  "primary_hazard": "short phrase",
  "instruction": "one short action the skier should take",
  "speak_now": true | false
}}

Detector output:
{json.dumps(_compact_detections(detections), ensure_ascii=False)}
"""

    response = model.generate_content(
        [
            Part.from_data(data=frame_bytes, mime_type="image/jpeg"),
            prompt,
        ],
        generation_config=GenerationConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    summary = _parse_json_response(response.text)
    summary["key_frame_time_sec"] = key_time
    summary["model"] = config.GEMINI_MODEL
    return summary
