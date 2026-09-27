# Phone Controls and Remote Inference Paths

Updated: 2026-09-26. The current device software includes phone controls and a user-initiated voice session. Cloud deployment and Core ML export/phone performance verification have not yet been completed.

## Computer Operations That Can Currently Be Removed

SkyCompanionCapture can select audio output, play a voice test, start/pause the landscape video experiment, and issue STT commands. Background inference and risk tracking no longer depend on the Mac webpage remaining connected. The Mac receiver service still needs to run as the development compute host.

The two recommended eventual configurations:

| Mode | Phone | Inference location | Verification required |
| --- | --- | --- | --- |
| Phone + cloud | ReplayKit upload, phone controls, offline STT/TTS, freshness gating | Nearby regional GPU receiver service | Cellular internet while directly connected to the drone, P95 latency, invalidation notices on disconnection, cost, and data retention |
| On-device phone | Camera/local video, Core ML inference, risk processing, and voice | Main phone app | Same-frame model export regression, temperature, memory, and battery life; separately test cross-app broadcast extension resource limits |

The main phone app's foreground camera path is better suited to offline inference. When DJI Fly is in the foreground, do not assume the SkyCompanion main app receives continuous visual-compute permission. Verify the recording extension's runtime/resource boundaries and the actual voice session separately; a background audio declaration is not a complete on-device solution.

Core ML is a feasible export direction: [official Ultralytics export documentation](https://docs.ultralytics.com/integrations/coreml/). Background audio recording started in advance requires an explicit user action and the `audio` mode: [Apple record documentation](https://developer.apple.com/documentation/avfaudio/avaudiosession/category-swift.struct/record). These platform capabilities do not replace SkyCompanion device acceptance testing.

## Prepared Cloud Receiver Code

`deploy/Dockerfile.live` starts only `app.live`, avoiding the original offline Google Cloud video-job dependencies. Use one worker: sessions, frame queues, and risk state currently live in process memory, so requests cannot be randomly distributed across multiple workers. CUDA/MPS/CPU selection is automatic. CPU performance without a GPU must not inherit the Mac MPS results.

The container needs read-only mounts for `backend/data/models` and private pairing configuration `/run/secrets/skycompanion-config.json`, plus a writable evidence directory. Do not bake local pairing configuration into the image. The container recipe has not been build-verified; no paid resources or public endpoints have been created.

Before remote deployment, the following are still required:

- HTTPS/WSS, separate time-limited authorization for each device, and revocation; the existing static single-user development token is for local verification only.
- Frame/command rate limits and latest-frame-only retention; the phone discards alerts older than 1.5 seconds using original capture uptime.
- Explicit cloud image upload and retention options; disable the evidence buffer when appropriate, without default long-term retention.
- A verified server-address and pairing flow configurable on the phone, without asking users to edit compiled source files.
- Monitoring for network loss, model failure, and audio interruption; empty detections never mean a path is safe.
- Continuous measurements of capture-to-speech latency, failure rate, traffic, battery use, and temperature on the target network before deciding frame rate and compression.

The Mac webpage is an optional diagnostic tool. Product controls for start, stop, pairing, mode selection, and recovery ultimately belong on the phone, with acceptance testing using VoiceOver and actual users.
