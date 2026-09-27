from __future__ import annotations

from pathlib import Path

import cv2

from . import config


def extract_to_dir(video_path: str, job_id: str) -> tuple[str, int]:
    """
    Sample the video at approximately EXTRACT_FPS (default 5) and write JPEGs.

    Returns (absolute directory path, number of frames written).
    """
    out_dir = Path(config.FRAMES_DIR) / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    native_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if native_fps < 1.0:
        native_fps = 25.0

    target = max(0.1, float(config.EXTRACT_FPS))
    stride = max(1, int(round(native_fps / target)))

    frame_idx = 0
    saved = 0
    max_frames = int(config.EXTRACT_MAX_FRAMES)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx % stride == 0:
                out_path = out_dir / f"f_{saved:06d}.jpg"
                cv2.imwrite(
                    str(out_path),
                    frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 92],
                )
                saved += 1
                if max_frames > 0 and saved >= max_frames:
                    break
            frame_idx += 1
    finally:
        cap.release()

    if saved == 0:
        raise RuntimeError("No frames extracted (empty or unreadable video?)")

    return str(out_dir.resolve()), saved
