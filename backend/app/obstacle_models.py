"""Versioned local detectors. Prompt preparation is an explicit setup step."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "data/models"
VOCABULARY_VERSION = 7
CLASSES = [
    ("person", "pedestrian"), ("bicycle", "bicycle"), ("car", "car"), ("motorcycle", "motorcycle"),
    ("bus", "bus"), ("truck", "truck"), ("train", "train"), ("traffic light", "traffic light"),
    ("traffic cone", "traffic cone"), ("construction barrel", "construction barrel"), ("trash can", "trash can"),
    ("pole", "pole"), ("bollard", "bollard"), ("fence", "fence"), ("railing", "railing"),
    ("construction barrier", "construction barrier"), ("caution tape", "caution tape"), ("box", "box"),
    ("bench", "bench"), ("potted plant", "potted plant"), ("stairs", "stairs"), ("curb", "curb"),
    ("pothole", "pothole"), ("sidewalk", "sidewalk"),
    ("tree", "tree"), ("tree trunk", "tree trunk"), ("light pole", "light pole"), ("signpost", "signpost"),
]
ALIASES = {"traffic cone": "traffic cone", "cone": "traffic cone", "garbage bin": "trash can"}
DISPLAY_NAMES = dict(CLASSES)
DISPLAY_NAMES.update({"trash": "scattered litter", "utility_pole": "utility pole", "kickboard": "scooter",
                      "damaged_braille_block": "damaged tactile paving"})
# Preserve COCO's existing categories when extending the street vocabulary.
# Prompts expand the output vocabulary; they are not supervised fine-tuning.
_vocabulary = json.loads(Path(__file__).with_name("obstacle_vocabulary.json").read_text())
CLASSES = [(name, DISPLAY_NAMES.get(name, name)) for name in _vocabulary["names"]]
PROFILES = {
    "yolo11n": {"file": "yolo11n.pt", "family": "yolo", "confidence": .35},
    "yoloe-11s": {"file": "skycompanion-yoloe-11s-v7.pt", "family": "yoloe", "confidence": .25, "imgsz": 960, "device": "auto"},
    "yoloe-11s-v2": {"file": "skycompanion-yoloe-11s-v2.pt", "family": "yoloe", "confidence": .25},
    "yoloe-11s-v1": {"file": "skycompanion-yoloe-11s-v1.pt", "family": "yoloe", "confidence": .25},
    "brailleguard-v6": {"file": "brailleguard-v6.pt", "family": "yolo", "confidence": .25},
    "skycompanion-finetuned": {"file": "skycompanion-finetuned.pt", "family": "yolo", "confidence": .25},
}


class LocalDetector:
    def __init__(self, profile=None, imgsz=None, device=None, confidence=None):
        self.profile = profile or os.environ.get("SKYCOMPANION_LIVE_MODEL", "yoloe-11s")
        if self.profile not in PROFILES:
            raise ValueError("Unknown model profile")
        self.settings = PROFILES[self.profile]
        self.path = MODEL_DIR / self.settings["file"]
        if self.profile == "yolo11n" and os.environ.get("SKYCOMPANION_YOLO_WEIGHTS"):
            self.path = Path(os.environ["SKYCOMPANION_YOLO_WEIGHTS"])
        self.imgsz = imgsz if imgsz is not None else self.settings.get("imgsz", 640)
        self.device = device or os.environ.get("SKYCOMPANION_LIVE_DEVICE") or self.settings.get("device", "cpu")
        if self.device == "auto":
            import torch
            self.device = "cuda:0" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        self.confidence = confidence if confidence is not None else self.settings["confidence"]
        self.model = None
        self._metadata = {}

    def load(self):
        from ultralytics import YOLO, YOLOE, __version__
        if not self.path.is_file():
            raise RuntimeError(f"Model is not ready: {self.profile}; run scripts/prepare_obstacle_models.py")
        self.model = (YOLOE if self.settings["family"] == "yoloe" else YOLO)(str(self.path))
        manifest_path = self.path.with_suffix(".json")
        provenance = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        self._metadata = {"name": self.profile, "family": self.settings["family"],
                          "file": self.path.name, "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                          "imgsz": self.imgsz, "confidence": self.confidence, "device": self.device,
                          "agnostic_nms": self.settings["family"] == "yoloe",
                          "ultralytics": __version__, "names": dict(self.model.names), "provenance": provenance}
        self.predict(np.zeros((640, 640, 3), dtype=np.uint8))

    def metadata(self):
        return self._metadata

    def predict(self, image):
        result = self.model.predict(image, imgsz=self.imgsz, conf=self.confidence, device=self.device,
                                    verbose=False, agnostic_nms=self.settings["family"] == "yoloe")[0]
        boxes = []
        polygons = result.masks.xyn if result.masks is not None else []
        if result.boxes is not None:
            for i, (xyxy, cls, conf) in enumerate(zip(result.boxes.xyxyn.cpu().tolist(),
                    result.boxes.cls.cpu().tolist(), result.boxes.conf.cpu().tolist())):
                x1, y1, x2, y2 = [max(0., min(1., float(v))) for v in xyxy]
                label = result.names[int(cls)]
                box = {"class_id": int(cls), "label": label, "display_label": DISPLAY_NAMES.get(label, label),
                       "confidence": float(conf), "x": x1, "y": y1, "w": max(0., x2-x1), "h": max(0., y2-y1)}
                if i < len(polygons):
                    p = polygons[i]
                    # Bound protocol size while preserving the contour for occupancy tests.
                    box["polygon"] = p[::max(1, int(np.ceil(len(p) / 96)))].round(5).tolist()
                boxes.append(box)
        return boxes
