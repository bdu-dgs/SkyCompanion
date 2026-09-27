from __future__ import annotations

from collections import Counter


def make_detection(
    *,
    label: str,
    source: str,
    time_offset_sec: float,
    left: float,
    top: float,
    right: float,
    bottom: float,
    track_id: int | None = None,
    score: float | None = None,
) -> dict:
    return {
        "label": label or "object",
        "source": source,
        "track_id": track_id,
        "time_offset_sec": float(time_offset_sec),
        "bbox": {
            "left": float(left),
            "top": float(top),
            "right": float(right),
            "bottom": float(bottom),
        },
        "score": None if score is None else float(score),
    }


def summarize_detections(detections: list[dict]) -> dict:
    labels = Counter()
    sources = Counter()
    tracks: set[tuple[str, int]] = set()

    for det in detections:
        label = str(det.get("label") or "object")
        source = str(det.get("source") or "unknown")
        labels[label] += 1
        sources[source] += 1
        track_id = det.get("track_id")
        if track_id is not None:
            tracks.add((source, int(track_id)))

    return {
        "track_count": len(tracks),
        "detection_count": len(detections),
        "labels": sorted(labels.keys()),
        "by_label": dict(sorted(labels.items())),
        "by_source": dict(sorted(sources.items())),
    }
