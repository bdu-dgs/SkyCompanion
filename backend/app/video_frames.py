from __future__ import annotations

import uuid
from pathlib import Path

import cv2


def extract_sample_frames(
    video_path: str,
    output_dir: str,
    sample_fps: float = 1.0,
) -> list[dict]:
    sample_fps = max(sample_fps, 0.1)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video for frame extraction: {video_path}")

    native_fps = cap.get(cv2.CAP_PROP_FPS)
    if not native_fps or native_fps < 1:
        native_fps = 25.0
    frame_interval = max(int(round(native_fps / sample_fps)), 1)
    token = uuid.uuid4().hex[:10]

    frames: list[dict] = []
    frame_idx = 0
    saved_idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx % frame_interval == 0:
                image_name = f"{token}_{saved_idx:05d}.jpg"
                image_path = Path(output_dir) / image_name
                if not cv2.imwrite(str(image_path), frame):
                    raise RuntimeError(f"Could not write frame image: {image_path}")
                frames.append(
                    {
                        "image_path": str(image_path),
                        "time_offset_sec": frame_idx / native_fps,
                    }
                )
                saved_idx += 1
            frame_idx += 1
    finally:
        cap.release()

    return frames
