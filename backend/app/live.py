"""Bounded live-screen sessions, independent of the offline/cloud pipeline."""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import math
import os
import secrets
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import cv2
import numpy as np
from fastapi import APIRouter, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from PIL import Image
from .obstacle_capture import EvidenceBuffer
from .obstacle_attention import prioritize_obstacles
from .obstacle_models import LocalDetector, PROFILES, MODEL_DIR
from .obstacle_risk import RiskMonitor, validate_corridor
from .voice import VoiceChannel, VoiceOutbox, safe_event
from .scene_description import SceneDescription
from .receiver_discovery import receiver_id, receiver_discovery

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MAX_JPEG = 750_000
MAX_MESSAGE = 1_050_000
FRAME_TIMEOUT = 2.0
HEARTBEAT_TIMEOUT = 3.0


def read_config():
    path = Path(os.environ.get("SKYCOMPANION_LIVE_CONFIG", str(REPO / ".skycompanion-live/config.json")))
    return json.loads(path.read_text()) if path.exists() else {}


def normalize_roi(value):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("Crop must contain x, y, width and height")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError("Crop values must be finite numbers")
    x, y, w, h = map(float, value)
    if x < 0 or y < 0 or w < .02 or h < .02 or x + w > 1.000001 or y + h > 1.000001:
        raise ValueError("The video area must fit within the frame and be at least 2% wide and high.")
    return [x, y, min(w, 1 - x), min(h, 1 - y)]


def crop_image(image, roi):
    if roi is None:
        return image
    x, y, w, h = roi
    ih, iw = image.shape[:2]
    left, top = int(x * iw), int(y * ih)
    right, bottom = min(iw, math.ceil((x + w) * iw)), min(ih, math.ceil((y + h) * ih))
    return image[top:bottom, left:right].copy()


@dataclass
class Frame:
    session_id: str
    frame_id: int
    captured_ms: float
    width: int
    height: int
    orientation: int
    jpeg: bytes
    received_at: float
    revision: int = 0


def parse_frame(message, session_id, now):
    if message.get("session_id") != session_id:
        raise ValueError("Video session mismatch")
    frame_id = message.get("frame_id")
    captured = message.get("captured_ms")
    width, height = message.get("width"), message.get("height")
    orientation = message.get("orientation", 1)
    if type(frame_id) is not int or frame_id < 0:
        raise ValueError("Invalid frame number")
    if type(captured) not in (int, float) or not math.isfinite(captured) or captured < 0:
        raise ValueError("Invalid capture time")
    if type(width) is not int or type(height) is not int or not 1 <= width <= 960 or not 1 <= height <= 960:
        raise ValueError("Image dimensions must be between 1 and 960 pixels")
    if type(orientation) is not int or orientation not in range(1, 9):
        raise ValueError("Invalid image orientation")
    encoded = message.get("image_b64", "")
    if not isinstance(encoded, str) or len(encoded) > MAX_JPEG * 4 // 3 + 4:
        raise ValueError("Image message is too large")
    try:
        jpeg = base64.b64decode(encoded, validate=True)
        if not jpeg or len(jpeg) > MAX_JPEG:
            raise ValueError("Invalid JPEG size")
        # Inspect compressed dimensions BEFORE OpenCV allocates a decoded image.
        with Image.open(io.BytesIO(jpeg)) as image:
            if image.format != "JPEG" or image.size != (width, height):
                raise ValueError("JPEG dimensions do not match the message")
            image.verify()
    except (binascii.Error, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid JPEG data") from exc
    return Frame(session_id, frame_id, float(captured), width, height, orientation, jpeg, now)


YoloDetector = LocalDetector


class Outbox:
    """Reliable small controls plus replaceable state/frame slots per socket."""
    def __init__(self):
        self.controls = deque(maxlen=32)
        self.state = None
        self.frame = None
        self.frame_queued_at = None
        self.wake = asyncio.Event()

    def put(self, packet):
        kind = packet["type"]
        if kind == "state":
            self.state = packet
            if self.frame and (self.frame["session_id"] != packet["session_id"] or
                               self.frame["revision"] != packet["revision"]):
                self.frame = None
        elif kind == "frame":
            self.frame = packet
            self.frame_queued_at = time.monotonic()
        else:
            if len(self.controls) == self.controls.maxlen:
                raise RuntimeError("Client did not receive messages in time")
            if kind in ("voice_event", "command_reply"):
                content = packet.get("event") if kind == "voice_event" else packet.get("speech")
                if content and content.get("ttl_ms") is not None:
                    packet = {**packet, "_expires": time.monotonic()+content["ttl_ms"]/1000}
            if kind == "voice_stop":
                self.controls = deque((p for p in self.controls if p["type"] != "voice_event"
                    and not (p["type"] == "command_reply" and (p.get("speech") or {}).get("code")
                             in ("risk_explanation", "camera_obstacle", "camera_surface", "camera_overhead", "camera_vehicle"))), maxlen=32)
                self.controls.appendleft(packet)
            else:
                self.controls.append(packet)
        self.wake.set()

    async def pump(self, socket):
        while True:
            await self.wake.wait()
            if self.controls:
                packet = self.controls.popleft()
                if "_expires" in packet:
                    packet = dict(packet)
                    remaining = int((packet.pop("_expires")-time.monotonic())*1000)
                    if remaining <= 0:
                        continue
                    key = "event" if packet["type"] == "voice_event" else "speech"
                    packet[key] = {**packet[key], "ttl_ms": remaining}
            elif self.state:
                packet, self.state = self.state, None
            elif self.frame:
                packet, self.frame = self.frame, None
                packet = {**packet, "server_frame_age_ms": packet.get("server_frame_age_ms", 0)
                          + max(0, (time.monotonic()-(self.frame_queued_at or time.monotonic()))*1000)}
            else:
                self.wake.clear()
                continue
            await asyncio.wait_for(socket.send_json(packet), timeout=2)


class LiveHub:
    def __init__(self, detector=None, clock=time.monotonic):
        self.detector = detector or YoloDetector()
        self.clock = clock
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="skycompanion-yolo")
        self.tasks = []
        self.source_socket = None
        self.source_out = None
        self.viewer_out = None
        self.pending = None
        self.work_available = asyncio.Event()
        self.model = {"state": "loading", "name": getattr(self.detector, "profile", "yoloe-11s"), "device": "cpu", "error": None}
        self.session_id = None
        self.revision = 0
        self.roi_version = 0
        self.connection = "waiting"
        self.capture = "waiting"
        self.source = None
        self.analysis_enabled = False
        self.roi = None
        self.dimensions = None
        self.orientation = None
        self.message = "Waiting for the phone to start a screen broadcast."
        self.last_frame = None
        self.last_heartbeat = None
        self.last_frame_id = -1
        self.session_started = self.clock()
        self.received_times = deque(maxlen=1000)
        self.processed_times = deque(maxlen=1000)
        self.latencies = deque(maxlen=4096)
        self.published = deque(maxlen=128)
        self.received_frames = 0
        self.processed_frames = 0
        self.dropped_frames = 0
        self.queue_ms = None
        self.inference_ms = None
        self.evidence = EvidenceBuffer(ROOT / "data/obstacle_cases")
        self.evidence_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="skycompanion-evidence")
        self.saving_case = False
        self.case_tasks = set()
        self.corridor = None
        self.risk_monitor = RiskMonitor()
        self.scene_description = SceneDescription()
        self.voice = VoiceChannel(self.clock)
        self.mobile_guidance = None
        self.mobile_arm_deadline = None
        self.mobile_session = None
        self.last_mobile_command = None
        self.latest_risk = None
        self.latest_risk_at = None
        self.latest_capture_uptime_ms = None
        self.latest_event = None
        self.latest_event_deadline = None
        self._perception_status = "unavailable"
        self._perception_seen_live = False
        self._perception_recovering_since = None
        self._fault_stopped_visual = False
        self._health_event_history = deque(maxlen=256)
        self.last_false_alert = None

    async def start(self):
        if self.tasks:
            return
        self.tasks = [asyncio.create_task(self.load_model()), asyncio.create_task(self.worker()),
                      asyncio.create_task(self.watchdog())]

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)
        for task in self.case_tasks:
            task.cancel()
        await asyncio.gather(*self.case_tasks, return_exceptions=True)
        self.evidence_executor.shutdown(wait=False, cancel_futures=True)

    async def save_case(self, message):
        if self.saving_case:
            raise ValueError("The previous sample is still being saved. Please wait.")
        reason = message.get("reason", "review")
        if reason not in ("missed_obstacle", "wrong_label", "suspected_train", "review"):
            raise ValueError("Invalid sample type.")
        note, group = message.get("note", ""), message.get("source_group", "")
        if not isinstance(note, str) or not isinstance(group, str) or len(note) > 500 or len(group) > 120:
            raise ValueError("The sample description is too long or has an invalid format.")
        target = self.evidence.select(message.get("session_id"), message.get("revision"), message.get("frame_id"))
        self.saving_case = True
        # Pin pre-roll now so slow disks / a context change cannot evict the target.
        before = self.evidence.clip(target, after=0)
        try:
            await asyncio.sleep(4)
            after = self.evidence.clip(target, before=0)
            entries = {e["frame"].frame_id: e for e in before + after}
            entries = [entries[k] for k in sorted(entries)]
            return await asyncio.get_running_loop().run_in_executor(
                self.evidence_executor, self.evidence.write, entries, target, reason, note, group)
        finally:
            self.saving_case = False

    async def load_model(self):
        try:
            await asyncio.get_running_loop().run_in_executor(self.executor, self.detector.load)
            self.model = self.ready_model_state()
        except Exception as exc:
            self.model = {**self.model, "state": "error", "error": str(exc)[:300]}
        self.publish_state()

    def ready_model_state(self):
        metadata = getattr(self.detector, "metadata", lambda: {})()
        return {"state": "ready", "name": getattr(self.detector, "profile", "yolo11n"),
                "device": getattr(self.detector, "device", "cpu"), "error": None,
                "file": metadata.get("file"), "sha256": metadata.get("sha256"),
                "vocabulary_version": metadata.get("provenance", {}).get("vocabulary_version"),
                "class_count": len(metadata.get("names", {}))}

    async def switch_model(self, profile):
        if profile not in PROFILES or not (MODEL_DIR / PROFILES[profile]["file"]).is_file():
            raise ValueError("Candidate weights are not ready; cannot switch models")
        if self.model["state"] == "loading":
            raise ValueError("Model is loading")
        self.invalidate("Updating SkyCompanion Vision. Restart analysis when loading finishes.")
        self.model = {**self.model, "state": "loading", "error": None}
        self.publish_state()
        candidate = LocalDetector(profile)
        try:
            await asyncio.get_running_loop().run_in_executor(self.executor, candidate.load)
        except Exception as exc:
            self.model = {**self.model, "state": "ready", "error": None}
            self.message = "Candidate model failed to load; original model retained: " + str(exc)[:150]
        else:
            self.detector = candidate
            self.model = self.ready_model_state()
            self.message = "SkyCompanion Vision is ready. Start analysis; additional classes are still being evaluated."
        self.publish_state()

    def metrics(self):
        now = self.clock()
        window = max(1., min(10., now - self.session_started))
        samples = sorted(self.latencies)
        percentile = lambda p: samples[max(0, math.ceil(len(samples) * p) - 1)] if samples else None
        return {"received_fps": round(sum(t > now - 10 for t in self.received_times) / window, 2),
                "processed_fps": round(sum(t > now - 10 for t in self.processed_times) / window, 2),
                "dropped_frames": self.dropped_frames, "received_frames": self.received_frames,
                "processed_frames": self.processed_frames, "queue_ms": self.queue_ms,
                "inference_ms": self.inference_ms, "roundtrip_p50_ms": percentile(.5),
                "roundtrip_p95_ms": percentile(.95)}

    def perception(self):
        """Receive-time freshness is not an end-to-end source latency measurement."""
        age = None if self.latest_risk_at is None else self.clock()-self.latest_risk_at
        if self.connection != "connected":
            reason = "input_disconnected"
        elif self.model.get("state") != "ready":
            reason = "model_unavailable"
        elif not self.analysis_enabled:
            reason = "analysis_paused"
        elif self.capture != "receiving" or age is None or not 0 <= age < 1.5:
            reason = "observations_stale"
        elif self.corridor is None:
            reason = "corridor_unconfigured"
        else:
            reason = "camera_geometry_only"
        usable = reason == "camera_geometry_only"
        return {"status": "limited" if usable else "unavailable", "reason": reason,
                "frame_age_ms": None if age is None else round(max(0, age)*1000),
                "freshness_basis": "Mac_receive_time_phone_rechecks_capture_uptime",
                "wearer_pose_available": False, "distance_available": False,
                "foot_clearance_known": False, "body_clearance_known": False, "head_clearance_known": False,
                "image_corridor_is_walking_path": False}

    def current_risk(self):
        if not self.latest_risk:
            return None
        result = {**self.latest_risk, "event": None}
        if self.perception()["status"] == "unavailable":
            result.update(state="unavailable", risk_level=None, direction=None,
                          direction_frame="unavailable", stale=True)
        return result

    def deliver_event(self, event, age_ms=0, captured_uptime_ms=None, mac=True):
        event = safe_event(event)
        if event is None:
            return
        if event.get("priority") in ("obstacle", "urgent"):
            self._fault_stopped_visual = False
        self.voice.publish(event, age_ms, captured_uptime_ms)
        if mac and self.viewer_out and self.voice.output in ("mac", "both"):
            remaining = int(event["ttl_ms"]-max(0, age_ms))
            if remaining > 0:
                self.viewer_out.put({"type": "voice_event", "event": {**event, "ttl_ms": remaining}})

    def refresh_perception(self):
        health = self.perception()
        status, now = health["status"], self.clock()
        # Recovery must remain fresh for a short interval; faults are immediate.
        if status == "limited":
            if self._perception_recovering_since is None:
                self._perception_recovering_since = now
            if now-self._perception_recovering_since < .5:
                return
        else:
            self._perception_recovering_since = None
        if status == self._perception_status:
            return
        self._perception_status = status
        if status == "unavailable":
            self.voice.stop("perception_unavailable")
            if self.viewer_out:
                self.viewer_out.put({"type": "voice_stop", "reason": "perception_unavailable"})
            self._fault_stopped_visual = True
            code = "perception_unavailable"
        else:
            self._fault_stopped_visual = False
            code = "perception_restored" if self._perception_seen_live else "direction_unverified"
            self._perception_seen_live = True
        self._health_event_history.append({"at_s": now, "status": status, "reason": health["reason"]})
        self.deliver_event({"id": uuid.uuid4().hex, "schema_version": 2,
            "speech_code": code, "priority": "health", "direction": "ahead",
            "direction_frame": "unavailable", "risk_level": None, "ttl_ms": 1500})

    def state(self):
        return {"type": "state", "session_id": self.session_id, "revision": self.revision,
                "connection": self.connection, "capture": self.capture, "source": self.source,
                "analysis_enabled": self.analysis_enabled, "roi": self.roi,
                "roi_version": self.roi_version, "dimensions": self.dimensions,
                "orientation": self.orientation,
                "model": self.model.copy(), "metrics": self.metrics(), "message": self.message,
                "last_mobile_command": self.last_mobile_command,
                "risk": self.current_risk(), "perception": self.perception(),
                "risk_preferences": {"quiet": getattr(self.risk_monitor, "quiet", False)},
                "last_false_alert": self.last_false_alert,
                "mobile_guidance": {"enabled": self.mobile_guidance is not None, "armed": self.mobile_arm_deadline is not None, "basis": "user_selected_test_corridor_not_free_space"},
                "corridor": self.corridor, "voice": self.voice.state(), "available_models": [key for key, profile in PROFILES.items()
                    if (MODEL_DIR / profile["file"]).is_file()]}

    def publish_state(self):
        self.refresh_perception()
        if self.viewer_out:
            self.viewer_out.put(self.state())

    def invalidate(self, message, reset_crop=False):
        # The freshness watchdog may already have stopped visual speech and
        # started a fault notice. A later transport timeout must not cut it off.
        if not self._fault_stopped_visual:
            self.voice.stop("video_context_invalidated")
            if self.viewer_out:
                self.viewer_out.put({"type": "voice_stop", "reason": "video_context_invalidated"})
        self.latest_risk = self.latest_risk_at = self.latest_capture_uptime_ms = None
        self.latest_event = self.latest_event_deadline = None
        self.revision += 1
        self.analysis_enabled = False
        if self.pending:
            self.dropped_frames += 1
        self.pending = None
        self.published.clear()
        self.risk_monitor.reset()
        self.scene_description.reset()
        if reset_crop:
            self.corridor = None
            self.roi = None
            self.roi_version += 1
        self.message = message

    def begin(self, source, socket=None):
        self.invalidate("Connected. Switch to your video player, then confirm the video area and start analysis here.", reset_crop=True)
        self.session_id = str(uuid.uuid4())
        if self.mobile_arm_deadline is not None and self.clock() <= self.mobile_arm_deadline:
            self.mobile_session = self.session_id
        else:
            self.mobile_guidance = None
            self.mobile_session = None
        self.mobile_arm_deadline = None
        self.connection, self.capture = "connected", "waiting"
        self.source = source
        self.dimensions = self.orientation = None
        self.last_frame = None
        self.last_frame_id = -1
        self.last_heartbeat = self.session_started = self.clock()
        self.received_times.clear()
        self.processed_times.clear()
        self.latencies.clear()
        self.received_frames = self.processed_frames = self.dropped_frames = 0
        self.queue_ms = self.inference_ms = None
        self.source_socket = socket
        self.source_out = Outbox()
        self.source_out.put({"type": "session", "session_id": self.session_id})
        self.publish_state()
        return self.session_id

    def end(self, session_id, intentional=False):
        if session_id != self.session_id:
            return
        self.connection = "ended" if intentional else "disconnected"
        self.capture = "ended" if intentional else "no_frames"
        self.invalidate("Input ended." if intentional else "Input interrupted. Waiting to reconnect.")
        self.source_socket = self.source_out = None
        self.mobile_guidance = self.mobile_session = self.mobile_arm_deadline = None
        self.publish_state()

    def accept_frame(self, frame):
        if frame.session_id != self.session_id or self.connection != "connected":
            raise ValueError("The video session has ended.")
        if frame.frame_id <= self.last_frame_id:
            raise ValueError("Frame numbers must increase")
        self.last_frame_id = frame.frame_id
        if self.capture == "paused":
            self.dropped_frames += 1
            return
        new_dimensions = [frame.width, frame.height]
        if self.dimensions and (new_dimensions != self.dimensions or frame.orientation != self.orientation):
            self.invalidate("The video orientation or size changed. Select the video area again.", reset_crop=True)
        self.dimensions, self.orientation = new_dimensions, frame.orientation
        self.last_frame = frame.received_at
        self.capture = "receiving"
        # A user explicitly arms full-screen landscape test playback on the phone.
        # Portrait app controls are never silently treated as a walking scene.
        if self.mobile_guidance and self.mobile_session == self.session_id:
            landscape = frame.width > frame.height
            if landscape and self.model["state"] == "ready" and not self.analysis_enabled:
                self.roi = self.mobile_guidance["roi"]
                self.corridor = self.mobile_guidance["corridor"]
                self.analysis_enabled = True
                self.message = "Phone-controlled landscape test analysis"
            elif not landscape and self.analysis_enabled:
                self.invalidate("Phone test paused in portrait; return to landscape playback")
        self.received_times.append(frame.received_at)
        self.received_frames += 1
        if self.pending:
            self.dropped_frames += 1
        frame.revision = self.revision
        self.pending = frame
        self.work_available.set()
        self.publish_state()

    def configure(self, message):
        if message.get("session_id") != self.session_id or self.connection != "connected":
            raise ValueError("Connect a video source first.")
        roi = normalize_roi(message.get("roi"))
        enabled = message.get("analysis_enabled")
        if type(enabled) is not bool:
            raise ValueError("analysis_enabled must be a boolean")
        if enabled and (self.model["state"] != "ready" or self.capture != "receiving" or
                        self.last_frame is None or self.clock() - self.last_frame >= FRAME_TIMEOUT):
            raise ValueError("A current frame and a ready model are required to start analysis.")
        changed_crop = roi != self.roi
        self.invalidate("Analyzing the current video." if enabled else "Analysis paused. You can now confirm the video area.")
        self.roi = roi
        if changed_crop:
            self.corridor = None
            self.roi_version += 1
        self.analysis_enabled = enabled
        # Keep preview acknowledgements out of the next analysis latency run.
        self.latencies.clear()
        self.publish_state()

    def mobile_command(self, message):
        command = message.get("command")
        speech = None
        if command in ("start", "start_analysis"):
            roi = normalize_roi(message.get("roi", [0, 0, 1, 1]))
            corridor = validate_corridor(message.get("corridor"))
            if roi is None or corridor is None:
                raise ValueError("Confirm a video area and experimental image corridor first")
            self.invalidate("Phone test armed; start broadcast and play landscape video")
            self.mobile_guidance = {"roi": roi, "corridor": corridor}
            if self.connection == "connected":
                self.mobile_session = self.session_id
                self.mobile_arm_deadline = None
            else:
                self.mobile_session = None
                self.mobile_arm_deadline = self.clock() + 120
        elif command in ("pause", "pause_analysis"):
            self.mobile_guidance = self.mobile_session = self.mobile_arm_deadline = None
            self.invalidate("Analysis paused from phone")
        elif command in ("voice_output", "mute", "unmute"):
            output = "off" if command == "mute" else "phone" if command == "unmute" else message.get("output")
            self.voice.select(output)
        elif command == "voice_test":
            if self.voice.output not in ("phone", "both") or self.voice.phone is None:
                raise ValueError("Connect phone voice and select Phone or Both first")
            self.voice.publish({"id": uuid.uuid4().hex, "direction": "ahead", "priority": "test", "ttl_ms": 1500})
        elif command == "repeat":
            # Re-evaluate current tracked occupancy, never revive the last spoken queue item.
            summary = self.risk_monitor.describe(self.clock())
            if (self.analysis_enabled and self.latest_risk_at is not None
                    and 0 <= self.clock()-self.latest_risk_at < 1.5
                    and summary.get("state") == "occupied" and summary.get("ttl_ms", 0) > 0
                    and summary.get("lifecycle", "observed") == "observed"
                    and summary.get("direction") in ("ahead", "left", "right")
                    and (self.voice.output in ("mac", "both") or
                         (self.voice.output == "phone" and self.voice.phone is not None))):
                event = {**summary, "id": uuid.uuid4().hex, "schema_version": 2,
                         "direction_frame": "camera_image", "speech_code": summary.get("speech_code", "camera_obstacle"),
                         "risk_level": summary.get("risk_level", "R2"),
                         "priority": "urgent" if summary.get("risk_level") == "R3" else "obstacle"}
                self.deliver_event(event, captured_uptime_ms=self.latest_capture_uptime_ms)
            else:
                speech = {"code": "no_recent_alert", "direction": "ahead"}
        elif command == "explain":
            if not self.analysis_enabled:
                speech = {"code": "vision_unavailable"}
            else:
                speech = self.risk_monitor.explain(self.clock())
        elif command == "acknowledge":
            speech = self.risk_monitor.acknowledge()
            # Acknowledgement changes repetition preference, not risk existence.
        elif command in ("quiet", "normal"):
            speech = self.risk_monitor.set_quiet(command == "quiet")
        elif command == "describe":
            if (not self.analysis_enabled or self.latest_risk_at is None
                    or self.clock()-self.latest_risk_at > 1.5):
                speech = {"code": "vision_unavailable", "direction": "ahead"}
            else:
                speech = self.scene_description.describe(self.clock())
        else:
            raise ValueError("Unknown mobile command")
        if (speech and command in ("describe", "explain")
                and speech["code"] not in ("vision_unavailable", "no_recent_alert", "risk_unresolved")
                and self.latest_risk_at is not None):
            speech.update(captured_uptime_ms=self.latest_capture_uptime_ms, max_observation_age_ms=1500,
                          ttl_ms=max(0, int((1.5-(self.clock()-self.latest_risk_at))*1000)))
        elif speech and speech.get("code") in ("vision_unavailable", "risk_unresolved", "no_recent_alert"):
            # A fresh answer ABOUT unavailable evidence does not renew that evidence.
            speech = {"code": speech["code"], "ttl_ms": 1500, "direction": None}
        self.last_mobile_command = {"command": command, "at_monotonic_s": self.clock(), "accepted": True}
        self.publish_state()
        return {"ok": True, "state": self.state(), "speech": speech}

    async def handle_command(self, message):
        if message.get("command") != "report_false_alert":
            return self.mobile_command(message)
        # Pin the actual frame context before awaiting clip post-roll; do not save
        # some newer unrelated frame after a slow request or source switch.
        if (not self.evidence.frames or self.latest_risk_at is None
                or not 0 <= self.clock()-self.latest_risk_at < 1.5):
            return {"ok": False, "state": self.state(), "speech": {"code": "no_evidence"}}
        entry = self.evidence.frames[-1]
        frame = entry["frame"]
        risk = self.current_risk() or {}
        message = {"session_id": frame.session_id, "revision": frame.revision, "frame_id": frame.frame_id,
                   "reason": "wrong_label", "source_group": "user_reported_risk",
                   "note": json.dumps({"user_report": "false_alert", "track_id": risk.get("track_id"),
                           "risk_level": risk.get("risk_level"), "reasons": risk.get("reason_codes", [])})[:500]}
        saved = await self.save_case(message)
        self.last_false_alert = {"case_id": saved["case_id"], "at_monotonic_s": self.clock()}
        self.publish_state()
        return {"ok": True, "state": self.state(), "speech": {"code": "false_alert_saved"}, "case": saved}

    def check_freshness(self):
        self.refresh_perception()
        if self.connection != "connected":
            return None
        now = self.clock()
        if self.last_heartbeat is not None and now - self.last_heartbeat > HEARTBEAT_TIMEOUT:
            socket = self.source_socket
            self.end(self.session_id)
            return socket
        if self.capture == "receiving" and self.last_frame is not None and now - self.last_frame > FRAME_TIMEOUT:
            self.capture = "no_frames"
            self.invalidate("Connected, but no new frames are arriving. Restart analysis when the video resumes.")
            self.publish_state()
        return None

    async def watchdog(self):
        last_state = 0.
        while True:
            await asyncio.sleep(.25)
            socket = self.check_freshness()
            if socket:
                try:
                    await asyncio.wait_for(socket.close(code=4008, reason="heartbeat timeout"), 1)
                except Exception:
                    pass
            if self.clock() - last_state >= 1:
                self.publish_state()
                last_state = self.clock()

    def process(self, frame, roi, enabled):
        started = self.clock()
        queue_ms = max(0., (started - frame.received_at) * 1000)
        if not enabled:
            return frame.jpeg, frame.width, frame.height, [], "unanalysed", queue_ms, 0., None
        image = cv2.imdecode(np.frombuffer(frame.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Cannot decode the current JPEG")
        image = crop_image(image, roi)
        inference_start = self.clock()
        error = None
        try:
            boxes = prioritize_obstacles(self.detector.predict(image))
            status = "ok" if boxes else "empty"
        except Exception as exc:
            boxes, status, error = [], "error", str(exc)[:300]
        inference_ms = max(0., (self.clock() - inference_start) * 1000)
        success, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not success:
            raise ValueError("Cannot encode the current frame")
        return encoded.tobytes(), image.shape[1], image.shape[0], boxes, status, queue_ms, inference_ms, error

    async def worker(self):
        loop = asyncio.get_running_loop()
        while True:
            await self.work_available.wait()
            self.work_available.clear()
            frame, self.pending = self.pending, None
            if frame is None:
                continue
            if self.clock() - frame.received_at > FRAME_TIMEOUT:
                self.dropped_frames += 1
                continue
            roi, enabled, roi_version = self.roi, self.analysis_enabled, self.roi_version
            try:
                result = await loop.run_in_executor(self.executor, self.process, frame, roi, enabled)
            except Exception as exc:
                if frame.session_id == self.session_id and frame.revision == self.revision:
                    self.invalidate("Image processing failed: " + str(exc)[:200])
                    self.publish_state()
                continue
            if (frame.session_id != self.session_id or frame.revision != self.revision or
                    self.connection != "connected" or self.capture != "receiving" or
                    self.clock() - frame.received_at > FRAME_TIMEOUT):
                self.dropped_frames += 1
                continue
            jpeg, width, height, boxes, status, queue_ms, infer_ms, error = result
            self.queue_ms, self.inference_ms = round(queue_ms, 2), round(infer_ms, 2)
            if enabled:
                self.processed_times.append(self.clock())
                self.processed_frames += 1
            if error:
                self.model = {**self.model, "state": "error", "error": error}
                self.analysis_enabled = False
                self.message = "Analysis failed. Check the receiver and restart the model."
                self.publish_state()
            packet = {"type": "frame", "session_id": frame.session_id, "revision": frame.revision,
                      "roi_version": roi_version, "frame_id": frame.frame_id,
                      "captured_ms": frame.captured_ms, "width": width, "height": height,
                      "image_b64": base64.b64encode(jpeg).decode("ascii"), "analysis_status": status,
                      "boxes": boxes, "queue_ms": self.queue_ms, "inference_ms": self.inference_ms}
            packet["risk"] = self.risk_monitor.update(boxes, self.corridor, frame.received_at) if enabled and not error else None
            packet["server_frame_age_ms"] = round((self.clock() - frame.received_at) * 1000, 2)
            if enabled and not error:
                self.scene_description.update(boxes, frame.received_at)
            else:
                self.scene_description.reset()
            self.latest_risk = packet["risk"]
            self.latest_risk_at = frame.received_at if enabled and not error else None
            self.latest_capture_uptime_ms = frame.captured_ms if enabled and not error else None
            if packet["risk"]:
                event = packet["risk"].get("event")
                if event:
                    self.latest_event = {**event, "captured_uptime_ms": frame.captured_ms}
                    self.latest_event_deadline = frame.received_at + event["ttl_ms"] / 1000
                self.deliver_event(packet["risk"].get("event"), packet["server_frame_age_ms"], frame.captured_ms, mac=False)
            self.refresh_perception()
            metadata = getattr(self.detector, "metadata", lambda: self.model)()
            self.evidence.add(frame, packet, roi, metadata)
            self.published.append((frame.frame_id, frame.revision))
            if self.viewer_out:
                self.viewer_out.put(packet)


hub = LiveHub()
router = APIRouter(prefix="/api/live")


@router.get("/health")
def health():
    config = read_config()
    return {"protocol_version": 1, "configured": bool(config.get("token")), "model": hub.model,
            "receiver_id": receiver_id(config), "discovery": receiver_discovery.snapshot()}


def authenticated_mobile(request):
    token = read_config().get("token", "")
    supplied = request.headers.get("authorization", "")
    if not token or not secrets.compare_digest(supplied, "Bearer " + token):
        raise HTTPException(401, "Pairing required")
    if request.headers.get("origin"):
        raise HTTPException(403, "Native mobile endpoint")


@router.get("/mobile/state")
def mobile_state(request: Request):
    authenticated_mobile(request)
    return hub.state()


@router.post("/mobile/command")
async def mobile_command(request: Request):
    authenticated_mobile(request)
    payload = await request.body()
    if len(payload) > 8192:
        raise HTTPException(413, "Command too large")
    try:
        message = json.loads(payload)
        if not isinstance(message, dict):
            raise ValueError("Command must be an object")
        return await hub.handle_command(message)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/report")
def report(request: Request):
    if not request.client or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(403, "Test reports are available only on localhost")
    return {"protocol_version": 1, "measurement": "capture-to-render-ack roundtrip; not photon-to-display",
            "target": {"capture_fps": 15, "processed_fps": 10, "roundtrip_p95_ms": 1000}, **hub.state()}


def local_request(request):
    if not request.client or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(403, "Local evaluation only")
    origin = request.headers.get("origin")
    if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise HTTPException(403, "Cross-site requests are not allowed")


@router.post("/cases")
async def save_case(request: Request):
    local_request(request)
    message = await request.json()
    if not isinstance(message, dict):
        raise HTTPException(400, "Invalid request")
    if not hub.evidence.frames:
        raise HTTPException(409, "No frame is available to save")
    latest = hub.evidence.frames[-1]["frame"]
    message = {"session_id": latest.session_id, "revision": latest.revision, "frame_id": latest.frame_id, **message}
    try:
        return await hub.save_case(message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/evidence-frame")
def evidence_frame(request: Request):
    local_request(request)
    if not hub.evidence.frames:
        raise HTTPException(409, "No frame is available")
    entry = hub.evidence.frames[-1]
    return Response(entry["frame"].jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/annotations")
def annotations(request: Request):
    local_request(request)
    path = MODEL_DIR.parent / "obstacle_dataset/review.html"
    if not path.is_file():
        raise HTTPException(404, "Annotation page has not been generated")
    return Response(path.read_text(), media_type="text/html", headers={"Cache-Control": "no-store"})


async def receive_packet(socket):
    text = await socket.receive_text()
    if len(text) > MAX_MESSAGE:
        raise ValueError("Message is too large")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Message must be an object")
    return value


async def run_socket(receiver, outbox, socket):
    rx = asyncio.create_task(receiver())
    tx = asyncio.create_task(outbox.pump(socket))
    try:
        done, _ = await asyncio.wait((rx, tx), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
        pass
    finally:
        rx.cancel()
        tx.cancel()
        await asyncio.gather(rx, tx, return_exceptions=True)


@router.websocket("/voice")
async def voice_socket(socket: WebSocket):
    token = read_config().get("token", "")
    supplied = socket.headers.get("authorization", "")
    if not token or not secrets.compare_digest(supplied, "Bearer " + token):
        await socket.close(code=1008)
        return
    if hub.voice.phone is not None:
        await socket.close(code=1013, reason="one voice receiver only")
        return
    await socket.accept()
    if hub.voice.phone is not None:
        await socket.close(code=1013)
        return
    outbox = hub.voice.phone = VoiceOutbox(hub.clock)
    outbox.put({"type": "voice_state", "output": hub.voice.output})
    hub.publish_state()

    async def receiver():
        while True:
            packet = await receive_packet(socket)
            if packet.get("type") == "voice_ack":
                try:
                    hub.voice.acknowledge(packet)
                except ValueError:
                    continue
                hub.publish_state()
            elif packet.get("type") == "voice_capability":
                value = packet.get("capability")
                if value not in ("foreground_only", "active_speech_session"):
                    raise ValueError("Unknown capability")
                hub.voice.phone_capability = value
                hub.publish_state()
            elif packet.get("type") != "voice_ping":
                raise ValueError("Unknown voice command")

    try:
        await run_socket(receiver, outbox, socket)
    except (ValueError, json.JSONDecodeError):
        await socket.close(code=1008)
    finally:
        if hub.voice.phone is outbox:
            hub.voice.phone = None
            hub.voice.phone_capability = "foreground_only"
            hub.publish_state()


@router.websocket("/source")
async def source_socket(socket: WebSocket):
    token = read_config().get("token", "")
    supplied = socket.headers.get("authorization", "")
    if not token or not secrets.compare_digest(supplied, "Bearer " + token):
        await socket.close(code=1008)
        return
    if hub.connection == "connected":
        await socket.close(code=1013, reason="one source only")
        return
    await socket.accept()
    try:
        hello = await asyncio.wait_for(receive_packet(socket), 3)
        if hello.get("type") != "hello" or hello.get("source") not in ("screen_video_test", "diagnostic_video"):
            await socket.close(code=1008, reason="invalid hello")
            return
    except (ValueError, WebSocketDisconnect, asyncio.TimeoutError):
        await socket.close(code=1008)
        return
    # Re-check after awaiting hello: two simultaneous handshakes cannot replace a source.
    if hub.connection == "connected":
        await socket.close(code=1013, reason="one source only")
        return
    session_id = hub.begin(hello["source"], socket)
    outbox = hub.source_out
    intentional = False

    async def receiver():
        nonlocal intentional
        while hub.session_id == session_id and hub.connection == "connected":
            try:
                packet = await receive_packet(socket)
                if packet.get("session_id") != session_id:
                    raise ValueError("The video session changed. Reconnect and try again.")
                kind = packet.get("type")
                if kind == "frame":
                    frame = parse_frame(packet, session_id, hub.clock())
                    hub.accept_frame(frame)
                    outbox.put({"type": "accepted", "session_id": session_id, "frame_id": frame.frame_id})
                elif kind == "heartbeat":
                    hub.last_heartbeat = hub.clock()
                elif kind in ("paused", "resumed"):
                    hub.invalidate("Broadcast paused." if kind == "paused" else "Broadcast resumed. Start analysis again.")
                    hub.capture = "paused" if kind == "paused" else "waiting"
                    hub.publish_state()
                elif kind == "ended":
                    intentional = True
                    break
                elif kind == "latency":
                    elapsed = packet.get("roundtrip_ms")
                    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or not 0 <= elapsed < 120000:
                        raise ValueError("Invalid latency record")
                    if any(fid == packet.get("frame_id") for fid, _ in hub.published):
                        hub.latencies.append(round(elapsed, 2))
                else:
                    raise ValueError("Unknown message type")
            except (ValueError, KeyError) as exc:
                outbox.put({"type": "error", "message": str(exc)[:200]})

    try:
        await run_socket(receiver, outbox, socket)
    finally:
        hub.end(session_id, intentional)
        try:
            await socket.close(code=1000)
        except RuntimeError:
            pass


@router.websocket("/viewer")
async def viewer_socket(socket: WebSocket):
    origin = urlparse(socket.headers.get("origin", ""))
    if (not socket.client or socket.client.host not in ("127.0.0.1", "::1") or
            origin.hostname not in ("127.0.0.1", "localhost", "::1") or origin.scheme not in ("http", "https")):
        await socket.close(code=1008)
        return
    if hub.viewer_out is not None:
        await socket.close(code=1013, reason="one viewer only")
        return
    await socket.accept()
    # accept() yields; re-check ownership before claiming the sole viewer slot.
    if hub.viewer_out is not None:
        await socket.close(code=1013)
        return
    outbox = hub.viewer_out = Outbox()
    if hub.connection == "connected" and hub.capture == "receiving":
        hub.message = "Video connected. Confirm the video area, then start analysis."
    hub.publish_state()

    async def receiver():
        while True:
            try:
                packet = await receive_packet(socket)
                if packet.get("type") == "configure":
                    hub.configure(packet)
                elif packet.get("type") == "switch_model":
                    await hub.switch_model(packet.get("profile"))
                elif packet.get("type") == "corridor":
                    if packet.get("session_id") != hub.session_id or packet.get("revision") != hub.revision:
                        raise ValueError("The video context changed. Confirm the corridor again.")
                    points = validate_corridor(packet.get("points"))
                    enabled = hub.analysis_enabled
                    hub.invalidate("Image corridor changed; waiting for new observations")
                    hub.corridor = points
                    hub.analysis_enabled = enabled
                    hub.publish_state()
                elif packet.get("type") == "voice_output":
                    hub.voice.select(packet.get("output"))
                    hub.publish_state()
                elif packet.get("type") == "voice_test":
                    if hub.voice.output == "off":
                        raise ValueError("Enable voice before testing")
                    event = {"id": uuid.uuid4().hex, "direction": "ahead", "priority": "test", "ttl_ms": 1500}
                    hub.voice.publish(event)
                    if hub.voice.output in ("mac", "both"):
                        outbox.put({"type": "voice_event", "event": event})
                elif packet.get("type") == "risk_command":
                    result = await hub.handle_command(packet)
                    outbox.put({"type": "command_reply", "command": packet.get("command"), "speech": result.get("speech")})
                elif packet.get("type") == "display_ack":
                    if (packet.get("session_id") == hub.session_id and hub.source_out and
                            (packet.get("frame_id"), packet.get("revision")) in hub.published and
                            packet.get("revision") == hub.revision):
                        hub.source_out.put({"type": "display_ack", "session_id": hub.session_id,
                                            "frame_id": packet["frame_id"]})
                        hub.evidence.acknowledge(hub.session_id, packet["revision"], packet["frame_id"])
                elif packet.get("type") == "save_case":
                    async def save(message):
                        try:
                            result = await hub.save_case(message)
                            outbox.put({"type": "case_saved", **result})
                        except (ValueError, OSError, RuntimeError) as exc:
                            outbox.put({"type": "error", "message": str(exc)[:200]})
                    task = asyncio.create_task(save(packet))
                    hub.case_tasks.add(task)
                    task.add_done_callback(hub.case_tasks.discard)
                else:
                    raise ValueError("Unknown monitor command")
            except ValueError as exc:
                outbox.put({"type": "error", "message": str(exc)[:200]})

    try:
        await run_socket(receiver, outbox, socket)
    finally:
        if hub.viewer_out is outbox:
            hub.viewer_out = None
            if not hub.mobile_guidance:
                hub.invalidate("Monitor disconnected. Start analysis again after reconnecting.")


# Also usable without importing the optional cloud/offline integrations.
app = FastAPI(title="SkyCompanion live screen test")
app.include_router(router)
from .tts import router as tts_router
app.include_router(tts_router)
app.add_event_handler("startup", hub.start)
app.add_event_handler("shutdown", hub.stop)
