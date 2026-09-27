"""Fixed-audio interface checks; no speaker, cloud service, or httpx required."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import tts


def test_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22050)
        audio.writeframes(b"\x80\x00" * 2205)
    return buffer.getvalue()


async def request(app: FastAPI, path: str, method: str = "GET") -> tuple[int, dict, bytes]:
    events = []

    async def send(event):
        events.append(event)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    await app({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "", "headers": [],
        "server": ("test", 80), "client": ("127.0.0.1", 1234),
    }, receive, send)
    start = next(event for event in events if event["type"] == "http.response.start")
    body = b"".join(event.get("body", b"") for event in events if event["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body


class TTSInterfaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.asset_dir = Path(self.temp.name)
        self.audio = test_wav()
        digest = hashlib.sha256(self.audio).hexdigest()
        clips = {direction: {**spec, "sha256": digest} for direction, spec in tts.CLIPS.items()}
        for spec in clips.values():
            (self.asset_dir / f"{spec['id']}.wav").write_bytes(self.audio)
        self.addCleanup(patch.stopall)
        patch.object(tts, "ASSET_DIR", self.asset_dir).start()
        patch.object(tts, "CLIPS", clips).start()
        self.app = FastAPI()
        self.app.include_router(tts.router)

    async def test_manifest_and_exact_audio_response(self):
        status, _, body = await request(self.app, "/api/tts/manifest")
        self.assertEqual(status, 200)
        manifest = json.loads(body)
        self.assertTrue(manifest["ready"])
        self.assertEqual(set(manifest["clips"]), {"ahead", "left", "right"})
        self.assertNotIn(str(self.asset_dir), body.decode())
        for item in manifest["clips"].values():
            self.assertEqual(item["duration_ms"], 100)
            status, headers, data = await request(self.app, item["url"])
            self.assertEqual(status, 200)
            self.assertEqual(headers[b"content-type"], b"audio/wav")
            self.assertEqual(data, self.audio)

    async def test_missing_clip_reports_not_ready_and_returns_503(self):
        (self.asset_dir / "en-obstacle-left.wav").unlink()
        manifest = tts.get_tts_manifest()
        self.assertFalse(manifest["ready"])
        self.assertEqual(manifest["clips"]["left"]["error"], "clip_not_installed")
        self.assertTrue(manifest["clips"]["right"]["ready"])
        status, _, _ = await request(self.app, "/api/tts/clips/en-obstacle-left.wav")
        self.assertEqual(status, 503)

    async def test_modified_audio_is_not_served(self):
        (self.asset_dir / "en-obstacle-ahead.wav").write_bytes(b"bad or changed media")
        self.assertEqual(tts.get_tts_manifest()["clips"]["ahead"]["error"], "clip_checksum_mismatch")
        status, _, _ = await request(self.app, "/api/tts/clips/en-obstacle-ahead.wav")
        self.assertEqual(status, 503)

    async def test_unknown_names_and_paths_cannot_be_served(self):
        for path in (
            "/api/tts/clips/en-pedestrian-ahead.wav",
            "/api/tts/clips/../../../.env.wav",
            "/api/tts/clips/stop_obstacle_ahead.wav",
        ):
            status, _, _ = await request(self.app, path)
            self.assertEqual(status, 404)
        status, _, _ = await request(self.app, "/api/tts/manifest", "POST")
        self.assertEqual(status, 405)

    async def test_symlink_does_not_bypass_fixed_asset_storage(self):
        target = self.asset_dir / "en-obstacle-right.wav"
        target.unlink()
        target.symlink_to(self.asset_dir / "en-obstacle-ahead.wav")
        status, _, _ = await request(self.app, "/api/tts/clips/en-obstacle-right.wav")
        self.assertEqual(status, 503)

    def test_validation_rejects_truncated_or_wrong_format_pcm(self):
        for data in (self.audio[:-2], b"not wav"):
            digest = hashlib.sha256(data).hexdigest()
            with self.assertRaises(ValueError):
                tts.validate_clip(data, digest)


if __name__ == "__main__":
    unittest.main()
