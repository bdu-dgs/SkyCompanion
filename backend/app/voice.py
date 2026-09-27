"""Bounded, expiring notification delivery; speech is played by the receiver."""
import asyncio
from collections import deque
import time
import math

OUTPUTS = frozenset(("off", "mac", "phone", "both"))
STAGES = frozenset(("received", "started", "completed", "expired", "interrupted", "failed"))
PRIORITY = {"test": 0, "query": 1, "health": 2, "obstacle": 2, "urgent": 3}
CAMERA_SPEECH = {"camera_obstacle": "obstacle", "camera_surface": "ground change",
                 "camera_overhead": "overhead obstruction", "camera_vehicle": "vehicle conflict"}
HEALTH_SPEECH = {
    "perception_unavailable": "Visual guidance is unavailable. Check your surroundings.",
    "perception_restored": "Live observations have resumed. Your direction and distance remain unverified.",
    "direction_unverified": "Your direction is unverified. Locations refer to the camera view.",
}


def safe_event(event):
    """Build speech from a bounded protocol, never labels or arbitrary server text."""
    if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not 0 < len(event["id"]) <= 128:
        return None
    ttl = event.get("ttl_ms")
    if type(ttl) not in (int, float) or not math.isfinite(ttl) or not 0 < ttl <= 1500:
        return None
    direction = event.get("direction", "ahead")
    if direction not in ("ahead", "left", "right"):
        return None
    priority, code = event.get("priority"), event.get("speech_code")
    base = {**event, "category_naming_enabled": False}
    if priority == "test":
        return {**base, "text": f"Stop. Obstacle {direction}.", "asset": f"stop_obstacle_{direction}",
                "clip_id": f"en-obstacle-{direction}"}
    if event.get("schema_version") != 2:
        return None
    if priority == "health" and code in HEALTH_SPEECH and event.get("direction_frame") == "unavailable":
        return {**base, "risk_level": None, "direction": "ahead", "text": HEALTH_SPEECH[code], "asset": "health_"+code}
    if (priority not in ("obstacle", "urgent") or code not in CAMERA_SPEECH
            or event.get("direction_frame") != "camera_image" or event.get("risk_level") not in ("R1", "R2", "R3")
            or (priority == "urgent") != (event.get("risk_level") == "R3")):
        return None
    where = "ahead" if direction == "ahead" else "on the " + direction
    return {**base, "asset": f"risk_{code}_{direction}",
            "text": f"Caution. Possible {CAMERA_SPEECH[code]} {where} in the camera view. Your direction is unverified."}


class VoiceOutbox:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.state = None
        self.pending = None
        self.stop_message = None
        self.ready = asyncio.Event()

    def put(self, message):
        if message["type"] == "voice_state":
            self.state = message
        elif message["type"] == "voice_stop":
            self.pending = None
            self.stop_message = message
        elif message["type"] == "voice_event":
            # One replaceable event, never an unbounded speech backlog.
            if (self.pending and self.pending[1] > self.clock()
                    and (PRIORITY.get(self.pending[0]["event"].get("priority"), -1)
                         > PRIORITY.get(message["event"].get("priority"), -1)
                         or (self.pending[0]["event"].get("priority") == "obstacle"
                             and message["event"].get("priority") == "health"))):
                return
            self.pending = (message, self.clock() + message["event"]["ttl_ms"] / 1000)
        self.ready.set()

    async def pump(self, socket):
        while True:
            await self.ready.wait()
            message = None
            if self.stop_message:
                message, self.stop_message = self.stop_message, None
            elif self.state:
                message, self.state = self.state, None
            elif self.pending:
                message, deadline = self.pending
                self.pending = None
                remaining = int((deadline - self.clock()) * 1000)
                if remaining <= 0:
                    continue
                message = {**message, "event": {**message["event"], "ttl_ms": remaining}}
            else:
                self.ready.clear()
                continue
            await asyncio.wait_for(socket.send_json(message), timeout=1)


class VoiceChannel:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.output = "off"
        self.phone = None
        self.sent = deque(maxlen=64)
        self.last_ack = None
        self.phone_capability = "foreground_only"

    def state(self):
        return {"output": self.output, "phone_connected": self.phone is not None,
                "phone_capability": self.phone_capability, "last_phone_ack": self.last_ack}

    def select(self, output):
        if not isinstance(output, str) or output not in OUTPUTS:
            raise ValueError("Unknown voice output")
        if self.output != output:
            self.stop("output_changed")
        self.output = output
        if self.phone:
            self.phone.put({"type": "voice_state", "output": output})

    def stop(self, reason="stopped"):
        if self.phone:
            self.phone.put({"type": "voice_stop", "reason": reason})

    def publish(self, event, frame_age_ms=0, captured_uptime_ms=None):
        if not event or self.output not in ("phone", "both") or not self.phone:
            return
        event = safe_event(event)
        if event is None or not math.isfinite(frame_age_ms):
            return
        remaining = int(event["ttl_ms"] - max(0, frame_age_ms))
        if remaining <= 0:
            return
        visual = event.get("priority") in ("obstacle", "urgent")
        if visual and (type(captured_uptime_ms) not in (float, int) or not math.isfinite(captured_uptime_ms) or captured_uptime_ms < 0):
            return
        message = {**event, "ttl_ms": min(1500, remaining)}
        if visual:
            message["captured_uptime_ms"] = captured_uptime_ms
            message["max_observation_age_ms"] = 1500
        self.sent.append(event["id"])
        self.phone.put({"type": "voice_event", "event": message})

    def acknowledge(self, message):
        event_id, stage = message.get("event_id"), message.get("stage")
        if event_id not in self.sent or stage not in STAGES:
            raise ValueError("Unknown voice acknowledgement")
        self.last_ack = {"event_id": event_id, "stage": stage,
                         "measurement": "receiver_API_callback_not_acoustic_onset"}
