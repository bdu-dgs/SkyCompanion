"""Behavior tests with controlled detector doubles, not a real YOLO benchmark."""
from __future__ import annotations

import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import live


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Detector:
    def __init__(self, boxes=None, error=None, block_first=False):
        self.boxes = boxes if boxes is not None else []
        self.error = error
        self.block_first = block_first
        self.started = threading.Event()
        self.release = threading.Event()
        self.images = []

    def load(self):
        pass

    def predict(self, image):
        self.images.append(image.copy())
        self.started.set()
        if self.block_first and len(self.images) == 1:
            if not self.release.wait(2):
                raise TimeoutError("Test did not release detector")
        if self.error:
            raise self.error
        return self.boxes


def frame_message(session="session", frame_id=1, width=100, height=80, orientation=1):
    image = Image.new("RGB", (width, height), color=(50, 100, 150))
    encoded = io.BytesIO()
    image.save(encoded, format="JPEG")
    return {
        "type": "frame", "session_id": session, "frame_id": frame_id,
        "captured_ms": 1000.0 + frame_id * 200, "width": width, "height": height,
        "orientation": orientation, "image_b64": base64.b64encode(encoded.getvalue()).decode(),
    }


async def eventually(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(.001)
    await asyncio.wait_for(wait(), 2)


class RecordingOutbox(live.Outbox):
    def __init__(self):
        super().__init__()
        self.packets = []

    def put(self, packet):
        self.packets.append(packet)
        super().put(packet)

    @property
    def frames(self):
        return [packet for packet in self.packets if packet["type"] == "frame"]


class Socket:
    """In-memory WebSocket boundary, exercising the real route state machine."""
    def __init__(self):
        self.headers = {"authorization": "Bearer test-token"}
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.closed = []

    def feed(self, packet):
        self.incoming.put_nowait(json.dumps(packet))

    async def accept(self):
        pass

    async def receive_text(self):
        return await self.incoming.get()

    async def send_json(self, packet):
        await self.outgoing.put(packet)

    async def close(self, code=1000, reason=None):
        self.closed.append((code, reason))


class ImageBoundaryTests(unittest.TestCase):
    def test_roi_rejects_invalid_values(self):
        invalid = [
            [], [0, 0, 1], (0, 0, 1, 1), "full", [True, 0, 1, 1],
            [0, float("nan"), 1, 1], [0, 0, float("inf"), 1],
            [-.01, 0, .5, .5], [0, 0, .01, .5], [.9, 0, .2, 1],
        ]
        for roi in invalid:
            with self.subTest(roi=roi), self.assertRaises(ValueError):
                live.normalize_roi(roi)
        self.assertIsNone(live.normalize_roi(None))
        self.assertEqual(live.normalize_roi([0, 0, 1, 1]), [0., 0., 1., 1.])

    def test_crop_preserves_exact_pixel_region(self):
        image = np.arange(10 * 20 * 3, dtype=np.uint16).reshape((10, 20, 3))
        crop = live.crop_image(image, [.1, .2, .4, .5])
        np.testing.assert_array_equal(crop, image[2:7, 2:10])
        self.assertEqual(crop.shape, (5, 8, 3))
        crop[:] = 0
        self.assertTrue(image[2:7, 2:10].any(), "Crop must not alias the source image")

    def test_valid_jpeg_roundtrips_and_dimension_mismatch_fails(self):
        message = frame_message()
        frame = live.parse_frame(message, "session", 20.0)
        self.assertEqual((frame.width, frame.height, frame.received_at), (100, 80, 20.0))
        self.assertEqual(cv2.imdecode(np.frombuffer(frame.jpeg, np.uint8), 1).shape, (80, 100, 3))
        with self.assertRaises(ValueError):
            live.parse_frame({**message, "width": 99}, "session", 20.0)

    def test_malformed_wrong_format_and_oversized_images_are_rejected(self):
        png = io.BytesIO()
        Image.new("RGB", (100, 80)).save(png, format="PNG")
        invalid = [
            "", "%%%not-base64%%%", base64.b64encode(b"not an image").decode(),
            base64.b64encode(png.getvalue()).decode(),
            "A" * (live.MAX_JPEG * 4 // 3 + 5),
            base64.b64encode(b"x" * (live.MAX_JPEG + 1)).decode(),
        ]
        for encoded in invalid:
            with self.subTest(length=len(encoded)), self.assertRaises(ValueError):
                live.parse_frame({**frame_message(), "image_b64": encoded}, "session", 0.)

    def test_frame_metadata_rejects_wrong_types_and_nonfinite_numbers(self):
        for key, value in [
            ("frame_id", True), ("frame_id", -1), ("captured_ms", float("inf")),
            ("captured_ms", -1), ("width", 961), ("height", False),
            ("orientation", 9), ("session_id", "old-session"),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                live.parse_frame({**frame_message(), key: value}, "session", 0.)


class LiveBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = Clock()
        self.detector = Detector()
        self.hub = live.LiveHub(self.detector, self.clock)
        self.outbox = RecordingOutbox()
        self.hub.viewer_out = self.outbox
        await self.hub.load_model()
        self.session = self.hub.begin("screen_video_test")

    async def asyncTearDown(self):
        self.detector.release.set()
        await self.hub.stop()

    def accept(self, frame_id, **kwargs):
        frame = live.parse_frame(frame_message(self.session, frame_id, **kwargs), self.session, self.clock())
        self.hub.accept_frame(frame)
        return frame

    def configure(self, enabled=True, roi=None):
        self.hub.configure({"session_id": self.session, "analysis_enabled": enabled, "roi": roi})

    def start_worker(self):
        self.hub.tasks.append(asyncio.create_task(self.hub.worker()))

    def enable(self, roi=None):
        self.accept(0)
        self.configure(roi=roi)

    async def test_frame_ids_must_increase_even_when_content_is_unchanged(self):
        self.accept(5)
        for stale in (5, 4):
            with self.subTest(stale=stale), self.assertRaises(ValueError):
                self.accept(stale)
        self.clock.advance(.2)
        newest = self.accept(6)
        self.assertIs(self.hub.pending, newest)
        self.assertEqual(self.hub.received_frames, 2)
        self.assertEqual(self.hub.last_frame, self.clock())
        self.assertEqual(self.hub.capture, "receiving")

    async def test_pending_slot_keeps_only_latest_frame(self):
        self.accept(1)
        self.accept(2)
        newest = self.accept(3)
        self.assertIs(self.hub.pending, newest)
        self.assertEqual(self.hub.dropped_frames, 2)
        self.assertEqual(self.hub.received_frames, 3)

    async def test_heartbeat_without_frames_is_distinct_from_disconnection(self):
        socket = object()
        self.hub.source_socket = socket
        self.enable()
        self.clock.advance(live.FRAME_TIMEOUT + .1)
        self.hub.last_heartbeat = self.clock()
        self.assertIsNone(self.hub.check_freshness())
        self.assertEqual(self.hub.connection, "connected")
        self.assertEqual(self.hub.capture, "no_frames")
        self.assertFalse(self.hub.analysis_enabled)
        self.clock.advance(live.HEARTBEAT_TIMEOUT + .1)
        self.assertIs(self.hub.check_freshness(), socket)
        self.assertEqual(self.hub.connection, "disconnected")

    async def test_analysis_cannot_start_on_stale_picture_or_unready_model(self):
        self.accept(1)
        self.clock.advance(live.FRAME_TIMEOUT)
        with self.assertRaises(ValueError):
            self.configure()
        self.accept(2)
        self.hub.model["state"] = "loading"
        with self.assertRaises(ValueError):
            self.configure()

    async def test_configure_and_rotation_revoke_old_frames_and_crop(self):
        self.enable([.1, .2, .5, .5])
        revision = self.hub.revision
        self.accept(1)
        self.configure(False, [.1, .2, .5, .5])
        self.assertGreater(self.hub.revision, revision)
        self.assertIsNone(self.hub.pending)
        self.assertFalse(self.hub.analysis_enabled)
        self.configure(True, [.1, .2, .5, .5])
        revision, roi_version = self.hub.revision, self.hub.roi_version
        self.accept(2, width=80, height=100, orientation=6)
        self.assertGreater(self.hub.revision, revision)
        self.assertGreater(self.hub.roi_version, roi_version)
        self.assertIsNone(self.hub.roi)
        self.assertFalse(self.hub.analysis_enabled)
        self.assertEqual(self.hub.dimensions, [80, 100])
        self.assertEqual(self.hub.pending.revision, self.hub.revision)

    async def test_crop_sent_to_detector_matches_result_picture_dimensions_and_boxes(self):
        boxes = [{"class_id": 2, "label": "car", "confidence": .9, "x": .25, "y": .25, "w": .5, "h": .5}]
        self.detector.boxes = boxes
        self.enable([.1, .25, .5, .5])
        self.start_worker()
        self.accept(1)
        await eventually(lambda: bool(self.outbox.frames))
        packet = self.outbox.frames[-1]
        self.assertEqual(self.detector.images[0].shape, (40, 50, 3))
        self.assertEqual((packet["width"], packet["height"]), (50, 40))
        displayed = cv2.imdecode(np.frombuffer(base64.b64decode(packet["image_b64"]), np.uint8), 1)
        self.assertEqual(displayed.shape, (40, 50, 3))
        self.assertEqual([{k: v for k, v in b.items() if k != "attention"} for b in packet["boxes"]], boxes)
        self.assertEqual(packet["boxes"][0]["attention"]["basis"], "image_geometry_not_metric_distance")
        self.assertEqual(packet["analysis_status"], "ok")
        self.assertEqual(packet["frame_id"], 1)

    async def test_busy_detector_processes_current_frame_then_latest_pending_only(self):
        self.detector.block_first = True
        self.enable()
        dropped_before = self.hub.dropped_frames
        self.start_worker()
        self.accept(1)
        await eventually(self.detector.started.is_set)
        self.accept(2)
        self.accept(3)
        self.detector.release.set()
        await eventually(lambda: len(self.outbox.frames) == 2)
        self.assertEqual([packet["frame_id"] for packet in self.outbox.frames], [1, 3])
        self.assertEqual(len(self.detector.images), 2)
        self.assertEqual(self.hub.dropped_frames - dropped_before, 1)

    async def test_pause_discards_inflight_result(self):
        self.detector.block_first = True
        self.enable()
        self.start_worker()
        self.accept(1)
        await eventually(self.detector.started.is_set)
        self.configure(False)
        dropped_before = self.hub.dropped_frames
        self.detector.release.set()
        await eventually(lambda: self.hub.dropped_frames > dropped_before)
        self.assertEqual(self.outbox.frames, [])
        self.assertEqual(list(self.hub.published), [])
        self.assertEqual(self.hub.processed_frames, 0)

    async def test_result_that_exceeds_frame_timeout_is_not_published(self):
        self.detector.block_first = True
        self.enable()
        self.start_worker()
        self.accept(1)
        await eventually(self.detector.started.is_set)
        dropped_before = self.hub.dropped_frames
        self.clock.advance(live.FRAME_TIMEOUT + .01)
        self.detector.release.set()
        await eventually(lambda: self.hub.dropped_frames > dropped_before)
        self.assertEqual(self.outbox.frames, [])

    async def test_empty_detections_are_successful_analysis(self):
        self.enable()
        self.start_worker()
        self.accept(1)
        await eventually(lambda: bool(self.outbox.frames))
        packet = self.outbox.frames[-1]
        self.assertEqual(packet["analysis_status"], "empty")
        self.assertEqual(packet["boxes"], [])
        self.assertEqual(self.hub.model["state"], "ready")
        self.assertTrue(self.hub.analysis_enabled)

    async def test_detector_exception_reports_error_not_empty_detection(self):
        self.detector.error = RuntimeError("controlled inference failure")
        self.enable()
        self.start_worker()
        self.accept(1)
        await eventually(lambda: bool(self.outbox.frames))
        self.assertEqual(self.outbox.frames[-1]["analysis_status"], "error")
        self.assertEqual(self.hub.model["state"], "error")
        self.assertIn("controlled inference failure", self.hub.model["error"])
        self.assertFalse(self.hub.analysis_enabled)

    async def test_reconnect_blocks_old_session_frames_controls_and_teardown(self):
        old_session = self.session
        old_frame = live.parse_frame(frame_message(old_session, 1), old_session, self.clock())
        self.hub.end(old_session)
        self.session = self.hub.begin("screen_video_test")
        self.assertNotEqual(self.session, old_session)
        with self.assertRaises(ValueError):
            self.hub.accept_frame(old_frame)
        with self.assertRaises(ValueError):
            self.hub.configure({"session_id": old_session, "analysis_enabled": False})
        self.hub.end(old_session, intentional=True)
        self.assertEqual(self.hub.connection, "connected")
        self.accept(0)
        self.assertEqual(self.hub.last_frame_id, 0)

    async def test_broadcast_pause_resume_requires_explicit_restart_via_actual_route(self):
        self.hub.end(self.session)
        socket = Socket()
        socket.feed({"type": "hello", "source": "screen_video_test"})
        with patch.object(live, "hub", self.hub), patch.object(live, "read_config", return_value={"token": "test-token"}):
            task = asyncio.create_task(live.source_socket(socket))
            try:
                hello = await asyncio.wait_for(socket.outgoing.get(), 1)
                self.session = hello["session_id"]
                socket.feed(frame_message(self.session, 1))
                await eventually(lambda: self.hub.capture == "receiving")
                self.configure()
                revision = self.hub.revision
                socket.feed({"type": "paused", "session_id": self.session})
                await eventually(lambda: self.hub.capture == "paused")
                self.assertGreater(self.hub.revision, revision)
                self.assertFalse(self.hub.analysis_enabled)
                received_before = self.hub.received_frames
                socket.feed(frame_message(self.session, 2))
                await eventually(lambda: self.hub.last_frame_id == 2)
                self.assertEqual(self.hub.received_frames, received_before)
                revision = self.hub.revision
                socket.feed({"type": "resumed", "session_id": self.session})
                await eventually(lambda: self.hub.capture == "waiting")
                self.assertGreater(self.hub.revision, revision)
                socket.feed(frame_message(self.session, 3))
                await eventually(lambda: self.hub.capture == "receiving")
                self.assertFalse(self.hub.analysis_enabled)
                self.configure()
                self.assertTrue(self.hub.analysis_enabled)
                socket.feed({"type": "ended", "session_id": self.session})
                await asyncio.wait_for(task, 1)
                self.assertEqual(self.hub.connection, "ended")
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


class OutboxTests(unittest.TestCase):
    def test_new_revision_evicts_queued_frame_but_keeps_reliable_control(self):
        outbox = live.Outbox()
        outbox.put({"type": "session", "session_id": "s"})
        outbox.put({"type": "frame", "session_id": "s", "revision": 1, "frame_id": 4})
        outbox.put({"type": "state", "session_id": "s", "revision": 2})
        self.assertIsNone(outbox.frame)
        self.assertEqual(outbox.controls[0]["type"], "session")

    def test_frame_slot_is_replaceable_and_control_queue_is_bounded(self):
        outbox = live.Outbox()
        outbox.put({"type": "frame", "session_id": "s", "revision": 1, "frame_id": 1})
        outbox.put({"type": "frame", "session_id": "s", "revision": 1, "frame_id": 2})
        self.assertEqual(outbox.frame["frame_id"], 2)
        for _ in range(32):
            outbox.put({"type": "accepted"})
        with self.assertRaises(RuntimeError):
            outbox.put({"type": "accepted"})


if __name__ == "__main__":
    unittest.main()
