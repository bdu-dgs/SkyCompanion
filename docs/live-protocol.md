# SkyCompanion live screen test protocol (v1)

This test uses iPhone 15 Plus / iOS 18, ReplayKit, one source, one browser viewer,
and local YOLO11n CPU inference. No cloud inference, audio, or drone connection.

## Connection and configuration

- Development config: `.skycompanion-live/config.json` and `ios/Shared/LocalCaptureConfig.json`
  contain identical `{ "server_url": "http://<Mac>.local:8000", "token": "..." }`.
  Both files are generated and ignored by Git. The iOS file is a resource in both targets.
- `GET /api/live/health`: public readiness (no token or image), returns `model`,
  `configured`, and `protocol_version: 1`.
- `WS /api/live/source`: `Authorization: Bearer <token>`; first send
  `{type:"hello", source:"screen_video_test", device:"iPhone"}`. Diagnostic clients
  must use `source:"diagnostic_video"`. Server replies `{type:"session", session_id}`.
- `WS /api/live/viewer`: development browser only; validated localhost Origin,
  proxied by Vite from `/api`. No token is exposed to the browser. Only one viewer.
- A new source connection gets a new session and resets analysis and crop.

## Source -> server

- `frame`: `{type, session_id, frame_id, captured_ms, width, height, orientation,
  image_b64}`. `captured_ms` is phone monotonic time in milliseconds; orientation
  is the original ReplayKit orientation integer, image pixels already upright.
  JPEG longest side <= 960, quality 0.65, target 15 FPS. Fixed capture time slots
  skip missed frames instead of catching up. Actual FPS depends on screen updates,
  encoding, network and inference. Frame IDs increase.
- `heartbeat`: `{type, session_id}` once per second, independent of new frames.
- `paused` / `resumed` / `ended`: `{type, session_id}`.
- `latency`: `{type, session_id, frame_id, roundtrip_ms}` after a display receipt;
  measured on the phone's monotonic clock. This includes the return receipt trip.
- Server replies `accepted` with session/frame IDs when a frame is admitted.
  Source keeps at most one unacknowledged frame plus one latest pending frame.
- Server sends `display_ack` with session/frame IDs back to the source after the
  viewer has decoded and drawn the corresponding image. Source keeps a bounded
  map of capture times; it never subtracts clocks from different devices.

## Viewer -> server

- `configure`: `{type, session_id, roi:[x,y,w,h] | null, analysis_enabled:boolean}`.
  ROI uses upright full-frame normalized coordinates, top-left origin. A change
  increments revision and invalidates in-flight results. Selecting a new crop
  uses raw full-frame preview with analysis paused. Start analysis separately.
- `display_ack`: `{type, session_id, frame_id, revision}` after decode + draw.

## Server -> viewer

- `state`: `{type, session_id, revision, connection, capture, source,
  analysis_enabled, roi, roi_version, dimensions, model, metrics, message}`.
  connection: `waiting|connected|disconnected|ended`;
  capture: `waiting|receiving|no_frames|paused|ended`;
  model: `{state:"loading|ready|error", name:"yolo11n", device:"cpu", error:null|string}`;
  dimensions: `[width,height] | null`.
  metrics: `received_fps`, `processed_fps`, `dropped_frames`, `queue_ms`,
  `inference_ms`, `roundtrip_p50_ms`, `roundtrip_p95_ms`, `received_frames`,
  `processed_frames` (numeric or null).
- `frame`: `{type, session_id, revision, roi_version, frame_id, captured_ms,
  width, height, image_b64, analysis_status, boxes, queue_ms, inference_ms}`.
  Image is the full frame for preview, the crop for analyzed frames. Boxes are
  `{class_id,label,confidence,x,y,w,h}` normalized to THIS message's image.
  analysis_status: `unanalysed|ok|empty|error`. Empty means model success with
  no detections, never a safety claim. One packet binds image and boxes.
- `error`: `{type, message}` for invalid commands (no secrets).

## Freshness and resources

One pending frame per worker/subscriber; replace older pending frames. Inference
runs outside the async network loop. Session/revision changes discard old results.
No frame for 2 s: invalidate display boxes and show no_frames. No heartbeat for 3 s:
disconnect source, clear pending work, pause analysis. Rotation or dimension changes
reset crop and pause analysis. Paused/resumed also require manual re-arming.
Static or identical images alone are NOT proof of a network failure.
Stop and reconnection never replay queued frames. Browser also clears overlays
when its own connection closes or state becomes stale/paused/ended.
