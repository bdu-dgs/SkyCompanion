"""Bounded, opt-in evidence capture. Predictions are never ground-truth labels."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import deque
from pathlib import Path

import cv2
import numpy as np


class EvidenceBuffer:
    def __init__(self, root, max_bytes=64_000_000, seconds=12):
        self.root = Path(root)
        self.max_bytes, self.seconds = max_bytes, seconds
        self.frames = deque()
        self.bytes = 0

    def add(self, frame, packet, roi, model):
        entry = {"frame": frame, "packet": {k: v for k, v in packet.items() if k != "image_b64"},
                 "roi": roi, "model": dict(model), "display_ack": False}
        self.frames.append(entry)
        self.bytes += len(frame.jpeg)
        while self.frames and (self.bytes > self.max_bytes or
                               frame.received_at - self.frames[0]["frame"].received_at > self.seconds):
            self.bytes -= len(self.frames.popleft()["frame"].jpeg)

    def acknowledge(self, session, revision, frame_id):
        for entry in reversed(self.frames):
            f = entry["frame"]
            if (f.session_id, f.revision, f.frame_id) == (session, revision, frame_id):
                entry["display_ack"] = True
                return

    def select(self, session, revision, frame_id):
        for entry in reversed(self.frames):
            f = entry["frame"]
            if (f.session_id, f.revision, f.frame_id) == (session, revision, frame_id):
                return entry
        raise ValueError("This frame is no longer buffered; save again when the problem appears")

    def clip(self, target, before=4, after=4):
        f = target["frame"]
        entries = [e.copy() for e in self.frames if
                   (e["frame"].session_id, e["frame"].revision) == (f.session_id, f.revision)
                   and f.received_at - before <= e["frame"].received_at <= f.received_at + after]
        if not any(e["frame"].frame_id == f.frame_id for e in entries):
            entries.append(target.copy())
        return sorted(entries, key=lambda e: e["frame"].frame_id)

    def write(self, entries, target, reason, note, source_group):
        case_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        directory = self.root / case_id
        directory.mkdir(parents=True)
        records = []
        from .live import crop_image
        for e in entries:
            f = e["frame"]
            stem = str(f.frame_id).zfill(8)
            raw_name, input_name = f"{stem}-source.jpg", f"{stem}-input.png"
            (directory / raw_name).write_bytes(f.jpeg)
            image = cv2.imdecode(np.frombuffer(f.jpeg, np.uint8), cv2.IMREAD_COLOR)
            model_input = crop_image(image, e["roi"]) if e["packet"]["analysis_status"] != "unanalysed" else image
            if not cv2.imwrite(str(directory / input_name), model_input):
                raise RuntimeError("Failed to save model input")
            records.append({**e["packet"], "roi": e["roi"], "orientation": f.orientation,
                            "received_monotonic_s": f.received_at, "source_file": raw_name,
                            "input_file": input_name, "display_ack": e["display_ack"],
                            "source_sha256": hashlib.sha256(f.jpeg).hexdigest(),
                            "input_bgr_sha256": hashlib.sha256(model_input.tobytes()).hexdigest(),
                            "model": e["model"]})
        t = target["frame"]
        manifest = {"schema_version": 1, "case_id": case_id, "reason": reason, "note": note,
                    "source_group": source_group, "session_id": t.session_id, "revision": t.revision,
                    "target_frame_id": t.frame_id, "annotation_status": "unreviewed",
                    "requested_context_s": {"before": 4, "after": 4},
                    "actual_context_s": {"before": round(t.received_at - records[0]["received_monotonic_s"], 3),
                                         "after": round(records[-1]["received_monotonic_s"] - t.received_at, 3)},
                    "frames": records}
        (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        return {"case_id": case_id, "frames": len(records), "path": str(directory),
                "annotation_status": "unreviewed"}
