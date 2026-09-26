"""Local video -> YOLO-World -> JSONL -> replaceable warning sink prototype."""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import warnings
import wave
from dataclasses import dataclass

import torch  # Load PyTorch's OpenMP runtime before OpenCV in this Windows/Conda environment.
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / ".deps"))
sys.path.insert(0, str(ROOT / ".deps_overlay"))
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT))

SCHEMA_VERSION = "1.1"
OBSTACLES = {"person", "bicycle", "car", "motorcycle", "bus", "truck", "dog", "chair", "bench", "suitcase", "backpack", "skateboard", "streetlight", "railing", "bus_stop_shelter", "tree", "utility_pole"}
MOTOR_VEHICLES = {"car", "motorcycle", "bus", "truck"}
MODEL_CLASSES = ["person", "bicycle", "streetlight", "railing", "bus stop shelter", "tree",
                 "traffic light red", "traffic light green", "utility pole", "car", "motorcycle", "bus", "truck"]
CLASS_ALIASES = {"bus stop shelter": "bus_stop_shelter", "utility pole": "utility_pole",
                 "traffic light red": "traffic_light_red", "traffic light green": "traffic_light_green"}
WARNING_NOUNS = {"person": "Pedestrian", "bicycle": "Bicycle", "car": "Car", "vehicle": "Vehicle", "obstacle": "Obstacle"}
POSITION_WORDS = {"left": "left", "right": "right", "center": "ahead"}
STAIR_CLASSES = {"stair", "stairs", "step", "steps", "staircase"}


def warning_text(kind: str, direction: str) -> str:
    if kind == "stairs":
        return "Stop. Obstacle ahead."  # Existing offline cue; the JSON still identifies stairs.
    return f"Stop. {WARNING_NOUNS[kind]} {POSITION_WORDS.get(direction, 'ahead')}."


def all_warning_texts() -> set[str]:
    return {warning_text(kind, direction) for kind in WARNING_NOUNS for direction in POSITION_WORDS}


def trim_wav_silence(path: Path, threshold: int = 100) -> None:
    """Remove long SAPI lead/tail silence while leaving a small audible guard."""
    with wave.open(str(path), "rb") as wav:
        params = wav.getparams()
        frames = wav.readframes(wav.getnframes())
    if params.sampwidth != 2 or params.nchannels not in (1, 2):
        return
    samples = np.frombuffer(frames, dtype="<i2").reshape(-1, params.nchannels)
    active = np.flatnonzero(np.max(np.abs(samples.astype(np.int32)), axis=1) > threshold)
    if not len(active):
        return
    if active[0] / params.framerate < 0.04 and (len(samples) - active[-1]) / params.framerate < 0.08:
        return
    first = max(0, active[0] - round(params.framerate * 0.025))
    last = min(len(samples), active[-1] + round(params.framerate * 0.06) + 1)
    temporary = path.with_name(path.stem + ".trim.wav")
    with wave.open(str(temporary), "wb") as wav:
        wav.setparams(params)
        wav.writeframes(samples[first:last].astype("<i2", copy=False).tobytes())
    os.replace(temporary, path)


def wall_ms() -> int:
    return time.time_ns() // 1_000_000


def mono_ms() -> float:
    return time.perf_counter_ns() / 1_000_000


@dataclass
class Frame:
    frame_id: int
    video_timestamp_ms: int
    entered_at_ms: int
    entered_mono_ms: float
    scheduled_mono_ms: float
    image: np.ndarray


class LatestFrame:
    """One slot only: the producer overwrites stale, unprocessed frames."""

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.item: Frame | None = None
        self.done = False
        self.dropped = 0

    def put(self, item: Frame) -> None:
        with self.condition:
            if self.item is not None:
                self.dropped += 1
            self.item = item
            self.condition.notify()

    def get(self) -> Frame | None:
        with self.condition:
            self.condition.wait_for(lambda: self.item is not None or self.done)
            item, self.item = self.item, None
            return item

    def finish(self) -> None:
        with self.condition:
            self.done = True
            self.condition.notify_all()


class VideoSource:
    def __init__(self, path: Path, fps: float, speed: float, mailbox: LatestFrame, limit_seconds: float | None = None):
        self.path, self.fps, self.speed, self.mailbox = path, fps, speed, mailbox
        self.limit_seconds = limit_seconds
        self.metadata: dict = {}
        self.read_ms: list[float] = []
        self.intake_lag_ms: list[float] = []
        self.selected = 0
        self.error: str | None = None
        self.stop = threading.Event()

    def run(self) -> None:
        cap = cv2.VideoCapture(str(self.path))
        try:
            if not cap.isOpened():
                raise RuntimeError(f"Cannot open video: {self.path}")
            source_fps = cap.get(cv2.CAP_PROP_FPS)
            if not source_fps or source_fps <= 0:
                raise RuntimeError("Video FPS is unavailable")
            self.metadata = {"width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                             "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                             "fps": source_fps, "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT))}
            start = mono_ms()
            next_sample = 0.0
            frame_id = 0
            while True:
                if self.stop.is_set():
                    break
                t0 = mono_ms()
                ok = cap.grab()
                if not ok:
                    break
                timestamp = frame_id * 1000.0 / source_fps
                if self.limit_seconds is not None and timestamp > self.limit_seconds * 1000:
                    break
                if timestamp + 0.01 >= next_sample:
                    ok, image = cap.retrieve()
                    if not ok:
                        break
                    scheduled = start + timestamp / self.speed
                    wait = scheduled - mono_ms()
                    if wait > 0:
                        time.sleep(wait / 1000.0)
                    now = mono_ms()
                    self.intake_lag_ms.append(now - scheduled)
                    self.mailbox.put(Frame(frame_id, round(timestamp), wall_ms(), now, scheduled, image))
                    self.selected += 1
                    next_sample = (math.floor(timestamp * self.fps / 1000.0) + 1) * 1000.0 / self.fps
                self.read_ms.append(mono_ms() - t0)
                frame_id += 1
        except Exception as exc:
            self.error = str(exc)
        finally:
            cap.release()
            self.mailbox.finish()


class WarningSink:
    def publish(self, warning: dict, frame: Frame) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class NullSink(WarningSink):
    def publish(self, warning: dict, frame: Frame) -> None:
        pass


class LocalSpeechSink(WarningSink):
    """Pre-rendered Windows SAPI WAVs; only one current pending warning."""

    def __init__(self, cache_dir: Path, event_path: Path):
        if sys.platform != "win32":
            raise RuntimeError("LocalSpeechSink currently requires Windows")
        import winsound
        self.winsound = winsound
        self.cache = cache_dir
        self.cache.mkdir(parents=True, exist_ok=True)
        self.files = self._prepare_files()
        self.event_file = event_path.open("w", encoding="utf-8", buffering=1)
        self.event_lock = threading.Lock()
        self.cv = threading.Condition()
        self.pending: tuple[dict, Frame] | None = None
        self.current_key: str | None = None
        self.current_priority = -1
        self.current_until = 0.0
        self.closed = False
        self.monitor_stop = threading.Event()
        self.awaiting_onset: tuple[Frame, dict, float] | None = None
        self.active_onset: tuple[Frame, dict, float] | None = None
        self.measurement_status = "starting"
        self.monitor = threading.Thread(target=self._monitor_audio, name="audio_loopback", daemon=True)
        self.monitor.start()
        self.thread = threading.Thread(target=self._run, name="speech", daemon=True)
        self.thread.start()

    def _prepare_files(self) -> dict[str, Path]:
        import subprocess
        paths = {}
        expected = all_warning_texts()
        if any(not (self.cache / f"{message.lower().replace(' ', '_').replace('.', '')}.wav").exists()
               or (self.cache / f"{message.lower().replace(' ', '_').replace('.', '')}.wav").stat().st_size < 1000
               for message in expected):
            subprocess.run(["powershell", "-NoProfile", "-File", str(ROOT / "make_voice_cache.ps1"),
                            "-OutputDir", str(self.cache.resolve())], check=True)
        for message in expected:
            slug = message.lower().replace(" ", "_").replace(".", "")
            paths[message] = self.cache / f"{slug}.wav"
            trim_wav_silence(paths[message])
        return paths

    def publish(self, warning: dict, frame: Frame) -> None:
        with self.cv:
            if not warning["speak"]:
                if not warning["text"] or (self.pending and self.pending[0]["target_id"] != warning["target_id"]):
                    self.pending = None
                return
            if self.pending is None or warning["priority"] >= self.pending[0]["priority"]:
                self.pending = (warning, frame)
                self.cv.notify()

    def _run(self) -> None:
        while True:
            with self.cv:
                self.cv.wait_for(lambda: self.pending is not None or self.closed)
                if self.closed:
                    break
                warning, frame = self.pending
                self.pending = None
            if mono_ms() - frame.entered_mono_ms > 900:
                self._event(frame, warning, "expired", None)
                continue
            if mono_ms() < self.current_until and warning["priority"] < self.current_priority:
                self._event(frame, warning, "lower_priority", None)
                continue
            path = self.files[warning["text"]]
            requested = wall_ms()
            try:
                with self.cv:
                    self.awaiting_onset = (frame, warning, mono_ms())
                self.winsound.PlaySound(str(path), self.winsound.SND_FILENAME | self.winsound.SND_ASYNC | self.winsound.SND_NODEFAULT)
                self.current_priority = warning["priority"]
                self.current_key = warning["target_id"]
                with wave.open(str(path), "rb") as wav:
                    duration_ms = wav.getnframes() * 1000.0 / wav.getframerate()
                self.current_until = mono_ms() + duration_ms
                self._event(frame, warning, "playback_api_returned", requested)
            except Exception as exc:
                with self.cv:
                    self.awaiting_onset = None
                self._event(frame, warning, "audio_error", requested, str(exc))

    def _monitor_audio(self) -> None:
        try:
            import soundcard as sc
            loopbacks = [device for device in sc.all_microphones(include_loopback=True) if device.isloopback]
            if not loopbacks:
                self.measurement_status = "no_WASAPI_loopback_device"
                return
            device = loopbacks[0]
            self.measurement_status = "WASAPI_loopback_default_speaker"
            was_loud = False
            silence_since: float | None = None
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", sc.SoundcardRuntimeWarning)
                with device.recorder(samplerate=48000, channels=2, blocksize=480) as recorder:
                    while not self.monitor_stop.is_set():
                        chunk = recorder.record(numframes=480)
                        now = mono_ms()
                        loud = float(np.max(np.abs(chunk))) > 0.001
                        if loud and not was_loud:
                            with self.cv:
                                pending = self.awaiting_onset
                                self.awaiting_onset = None
                            if pending and 0 <= now - pending[2] < 1500:
                                frame, warning, requested_mono = pending
                                self.active_onset = (frame, warning, now)
                                self._event(frame, warning, "loopback_audio_onset", None,
                                            extra={"frame_to_audio_onset_ms": round(now - frame.entered_mono_ms, 2),
                                                   "api_to_audio_onset_ms": round(now - requested_mono, 2),
                                                   "measurement_resolution_ms": 10})
                        if loud:
                            silence_since = None
                        elif self.active_onset:
                            if silence_since is None:
                                silence_since = now
                            elif now - silence_since >= 650:
                                frame, warning, onset = self.active_onset
                                self._event(frame, warning, "loopback_audio_end", None,
                                            extra={"frame_to_audio_end_ms": round(silence_since - frame.entered_mono_ms, 2),
                                                   "playback_duration_ms": round(silence_since - onset, 2),
                                                   "measurement_resolution_ms": 10})
                                self.active_onset = None
                                silence_since = None
                        was_loud = loud
        except Exception as exc:
            self.measurement_status = f"loopback_error:{exc}"

    def _event(self, frame: Frame, warning: dict, status: str, requested_at: int | None, error: str | None = None,
               extra: dict | None = None) -> None:
        entry = {"frame_id": frame.frame_id, "target_id": warning["target_id"],
            "status": status, "entered_at_ms": frame.entered_at_ms,
            "playback_requested_at_ms": requested_at, "event_at_ms": wall_ms(), "error": error}
        if extra:
            entry.update(extra)
        with self.event_lock:
            self.event_file.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def close(self) -> None:
        with self.cv:
            self.closed = True
            self.pending = None
            self.cv.notify()
        self.thread.join(timeout=3)
        remaining = self.current_until - mono_ms()
        if remaining > 0:
            time.sleep(remaining / 1000 + 0.75)
        self.monitor_stop.set()
        self.monitor.join(timeout=3)
        self.event_file.close()


def relative_distance(y_bottom: float, height: int) -> str:
    ratio = y_bottom / height
    return "near" if ratio >= 0.82 else "medium" if ratio >= 0.62 else "far"


def signal_color(image: np.ndarray, bbox: list[int]) -> str:
    x1, y1, x2, y2 = bbox
    crop = image[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
    if crop.shape[0] < 20 or crop.shape[1] < 12:
        return "unknown"
    if cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() < 35:
        return "unknown"
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    if np.mean(hsv[:, :, 2] > 248) > 0.2:
        return "unknown"
    mask = (hsv[:, :, 1] > 105) & (hsv[:, :, 2] > 130)
    hue = hsv[:, :, 0]
    fractions = {"red": np.mean(mask & ((hue < 10) | (hue > 170))),
                 "yellow": np.mean(mask & (hue >= 17) & (hue <= 38)),
                 "green": np.mean(mask & (hue >= 40) & (hue <= 95))}
    ordered = sorted(fractions.items(), key=lambda pair: pair[1], reverse=True)
    if ordered[0][1] < 0.07 or ordered[0][1] < ordered[1][1] * 2:
        return "unknown"
    return ordered[0][0]


class SceneRules:
    def __init__(self, corridor: list[float], confidence: float, cooldown_s: float, fixed_camera: bool = False):
        self.confidence = confidence
        self.cooldown_ms = cooldown_s * 1000
        self.fixed_camera = fixed_camera
        self.history: dict[int | str, list[tuple[int, float, float, float]]] = {}
        self.last_spoken: dict[int | str, float] = {}
        self.last_global_spoken = -1e12
        self.last_global_priority = 0
        self.previous_small: np.ndarray | None = None
        self.road_line_streak = 0
        self.protagonist_track_id: int | None = None
        self.protagonist_box: list[int] | None = None
        self.protagonist_last_seen_ms = -1e12

    @staticmethod
    def _canonical_class(label: str) -> str:
        value = label.lower().strip()
        return CLASS_ALIASES.get(value, value.replace(" ", "_"))

    def _select_protagonist(self, result, frame: Frame, width: int, height: int) -> dict:
        boxes = result.boxes
        ids = boxes.id.int().cpu().tolist() if boxes.id is not None else [None] * len(boxes)
        candidates = []
        for box, cls, conf, track_id in zip(boxes.xyxy.cpu().tolist(), boxes.cls.int().cpu().tolist(),
                                             boxes.conf.cpu().tolist(), ids):
            if self._canonical_class(result.names[cls]) != "person" or track_id is None:
                continue
            x1, y1, x2, y2 = [int(round(v)) for v in box]
            center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
            candidates.append({"track_id": int(track_id), "box": [x1, y1, x2, y2], "confidence": float(conf),
                               "center": (center_x, center_y), "area": max(0, x2 - x1) * max(0, y2 - y1)})

        selected = next((item for item in candidates if item["track_id"] == self.protagonist_track_id), None)
        if selected is None and candidates and frame.video_timestamp_ms - self.protagonist_last_seen_ms <= 1200:
            # If ByteTrack briefly changes the ID, relock only to a nearby, similarly sized person.
            old = self.protagonist_box
            if old is not None:
                old_center = ((old[0] + old[2]) / 2, (old[1] + old[3]) / 2)
                old_height = max(1, old[3] - old[1])
                nearby = [item for item in candidates
                          if math.hypot((item["center"][0] - old_center[0]) / width,
                                        (item["center"][1] - old_center[1]) / height) < 0.14
                          and 0.55 <= (item["box"][3] - item["box"][1]) / old_height <= 1.8]
                if nearby:
                    selected = min(nearby, key=lambda item: math.hypot(
                        (item["center"][0] - old_center[0]) / width,
                        (item["center"][1] - old_center[1]) / height))
        if selected is None and candidates and frame.video_timestamp_ms - self.protagonist_last_seen_ms > 1200:
            # First lock: prefer the largest person nearest the horizontal camera center.
            selected = min(candidates, key=lambda item:
                2.5 * abs(item["center"][0] / width - 0.5)
                + 0.35 * abs(item["box"][3] / height - 0.78)
                - 0.18 * math.sqrt(item["area"] / (width * height)))
        if selected is not None:
            self.protagonist_track_id = selected["track_id"]
            self.protagonist_box = selected["box"]
            self.protagonist_last_seen_ms = frame.video_timestamp_ms
            status = "locked"
        elif frame.video_timestamp_ms - self.protagonist_last_seen_ms <= 1200:
            status = "temporarily_lost"
        else:
            self.protagonist_track_id = None
            self.protagonist_box = None
            status = "not_found"
        return {"status": status, "track_id": self.protagonist_track_id,
                "bbox_xyxy": self.protagonist_box if status == "locked" else None,
                "direction_basis": "assumed_upper_image_is_forward_for_rear_follow_view"}

    @staticmethod
    def _front_scan(width: int, height: int, protagonist_box: list[int] | None) -> np.ndarray | None:
        if protagonist_box is None:
            return None
        x1, y1, x2, _ = protagonist_box
        body_width = max(1, x2 - x1)
        body_height = max(1, protagonist_box[3] - y1)
        center_x = (x1 + x2) / 2
        half_width = min(width * 0.28, max(width * 0.10, body_width * 1.25))
        top = max(0, round(y1 - body_height * 0.9))
        bottom = max(0, min(height - 1, y1))
        left = max(0, round(center_x - half_width))
        right = min(width - 1, round(center_x + half_width))
        if right <= left or bottom <= top:
            return None
        return np.array([[left, top], [right, top], [right, bottom], [left, bottom]], dtype=np.int32)

    def _camera_motion(self, frame: np.ndarray) -> str:
        small = cv2.resize(frame, (320, 180))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        previous, self.previous_small = self.previous_small, gray
        if previous is None:
            return "unknown"
        points = cv2.goodFeaturesToTrack(previous, 100, 0.03, 8)
        if points is None or len(points) < 15:
            return "unknown"
        moved, status, _ = cv2.calcOpticalFlowPyrLK(previous, gray, points, None)
        if moved is None:
            return "unknown"
        flow = np.linalg.norm((moved - points)[status[:, 0] == 1], axis=1)
        if len(flow) < 15:
            return "unknown"
        return "stable" if float(np.median(flow)) < 0.35 else "moving"

    def _road_boundary(self, frame: np.ndarray) -> dict:
        small = cv2.resize(frame, (640, 360))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 70, 170)
        edges[:210, :] = 0
        edges[:, :340] = 0
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 65, minLineLength=80, maxLineGap=25)
        candidates = []
        if lines is not None:
            for x1, y1, x2, y2 in lines[:, 0]:
                length = math.hypot(x2 - x1, y2 - y1)
                if length > 90 and abs(y2 - y1) > 10:
                    candidates.append((int(x1), int(y1), int(x2), int(y2), round(length, 1)))
        self.road_line_streak = self.road_line_streak + 1 if candidates else 0
        return {"candidate_visible": bool(candidates), "candidate_streak": self.road_line_streak,
                "evidence": "edge_lines_only_unverified_as_road_boundary" if candidates else "no_reliable_edge_line"}

    def evaluate(self, frame: Frame, result, stair_result=None) -> tuple[list[dict], dict, list[dict], dict]:
        image = frame.image
        height, width = image.shape[:2]
        camera = self._camera_motion(image)
        road = self._road_boundary(image)
        protagonist = self._select_protagonist(result, frame, width, height)
        protagonist_box = protagonist["bbox_xyxy"]
        area = self._front_scan(width, height, protagonist_box)
        protagonist_center_x = ((protagonist_box[0] + protagonist_box[2]) / 2) if protagonist_box else width / 2
        area_points = area.tolist() if area is not None else []
        detections = []
        hazards = []
        light_colors = []
        boxes = result.boxes
        ids = boxes.id.int().cpu().tolist() if boxes.id is not None else [None] * len(boxes)
        for box, cls, conf, track_id in zip(boxes.xyxy.cpu().tolist(), boxes.cls.int().cpu().tolist(), boxes.conf.cpu().tolist(), ids):
            label = self._canonical_class(result.names[cls])
            xyxy = [int(round(v)) for v in box]
            x1, y1, x2, y2 = xyxy
            foot_x = (x1 + x2) / 2
            foot_y = y2
            in_path = area is not None and cv2.pointPolygonTest(area, (foot_x, foot_y), False) >= 0
            side_delta = foot_x - protagonist_center_x
            direction = "left" if side_delta < -width * 0.035 else "right" if side_delta > width * 0.035 else "center"
            distance = relative_distance(y2, height)
            is_protagonist = (protagonist["status"] == "locked" and track_id is not None
                              and int(track_id) == protagonist["track_id"])
            det = {"class": label, "confidence": round(conf, 4), "bbox_xyxy": xyxy,
                   "track_id": track_id if track_id is not None else "unknown", "direction": direction,
                   "relative_distance": distance, "in_walking_corridor": in_path,
                   "role": "protagonist" if is_protagonist else "object"}
            if label in {"traffic light", "traffic_light_red", "traffic_light_green"}:
                det["visual_signal_color"] = ("red" if label == "traffic_light_red" else
                                               "green" if label == "traffic_light_green" else signal_color(image, xyxy))
                light_colors.append(det["visual_signal_color"])
            detections.append(det)
            if is_protagonist or label not in OBSTACLES or conf < self.confidence:
                continue
            history = self.history.setdefault(track_id, []) if track_id is not None else []
            if history and frame.video_timestamp_ms - history[-1][0] > 500:
                history.clear()
            history.append((frame.video_timestamp_ms, (x2 - x1) * (y2 - y1) / (width * height), foot_y / height, float(in_path)))
            if len(history) > 5:
                del history[:-5]
            confirmed = track_id is not None and len(history) >= 2 and all(v[3] for v in history[-2:])
            approaching: bool | str = "unknown"
            if label == "person" and self.fixed_camera and len(history) >= 4 and camera == "stable":
                recent = history[-4:]
                if all(recent[i + 1][1] > recent[i][1] * 1.04 for i in range(3)) and recent[-1][2] > recent[0][2] + 0.025:
                    approaching = True
            risk = "high" if confirmed and distance == "near" else "medium" if confirmed and distance == "medium" else "unknown"
            hazards.append({"target_id": track_id if track_id is not None else "unknown", "type": label,
                            "in_path": in_path, "direction": direction, "approaching": approaching, "risk_level": risk,
                            "evidence": ["bbox_footpoint_in_configured_corridor" if in_path else "outside_configured_corridor",
                                         f"relative_image_region_{distance}", f"consecutive_track_frames_{len(history)}",
                                         f"camera_motion_{camera}"]})
        if stair_result is not None:
            boxes = stair_result.boxes
            stair_ids = boxes.id.int().cpu().tolist() if boxes.id is not None else [None] * len(boxes)
            for box, cls, conf, raw_id in zip(boxes.xyxy.cpu().tolist(), boxes.cls.int().cpu().tolist(), boxes.conf.cpu().tolist(), stair_ids):
                label = stair_result.names[cls].lower().strip()
                if label not in STAIR_CLASSES:
                    continue
                xyxy = [int(round(v)) for v in box]
                x1, y1, x2, y2 = xyxy
                foot_x, foot_y = (x1 + x2) / 2, y2
                in_path = area is not None and cv2.pointPolygonTest(area, (foot_x, foot_y), False) >= 0
                side_delta = foot_x - protagonist_center_x
                direction = "left" if side_delta < -width * 0.035 else "right" if side_delta > width * 0.035 else "center"
                distance = relative_distance(foot_y, height)
                target = f"stairs:{raw_id}" if raw_id is not None else "unknown"
                detections.append({"class": "stairs", "confidence": round(conf, 4), "bbox_xyxy": xyxy,
                                   "track_id": target, "direction": direction, "relative_distance": distance,
                                   "in_walking_corridor": in_path, "source": "stairs_model"})
                if conf < self.confidence:
                    continue
                history = self.history.setdefault(target, []) if raw_id is not None else []
                if history and frame.video_timestamp_ms - history[-1][0] > 500:
                    history.clear()
                history.append((frame.video_timestamp_ms, 0.0, foot_y / height, float(in_path)))
                if len(history) > 5:
                    del history[:-5]
                confirmed = raw_id is not None and len(history) >= 2 and all(v[3] for v in history[-2:])
                risk = "high" if confirmed and distance == "near" else "medium" if confirmed and distance == "medium" else "unknown"
                hazards.append({"target_id": target, "type": "stairs", "in_path": in_path, "direction": direction,
                                "approaching": "unknown", "risk_level": risk,
                                "evidence": ["separate_stairs_model", "bbox_footpoint_in_configured_corridor" if in_path else "outside_configured_corridor",
                                             f"relative_image_region_{distance}", f"consecutive_track_frames_{len(history)}",
                                             "step_height_and_ascent_direction_unknown"]})
        # Keep bounded state, because long videos can otherwise retain old tracks indefinitely.
        live_ids = {d["track_id"] for d in detections if d["track_id"] != "unknown"}
        for key in list(self.history):
            if key not in live_ids and self.history[key][-1][0] < frame.video_timestamp_ms - 1000:
                del self.history[key]
        scan_status = "person_anchored_front_scan" if area is not None else "awaiting_protagonist_lock"
        scene = {"walking_corridor": {"status": scan_status, "polygon_xy": area_points},
                 "protagonist": protagonist,
                 "front_scan": {"status": scan_status, "rectangle_xyxy":
                                [int(area[0, 0]), int(area[0, 1]), int(area[2, 0]), int(area[2, 1])] if area is not None else None,
                                "forward_direction": "toward_upper_image" if area is not None else "unknown"},
                 "roadway_proximity": "unknown", "road_boundary": road,
                 "traffic_light_state": "unknown", "visual_signal_colors": light_colors,
                 "traffic_light_relevance": "unknown", "about_to_turn_red": "unknown", "camera_motion": camera,
                 "stairs": {"status": "model_detection" if any(d["class"] == "stairs" for d in detections) else "unknown",
                            "reason": "model_detected_candidate" if any(d["class"] == "stairs" for d in detections) else
                                      "no_stairs_model" if stair_result is None else "no_stairs_detection"}}
        eligible = [h for h in hazards if protagonist["status"] == "locked" and h["in_path"]
                    and h["risk_level"] in {"medium", "high"}]
        eligible.sort(key=lambda h: (h["risk_level"] == "high", h["type"] == "stairs", h["type"] in MOTOR_VEHICLES), reverse=True)
        warning = {"speak": False, "text": "", "priority": 0, "target_id": "unknown",
                   "avoid_direction": "unknown", "reason": "no_confirmed_in_path_hazard"
                   if protagonist["status"] == "locked" else "protagonist_not_locked"}
        if eligible:
            hazard = eligible[0]
            target = hazard["target_id"]
            kind = "stairs" if hazard["type"] == "stairs" else "person" if hazard["type"] == "person" else "bicycle" if hazard["type"] == "bicycle" else "car" if hazard["type"] == "car" else "vehicle" if hazard["type"] in MOTOR_VEHICLES else "obstacle"
            warning.update({"text": warning_text(kind, hazard["direction"]),
                            "priority": 3 if kind == "stairs" else 2 if hazard["risk_level"] == "high" else 1,
                            "target_id": target,
                            "reason": ("stairs_model_track_confirmed;" if kind == "stairs" else "confirmed_in_corridor;") +
                                      "no_verified_safe_avoidance_side"})
            now = frame.entered_mono_ms
            target_ready = now - self.last_spoken.get(target, -1e12) >= self.cooldown_ms
            global_ready = now - self.last_global_spoken >= self.cooldown_ms or warning["priority"] > self.last_global_priority
            if target_ready and global_ready:
                warning["speak"] = True
                self.last_spoken[target] = now
                self.last_global_spoken = now
                self.last_global_priority = warning["priority"]
            else:
                warning["reason"] += ";cooldown"
        return detections, scene, hazards, warning


@lru_cache(maxsize=2)
def debug_font(size: int):
    from PIL import ImageFont
    return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)


def draw(frame: Frame, detections: list[dict], scene: dict, warning: dict, scale: float = 0.5) -> np.ndarray:
    image = cv2.resize(frame.image, None, fx=scale, fy=scale)
    area_points = scene["walking_corridor"]["polygon_xy"]
    if area_points:
        area = (np.array(area_points) * scale).astype(np.int32)
        cv2.polylines(image, [area], True, (0, 255, 255), 2)
    protagonist = scene.get("protagonist", {})
    if protagonist.get("status") != "locked":
        cv2.putText(image, "Protagonist not locked", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 180, 255), 2)
    for det in detections:
        x1, y1, x2, y2 = [round(v * scale) for v in det["bbox_xyxy"]]
        color = (255, 180, 0) if det.get("role") == "protagonist" else (0, 0, 255) if det["in_walking_corridor"] else (100, 210, 80)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        role = " MAIN" if det.get("role") == "protagonist" else ""
        cv2.putText(image, f'{det["class"]}{role} {det["confidence"]:.2f} #{det["track_id"]}', (x1, max(20, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    label = "No active warning"
    if warning["text"]:
        label = "STOP"
    cv2.putText(image, f"t={frame.video_timestamp_ms / 1000:.1f}s  {label}", (20, 34),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255) if warning["text"] else (255, 255, 255), 2)
    if warning["text"]:
        from PIL import Image, ImageDraw
        if Path("C:/Windows/Fonts/msyh.ttc").exists():
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            canvas = Image.fromarray(rgb)
            ImageDraw.Draw(canvas).text((225, 9), warning["text"], font=debug_font(28), fill=(255, 60, 60))
            image = cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)
    return image


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    return round(float(np.percentile(values, pct)), 2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    fallback_video = ROOT / "videos" / "walking video.mp4"
    dated_videos = sorted((ROOT / "videos").glob("*.mp4"))
    preferred_video = next((path for path in dated_videos if path.name != fallback_video.name), fallback_video)
    default_video = preferred_video if preferred_video.is_file() else fallback_video
    parser.add_argument("--video", type=Path, default=default_video)
    parser.add_argument("--model", type=Path, default=ROOT / "yolov8s-worldv2.pt")
    parser.add_argument("--stairs-model", type=Path, help="optional YOLO weights trained with a stair/steps class")
    parser.add_argument("--output", type=Path, default=ROOT / "run" / "frames.jsonl")
    parser.add_argument("--fps", type=float, default=10.0, help="sampled processing FPS")
    parser.add_argument("--imgsz", type=int, default=416, help="inference size; 416 is the CPU-friendly default")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--cooldown", type=float, default=5.0)
    parser.add_argument("--display", action="store_true")
    parser.add_argument("--stdout", action="store_true", help="publish each JSON line live to stdout")
    parser.add_argument("--no-audio", action="store_true", help="run rules without speech")
    parser.add_argument("--fixed-camera", action="store_true", help="allow optical approach inference only for a stationary camera")
    parser.add_argument("--limit-video-seconds", type=float, help="diagnostic: stop after this many source seconds")
    parser.add_argument("--simulate-inference-ms", type=float, default=0, help="diagnostic: model an overloaded CPU")
    args = parser.parse_args()
    if args.fps <= 0 or args.speed <= 0 or args.imgsz < 32:
        parser.error("fps/speed must be positive; imgsz >= 32")
    if not args.video.is_file() or not args.model.is_file():
        parser.error("video or model does not exist")
    if args.stairs_model is not None and not args.stairs_model.is_file():
        parser.error("stairs model does not exist")
    if args.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    from ultralytics import YOLO, YOLOWorld
    torch.set_num_threads(min(4, torch.get_num_threads()))
    model = YOLOWorld(str(args.model))
    model.set_classes(MODEL_CLASSES)
    stairs_model = YOLO(str(args.stairs_model)) if args.stairs_model else None
    if stairs_model is not None and not any(str(name).lower().strip() in STAIR_CLASSES for name in stairs_model.names.values()):
        parser.error("stairs model must have a stair, stairs, step, steps, or staircase class")
    model.track(np.zeros((640, 640, 3), dtype=np.uint8), persist=True, tracker="bytetrack.yaml",
                imgsz=args.imgsz, conf=args.conf, verbose=False, device="cpu")
    if stairs_model is not None:
        stairs_model.track(np.zeros((640, 640, 3), dtype=np.uint8), persist=True, tracker="bytetrack.yaml",
                           imgsz=args.imgsz, conf=args.conf, verbose=False, device="cpu")
    mailbox = LatestFrame()
    source = VideoSource(args.video, args.fps, args.speed, mailbox, args.limit_video_seconds)
    rules = SceneRules([], args.conf, args.cooldown, args.fixed_camera)
    sink: WarningSink = NullSink() if args.no_audio else LocalSpeechSink(ROOT / "assets" / "tts" / "en_short", args.output.parent / "audio_events.jsonl")
    times = {name: [] for name in ["yolo", "stairs_yolo", "rules", "json", "latency"]}
    started = mono_ms()
    producer = threading.Thread(target=source.run, name="video", daemon=True)
    producer.start()
    processed = 0
    warnings = 0
    try:
        with args.output.open("w", encoding="utf-8", buffering=1) as stream:
            while True:
                frame = mailbox.get()
                if frame is None:
                    break
                t0 = mono_ms()
                result = model.track(frame.image, persist=True, tracker="bytetrack.yaml", imgsz=args.imgsz,
                                     conf=args.conf, verbose=False, device="cpu")[0]
                t_stairs_start = mono_ms()
                stair_result = stairs_model.track(frame.image, persist=True, tracker="bytetrack.yaml", imgsz=args.imgsz,
                                                  conf=args.conf, verbose=False, device="cpu")[0] if stairs_model is not None else None
                t_stairs_end = mono_ms()
                if args.simulate_inference_ms:
                    time.sleep(args.simulate_inference_ms / 1000)
                inference_done = wall_ms()
                t1 = mono_ms()
                detections, scene, hazards, warning = rules.evaluate(frame, result, stair_result)
                t2 = mono_ms()
                record = {"schema_version": SCHEMA_VERSION, "frame_id": frame.frame_id,
                          "video_timestamp_ms": frame.video_timestamp_ms, "entered_at_ms": frame.entered_at_ms,
                          "inference_completed_at_ms": inference_done, "processed_at_ms": wall_ms(),
                          "detections": detections, "scene": scene, "hazards": hazards, "warning": warning,
                          "latency_ms": round(mono_ms() - frame.entered_mono_ms, 2),
                          "stage_ms": {"yolo": round(t_stairs_start - t0, 2), "stairs_yolo": round(t_stairs_end - t_stairs_start, 2),
                                       "rules": round(t2 - t1, 2),
                                       "video_intake_lag": round(frame.entered_mono_ms - frame.scheduled_mono_ms, 2)}}
                line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                write_start = mono_ms()
                stream.write(line + "\n")
                if args.stdout:
                    print(line, flush=True)
                times["json"].append(mono_ms() - write_start)
                times["yolo"].append(t_stairs_start - t0)
                times["stairs_yolo"].append(t_stairs_end - t_stairs_start)
                times["rules"].append(t2 - t1)
                times["latency"].append(record["latency_ms"])
                sink.publish(warning, frame)
                processed += 1
                warnings += int(warning["speak"])
                if args.display:
                    cv2.imshow("SkyCompanion - press q to quit", draw(frame, detections, scene, warning))
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        source.stop.set()
                        break
    finally:
        producer.join()
        sink.close()
        if args.display:
            cv2.destroyAllWindows()
    report = {"video": str(args.video), "model": str(args.model), "stairs_model": str(args.stairs_model) if args.stairs_model else None,
              "imgsz": args.imgsz, "metadata": source.metadata,
              "speed": args.speed, "target_fps": args.fps, "selected_frames": source.selected,
              "simulated_inference_ms": args.simulate_inference_ms,
              "fixed_camera": args.fixed_camera,
              "processed_frames": processed, "overwritten_frames": mailbox.dropped,
              "warning_events": warnings, "wall_runtime_s": round((mono_ms() - started) / 1000, 2),
              "stage_ms": {"read_p50": percentile(source.read_ms, 50), "read_p95": percentile(source.read_ms, 95),
                           "intake_lag_p50": percentile(source.intake_lag_ms, 50), "intake_lag_p95": percentile(source.intake_lag_ms, 95),
                           **{key + "_p50": percentile(val, 50) for key, val in times.items()},
                           **{key + "_p95": percentile(val, 95) for key, val in times.items()}},
              "audio_onset_measurement": getattr(sink, "measurement_status", "audio_disabled"),
              "source_error": source.error}
    if not args.no_audio:
        audio_events = [json.loads(line) for line in (args.output.parent / "audio_events.jsonl").open(encoding="utf-8")]
        actual = [event["frame_to_audio_onset_ms"] for event in audio_events if event["status"] == "loopback_audio_onset"]
        playback = [event["playback_duration_ms"] for event in audio_events if event["status"] == "loopback_audio_end"]
        frame_to_end = [event["frame_to_audio_end_ms"] for event in audio_events if event["status"] == "loopback_audio_end"]
        submitted = [event["event_at_ms"] - event["entered_at_ms"] for event in audio_events if event["status"] == "playback_api_returned"]
        report["audio"] = {"api_return_events": len(submitted), "measured_onset_events": len(actual),
                           "api_return_p50_ms": percentile(submitted, 50), "api_return_p95_ms": percentile(submitted, 95),
                           "actual_onset_p50_ms": percentile(actual, 50), "actual_onset_p95_ms": percentile(actual, 95),
                           "actual_onset_max_ms": max(actual) if actual else None,
                           "measured_end_events": len(playback), "playback_duration_p50_ms": percentile(playback, 50),
                           "playback_duration_p95_ms": percentile(playback, 95),
                           "frame_to_playback_end_p95_ms": percentile(frame_to_end, 95)}
    (args.output.parent / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
    if source.error:
        raise RuntimeError(source.error)


if __name__ == "__main__":
    main()

