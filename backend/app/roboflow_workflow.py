from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import cv2

from . import config
from .detections import make_detection
from .video_frames import extract_sample_frames

try:
    from inference_sdk import InferenceHTTPClient
except Exception:  # noqa: BLE001 - allow app to run before dependency is installed
    InferenceHTTPClient = None


def is_configured() -> bool:
    return bool(
        InferenceHTTPClient
        and config.ROBOFLOW_API_KEY
        and config.ROBOFLOW_WORKSPACE
        and config.ROBOFLOW_WORKFLOW_ID
        and config.ROBOFLOW_IMAGE_INPUT
    )


@lru_cache(maxsize=1)
def _client():
    if InferenceHTTPClient is None:
        raise RuntimeError("inference-sdk is not installed. Run pip install -r requirements.txt.")
    if not config.ROBOFLOW_API_KEY:
        raise RuntimeError("ROBOFLOW_API_KEY is not configured.")
    return InferenceHTTPClient.init(
        api_url=config.ROBOFLOW_API_URL,
        api_key=config.ROBOFLOW_API_KEY,
    )


def _image_size(image_path: str) -> tuple[int, int]:
    image = cv2.imread(image_path)
    if image is None:
        raise RuntimeError(f"Could not read Roboflow frame image: {image_path}")
    h, w = image.shape[:2]
    return (w, h)


def _iter_prediction_lists(value: Any):
    if isinstance(value, dict):
        predictions = value.get("predictions")
        if isinstance(predictions, list):
            yield predictions
        for child in value.values():
            yield from _iter_prediction_lists(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_prediction_lists(item)


_VISUALIZATION_OUTPUT_KEYS = (
    "annotated_frame",
    "label_viz_image",
    "mask_viz_image",
    "visualization",
    "visualisation",
)


def _base64_image_value(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        encoded = value.get("value")
        if value.get("type") == "base64" and isinstance(encoded, str) and encoded:
            return encoded
    return None


def _iter_annotated_frames(value: Any):
    if isinstance(value, dict):
        for key in _VISUALIZATION_OUTPUT_KEYS:
            frame = _base64_image_value(value.get(key))
            if frame is not None:
                yield frame
        for key, child in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("viz", "visual", "annotated")):
                frame = _base64_image_value(child)
                if frame is not None:
                    yield frame
        for child in value.values():
            yield from _iter_annotated_frames(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_annotated_frames(item)


def _prediction_to_detection(
    prediction: dict,
    *,
    time_offset_sec: float,
    frame_w: int,
    frame_h: int,
) -> dict | None:
    label = prediction.get("class") or prediction.get("class_name") or prediction.get("label")
    score = prediction.get("confidence") or prediction.get("score")
    if score is not None and float(score) < config.ROBOFLOW_CONFIDENCE:
        return None

    if all(k in prediction for k in ("x", "y", "width", "height")):
        x = float(prediction["x"])
        y = float(prediction["y"])
        width = float(prediction["width"])
        height = float(prediction["height"])
        left = (x - width / 2) / frame_w
        top = (y - height / 2) / frame_h
        right = (x + width / 2) / frame_w
        bottom = (y + height / 2) / frame_h
    elif all(k in prediction for k in ("x1", "y1", "x2", "y2")):
        left = float(prediction["x1"]) / frame_w
        top = float(prediction["y1"]) / frame_h
        right = float(prediction["x2"]) / frame_w
        bottom = float(prediction["y2"]) / frame_h
    else:
        return None

    left = max(0.0, min(1.0, left))
    top = max(0.0, min(1.0, top))
    right = max(0.0, min(1.0, right))
    bottom = max(0.0, min(1.0, bottom))
    if right <= left or bottom <= top:
        return None

    return make_detection(
        label=str(label or "obstacle"),
        source="roboflow_workflow",
        time_offset_sec=time_offset_sec,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        score=None if score is None else float(score),
    )


def _normalize_result(result: Any, *, image_path: str, time_offset_sec: float) -> list[dict]:
    frame_w, frame_h = _image_size(image_path)
    detections: list[dict] = []
    for predictions in _iter_prediction_lists(result):
        for prediction in predictions:
            if not isinstance(prediction, dict):
                continue
            det = _prediction_to_detection(
                prediction,
                time_offset_sec=time_offset_sec,
                frame_w=frame_w,
                frame_h=frame_h,
            )
            if det is not None:
                detections.append(det)
    return detections


def _run_frame(image_path: str) -> Any:
    return _client().run_workflow(
        workspace_name=config.ROBOFLOW_WORKSPACE,
        workflow_id=config.ROBOFLOW_WORKFLOW_ID,
        images={config.ROBOFLOW_IMAGE_INPUT: image_path},
        use_cache=False,
    )


def run_workflow_on_video(
    video_path: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict:
    if not is_configured():
        return {"detections": [], "annotated_frames": []}

    frame_output_dir = str(Path(config.FRAME_DIR) / f"roboflow_input_{Path(video_path).stem}")
    annotated_output_dir = Path(config.FRAME_DIR) / f"roboflow_annotated_{Path(video_path).stem}"
    annotated_output_dir.mkdir(parents=True, exist_ok=True)
    frames = extract_sample_frames(
        video_path=video_path,
        output_dir=frame_output_dir,
        sample_fps=config.ROBOFLOW_SAMPLE_FPS,
    )

    detections: list[dict] = []
    annotated_frames: list[dict] = []
    total_frames = len(frames)
    if progress_callback is not None:
        progress_callback(0, total_frames)
    try:
        for idx, frame in enumerate(frames):
            result = _run_frame(frame["image_path"])
            detections.extend(
                _normalize_result(
                    result,
                    image_path=frame["image_path"],
                    time_offset_sec=frame["time_offset_sec"],
                )
            )
            for annotated in _iter_annotated_frames(result):
                annotated_path = annotated_output_dir / f"annotated_{idx:05d}.jpg"
                annotated_path.write_bytes(base64.b64decode(annotated))
                annotated_frames.append(
                    {
                        "image_path": str(annotated_path),
                        "time_offset_sec": frame["time_offset_sec"],
                    }
                )
                break
            if progress_callback is not None:
                progress_callback(idx + 1, total_frames)
    finally:
        for frame in frames:
            try:
                Path(frame["image_path"]).unlink(missing_ok=True)
            except OSError:
                pass
        try:
            Path(frame_output_dir).rmdir()
        except OSError:
            pass

    return {"detections": detections, "annotated_frames": annotated_frames}


def run_obstacle_detection(video_path: str) -> list[dict]:
    return run_workflow_on_video(video_path)["detections"]
