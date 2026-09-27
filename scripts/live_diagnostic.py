#!/usr/bin/env python3
"""A clearly labeled VIDEO diagnostic source, never a substitute for iPhone QA."""
import argparse
import asyncio
import base64
import json
import time
from pathlib import Path

import cv2
import websockets

ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    config = json.loads((ROOT / ".skycompanion-live/config.json").read_text())
    url = args.server.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise SystemExit("Cannot open the test video")
    video_fps = max(1., capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if frame_count < 1:
        raise SystemExit("The test video has no readable frames")
    times = {}
    accepted = asyncio.Event()
    accepted.set()
    try:
        async with websockets.connect(url + "/api/live/source", additional_headers={
                "Authorization": "Bearer " + config["token"]}, max_size=1100000) as socket:
            await socket.send(json.dumps({"type": "hello", "source": "diagnostic_video", "device": "Mac diagnostic"}))
            response = json.loads(await socket.recv())
            session = response["session_id"]
            print(f"Diagnostic video input connected (not phone capture): {session}", flush=True)

            async def send(packet):
                await socket.send(json.dumps({"session_id": session, **packet}))

            async def receive():
                async for raw in socket:
                    message = json.loads(raw)
                    if message["type"] == "accepted":
                        accepted.set()
                    elif message["type"] == "display_ack":
                        stamp = times.get(message["frame_id"])
                        if stamp is not None:
                            await send({"type": "latency", "frame_id": message["frame_id"],
                                        "roundtrip_ms": (time.monotonic() - stamp) * 1000})
                    elif message["type"] == "error":
                        print("Receiver error: ", message["message"], flush=True)
                        accepted.set()

            async def heartbeat():
                while True:
                    await send({"type": "heartbeat"})
                    await asyncio.sleep(1)

            receiver = asyncio.create_task(receive())
            heartbeat_task = asyncio.create_task(heartbeat())
            started = time.monotonic()
            frame_id = 0
            try:
                while args.seconds <= 0 or time.monotonic() - started < args.seconds:
                    await asyncio.wait_for(accepted.wait(), 3)
                    accepted.clear()
                    # Follow wall time instead of decoding old frames after a stall.
                    elapsed = time.monotonic() - started
                    # Millisecond seeking can round the final fractional frame to
                    # EOF. Integer frame positions stay inside the valid loop.
                    position = int(elapsed * video_fps) % frame_count
                    capture.set(cv2.CAP_PROP_POS_FRAMES, position)
                    success, image = capture.read()
                    if not success:
                        raise RuntimeError("Failed to decode the test video")
                    h, w = image.shape[:2]
                    scale = min(1, 960 / max(h, w))
                    image = cv2.resize(image, (round(w * scale), round(h * scale)))
                    success, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    if not success:
                        raise RuntimeError("Failed to encode the test frame")
                    times[frame_id] = time.monotonic()
                    for old in list(times):
                        if old < frame_id - 128:
                            del times[old]
                    await send({"type": "frame", "frame_id": frame_id,
                                "captured_ms": times[frame_id] * 1000, "width": image.shape[1],
                                "height": image.shape[0], "orientation": 1,
                                "image_b64": base64.b64encode(jpeg).decode()})
                    frame_id += 1
                    # Encoding/seeking time is part of the frame interval.
                    next_slot = int((time.monotonic() - started) * args.fps) + 1
                    deadline = started + next_slot / args.fps
                    await asyncio.sleep(max(0, deadline - time.monotonic()))
                await send({"type": "ended"})
            finally:
                receiver.cancel()
                heartbeat_task.cancel()
                await asyncio.gather(receiver, heartbeat_task, return_exceptions=True)
    finally:
        capture.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=ROOT / "samples/local/skycompanion-pov-3874684-1080p30-timecode.mp4")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--fps", type=float, default=15)
    parser.add_argument("--seconds", type=float, default=60)
    args = parser.parse_args()
    if not 0 < args.fps <= 30:
        parser.error("fps must be > 0 and <= 30")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
