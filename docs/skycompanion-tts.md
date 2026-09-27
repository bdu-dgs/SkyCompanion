# SkyCompanion warning audio in SkyCompanion

Verified locally on 2026-09-25. Source checkout: `references/SkyCompanion`, commit
`e8c763f7de8f8b46ee749e3f66a704edbb141187`.

## What the reference actually implements

[SkyCompanion README at the inspected revision](https://github.com/bdu-dgs/SkyCompanion/blob/e8c763f7de8f8b46ee749e3f66a704edbb141187/README.md)
describes a Windows walking-video prototype using YOLO11n, tracking, a projected
walking corridor, and prerecorded English warning WAVs. Its `WarningSink` interface
separates visual decisions from speech delivery.

The [LocalSpeechSink implementation](https://github.com/bdu-dgs/SkyCompanion/blob/e8c763f7de8f8b46ee749e3f66a704edbb141187/sky_companion.py#L178)
requires Windows and uses `winsound.PlaySound`. The
[voice-cache script](https://github.com/bdu-dgs/SkyCompanion/blob/e8c763f7de8f8b46ee749e3f66a704edbb141187/make_voice_cache.ps1)
uses Windows `System.Speech.Synthesis.SpeechSynthesizer`, the installed
`Microsoft Zira Desktop` voice, and rate 5. It precomputes 15 short phrases from
five nouns and three directions. This path needs no paid service or API key.
Its Windows SAPI/WASAPI dependencies are not a Mac implementation.

Useful design ideas are: one latest pending warning, priority selection, dropping
unstarted warnings older than 900 ms, and separating playback API events from
observed audio output. Its separate `soundcard` WASAPI loopback monitor measures
output onset; SkyCompanion's HTTP response or browser `play()` completion does not provide
that measurement. The source is a prototype, not evidence that its corridor
heuristic establishes a safe walking path.

No project-level LICENSE or other permission grant was found in the inspected
checkout. The user's explicit instruction authorizes the current local evaluation
with these three assets. It does not establish a redistribution or commercial
license. No MIT/Apache license is attributed to this repository. Obtain permission
or replace the assets with independently generated, appropriately licensed speech
before distributing them. SkyCompanion's new file-serving code is independently written;
Windows playback code, installation scripts, bundled dependencies, and OpenMP
workarounds are not executed or imported.

## Implemented backend boundary

`backend/app/tts.py` serves three fixed English clips:

| Direction | ID | Exact spoken phrase | PCM duration |
| --- | --- | --- | --- |
| Ahead | `en-obstacle-ahead` | Stop. Obstacle ahead. | 1473.33 ms |
| Left | `en-obstacle-left` | Stop. Obstacle left. | 1467.71 ms |
| Right | `en-obstacle-right` | Stop. Obstacle right. | 1473.33 ms |

All are 22050 Hz, mono, 16-bit PCM. Category naming remains unapproved by the
visual evaluation; these clips deliberately use the generic noun `obstacle`.
The English-only implementation matches this iteration's English interface.

Install from the already cloned, exact source revision:

```sh
cd /Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion
backend/.venv/bin/python scripts/setup_tts_assets.py
```

The setup script verifies the checkout revision, the three SHA-256 digests, and
WAV metadata before copying any file. It writes the fixed clips and provenance
to `backend/data/tts/`, which is local generated data. It does not download or
execute the reference project's scripts. `provenance.json` records source paths,
commit, digests, PCM metadata, and the unresolved license status.

Mount the exported router in the application's integration layer:

```python
from .tts import router as tts_router
app.include_router(tts_router)
```

No startup hook, package installation, microphone permission, cloud credentials,
or native audio device is needed to serve the files.

### HTTP contract

`GET /api/tts/manifest` returns HTTP 200 with:

```json
{
  "schema_version": 1,
  "engine": "skycompanion-cached-wav",
  "ready": true,
  "languages": ["en"],
  "clips": {
    "ahead": {
      "id": "en-obstacle-ahead",
      "text": "Stop. Obstacle ahead.",
      "locale": "en-US",
      "url": "/api/tts/clips/en-obstacle-ahead.wav",
      "sha256": "c1f14bed369aaeb010498a005faf8df2767c6efe13018e27baf454510ca6d92a",
      "ready": true,
      "duration_ms": 1473.33
    }
  }
}
```

The actual response also contains `left`, `right`, PCM metadata, source revision,
and a measurement limitation. Readiness verifies file integrity and decodability,
not an active output device or audible playback. Missing or changed clips set
`ready: false` and provide a stable per-clip error code, without disclosing local
paths.

`GET /api/tts/clips/{clip_id}.wav` accepts only the three IDs above. It returns
`audio/wav`, a SHA-based ETag, and `nosniff`. Unknown IDs and traversal paths return
404; known but missing, changed, or symlinked assets return 503. There is no
arbitrary-text synthesis, command execution, user-supplied path, or image upload
endpoint. `get_tts_manifest()` also exposes the same readiness to the integration
code without an HTTP round trip.

## Playback integration responsibilities

The following responsibilities belong to the selected Mac browser or iPhone
player; the file server does not implement a speech scheduler:

1. Require the user to enable the chosen output device, preload the three clips,
   and play a test phrase. Use exactly one output destination per active session
   unless the user explicitly selects both. Cached audio avoids per-warning cloud
   or synthesis latency.
2. Preserve event ID, source session, ROI/configuration revision, frame ID,
   direction, priority, and remaining TTL when delivering a warning. Deduplicate
   event IDs and keep a bounded latest pending event; do not accumulate a spoken
   backlog. Detector result age counts against the TTL. Different devices must
   not compare unrelated monotonic clocks.
3. Recheck context and TTL immediately before starting audio, including after
   asset loading or a browser user-gesture wait. Clear queued events and stop
   active audio when analysis pauses, input disconnects, the output changes, or
   the source/ROI changes. A new higher-priority risk may interrupt ordinary
   conversational speech; ordinary speech must not interrupt a current risk.
4. Report `received`, `expired`, `cancelled`, `playback_requested`, and playback
   errors separately. API success is not verified physical sound. Actual acoustic
   onset and headphone output require a device-level test.

These are short prerecorded TTS outputs, not a general conversation or STT
implementation. Browser fallback may use `speechSynthesis` if explicitly selected;
it must share the same single queue and cancellation policy, and must not double
play alongside the fixed clips. Phone background playback, microphone/STT,
cross-app lifecycle, and the Neo 2 network path remain distinct native integration
and field-test concerns; see `mobile-voice-architecture.md`.

## Verification completed for this module

```sh
backend/.venv/bin/python scripts/setup_tts_assets.py
backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_tts*.py' -v
```

The setup completed with three installed clips. Full PCM payloads were read and
shown to contain nonzero samples; source hashes match the installed bytes. Six
ASGI behavior tests pass: exact manifest/audio responses, missing-file readiness
and 503, modified audio refusal, unknown ID/path traversal/unsupported method,
symlink refusal, and truncated/invalid WAV refusal. Tests use a small generated
PCM fixture and the real FastAPI router, without requiring `httpx`.

This module verification does not demonstrate audible speaker/headphone output,
warning accuracy, end-to-end expiry enforcement in a client, or successful iPhone
background playback. Those are verified by the integration owners separately.
