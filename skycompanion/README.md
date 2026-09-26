# SkyCompanion phone event agent

The iPhone app is responsible for video capture, on-device detection, rules, and immediate English speech. This PC process receives spoken warning events through its phone API, keeps a local event log, answers iMessage questions through Photon, and can optionally send a short iMessage report for a fresh event. The PC and phone need Internet access, but do not need the same Wi-Fi network. This repository does not yet contain an iPhone app.

## Start

Install dependencies with `npm install` in this directory. Configure `PROJECT_ID` and `PROJECT_SECRET` for Photon as before. Also set a long random `SKY_INGEST_TOKEN` in the PC process environment and the phone app's secure storage. Never place Photon credentials in the phone app. Run `npm run start`.

The API listens on `127.0.0.1:8787` by default. Set `SKY_API_PORT` if needed. For an outdoor phone, put an HTTPS reverse proxy or private tunnel in front of this localhost API; configure the phone with that HTTPS URL. Do not expose the plain HTTP port publicly. `GET /health` returns only `{ "ok": true }`.

Optionally set `SKY_REPORT_TO_PHONE` to an authorized Photon iMessage recipient (E.164 phone number). A newly accepted event is sent as an iMessage only when its phone observation time is within 10 seconds before, or 5 seconds after, PC receipt. Old offline uploads remain queryable but never trigger a "live" iMessage. Leave this unset if only Q&A is desired. Photon outbound delivery depends on its service and recipient permissions.

## Phone contract

`POST /v1/events` with `Authorization: Bearer <SKY_INGEST_TOKEN>` and JSON:

```json
{
  "schema_version": "1.0",
  "events": [{
    "event_id": "51a61f71-7fbf-4ba4-91b0-a40ace75613c",
    "session_id": "walk-2026-09-26-01",
    "observed_at_ms": 1790450000000,
    "processed_at_ms": 1790450000090,
    "video_timestamp_ms": null,
    "frame_id": 125,
    "type": "person",
    "direction": "center",
    "warning_text": "Stop. Pedestrian ahead.",
    "target_id": 7,
    "avoid_direction": "unknown",
    "approaching": "unknown",
    "evidence": ["bbox_footpoint_in_configured_corridor", "consecutive_track_frames_2"]
  }]
}
```

The phone creates a stable `event_id` per spoken warning and a new `session_id` per walk. It queues failed uploads locally and retries the *same* IDs. The response contains `accepted`, `duplicates`, and PC `received_at_ms`; a duplicate is already stored and needs no retry. Maximum 50 events and 256 KB per request. `observed_at_ms` is the phone wall-clock UTC Unix milliseconds when the relevant frame entered the app, `processed_at_ms` is when the warning was decided, and `received_at_ms` is assigned by the PC. `video_timestamp_ms` is optional source-media time, not a wall clock. Clock skew can affect freshness classification, so sync the phone and PC clocks. Upload only selected warning events, never full video or per-frame detections.

`POST /v1/query` with the same bearer token and `{ "question": "Trip summary?" }` returns `{ "answer": "..." }`. Photon inbound iMessages use the same event log and answer logic. The latest walk is selected by phone observation time, not upload order. Questions such as `What happened?`, `Why did you warn me?`, and `Trip summary?` use fixed templates and recorded evidence. If the latest event is older than 15 seconds, answers are explicitly labeled as synchronized history, not live status. No open-ended RAG or phone client is implemented yet.

Stored events default to `data/events.jsonl` (gitignored); override with `SKY_EVENTS_PATH`. The old desktop `run/frames.jsonl` parser remains for standalone tests and demos, but the running Photon agent now reads phone-uploaded events.

Run `npm test` and `npm run typecheck` for offline validation. These checks do not send an iMessage or prove the outdoor phone path or message delivery latency.
