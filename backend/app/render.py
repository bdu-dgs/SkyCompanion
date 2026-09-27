from __future__ import annotations

import cv2


def _color_bgr(seed: int) -> tuple[int, int, int]:
    """Deterministic BGR color per detection family (OpenCV uses BGR order)."""
    h = (abs(seed) * 2654435761) & 0xFFFFFFFF
    b = 80 + (h & 0x6F)
    g = 80 + ((h >> 9) & 0x6F)
    r = 80 + ((h >> 18) & 0x6F)
    return (int(b), int(g), int(r))


def _box_pixels(bbox: dict, frame_w: int, frame_h: int) -> tuple[int, int, int, int] | None:
    left = float(bbox.get("left", 0.0))
    top = float(bbox.get("top", 0.0))
    right = float(bbox.get("right", 0.0))
    bottom = float(bbox.get("bottom", 0.0))
    x1 = max(0, min(frame_w - 1, int(left * frame_w)))
    y1 = max(0, min(frame_h - 1, int(top * frame_h)))
    x2 = max(0, min(frame_w - 1, int(right * frame_w)))
    y2 = max(0, min(frame_h - 1, int(bottom * frame_h)))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _drawables_at_time(
    t: float,
    detections,
    frame_w: int,
    frame_h: int,
    max_delta: float = 0.25,
) -> list[tuple[str, int, int, int, int, tuple[int, int, int]]]:
    """Return list of (label, x1, y1, x2, y2, bgr)."""
    out: list[tuple[str, int, int, int, int, tuple[int, int, int]]] = []
    for det in detections:
        dt = abs(float(det.get("time_offset_sec", 0.0)) - t)
        if dt > max_delta:
            continue
        bbox = det.get("bbox") or {}
        box = _box_pixels(bbox, frame_w, frame_h)
        if box is None:
            continue
        track_id = det.get("track_id")
        seed = int(track_id) if track_id is not None else hash(
            (det.get("source", "unknown"), det.get("label", "object"))
        )
        color = _color_bgr(seed)
        label = str(det.get("label") or "object")
        x1, y1, x2, y2 = box
        out.append((label, x1, y1, x2, y2, color))
    return out


def _load_annotated_frames(annotated_frames: list[dict], frame_w: int, frame_h: int) -> list[dict]:
    loaded = []
    for item in annotated_frames:
        image = cv2.imread(item["image_path"])
        if image is None:
            continue
        if image.shape[1] != frame_w or image.shape[0] != frame_h:
            image = cv2.resize(image, (frame_w, frame_h))
        loaded.append(
            {
                "time_offset_sec": float(item.get("time_offset_sec", 0.0)),
                "image": image,
            }
        )
    return loaded


def _annotated_frame_at_time(t: float, annotated_frames: list[dict]):
    best_image = None
    best_dt = float("inf")
    for item in annotated_frames:
        dt = abs(float(item["time_offset_sec"]) - t)
        if dt < best_dt:
            best_dt = dt
            best_image = item["image"]
    return best_image


def draw_detections_on_video(
    input_path: str,
    output_path: str,
    detections,
    safety_advice: str | None = None,
    annotated_frames: list[dict] | None = None,
) -> None:
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {input_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps < 1:
        fps = 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, fps, (w, h))
    loaded_annotated_frames = sorted(
        _load_annotated_frames(annotated_frames or [], w, h),
        key=lambda item: item["time_offset_sec"],
    )

    frame_idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = frame_idx / fps
            annotated = _annotated_frame_at_time(t, loaded_annotated_frames)
            if annotated is not None:
                frame = annotated.copy()
            else:
                for label, x1, y1, x2, y2, color in _drawables_at_time(
                    t, detections, w, h
                ):
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(
                        frame,
                        label[:40],
                        (x1, max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        color,
                        1,
                        cv2.LINE_AA,
                )
            writer.write(frame)
            frame_idx += 1
    finally:
        cap.release()
        writer.release()
