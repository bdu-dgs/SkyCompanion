# SkyCompanion Assistant: Photon integration

2026-09-26. Default agent name **SkyCompanion Assistant**, configurable server-side via `SKY_AGENT_NAME`. This controls app/reply naming; Photon/Apple still control the iMessage sender number/contact name.

The assistant UI, new replies, trip summaries, correction acknowledgements and local summaries use English. The current mobile app accepts English voice commands. Original user feedback/evidence and previously sent messages/inbox history are preserved rather than translated. The service's earlier non-English input compatibility does not change the app's English interface.

## Five implemented behaviors

1. **Call the agent from the app:** Assistant and trip history supports questions, history, explanations and summaries. Voice commands include SkyCompanion trip summary and SkyCompanion ask assistant why. Requests enter Photon asynchronously; replies arrive in the app inbox and configured private iMessage conversation.
2. **Accessible message speech:** Text, fields and buttons expose VoiceOver content. New replies can use system TTS; each history entry provides Read message aloud.
3. **Obstacle priority:** Agent speech priority -1 is below every obstacle. It waits during active obstacles, speech or commands; a new obstacle can cancel it immediately. Agent replies do not use protected-command status. Queue limit eight, automatic expiry 60 seconds, full inbox text retained; mute suppresses autoplay.
4. **End-of-trip summary:** Ending assistance, replacing a trip or natural completion of an ordinary test video creates a local summary even offline. With Photon enabled, ordered upload creates one server summary/outbox job; retransmissions do not double-count. An unfinished stored trip at startup is marked interrupted and potentially incomplete.
5. **Correction feedback:** The app records the latest obstacle utterance that actually reached its speech-start callback. User corrections bind trip/event/frame/original wording and preserve same-frame evidence locally. In iMessage, use `wrong latest: it was a shadow`, replacing latest with an event ID when appropriate.

Counts are speech-start callbacks, not all boxes or proof the user heard them. Ordinary and rear-following obstacle prompts count; pure boundary/tracking/health/command messages do not. Unverified categories use obstacle. Zero reminders does not mean zero obstacles.

## VoiceOver and audio boundaries

A third-party service cannot enable system VoiceOver or control Apple Messages announcement priority. SkyCompanion uses its own cancellable AVSpeechSynthesizer queue alongside accessible controls, not an uncontrollable system announcement queue. Apple Messages follows the user's own VoiceOver/notification settings. Obstacle priority applies to app-managed audio, not every other app. References: [VoiceOver state](https://developer.apple.com/documentation/uikit/uiaccessibility/isvoiceoverrunning), [immediate speech cancellation](https://developer.apple.com/documentation/avfaudio/avspeechsynthesizer/stopspeaking(at:)).

## Configuration and operation

Server: `/Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/skycompanion`; see its README for full contracts. In addition to existing Photon settings:

```dotenv
SKY_INGEST_TOKEN=<random-upload-token-at-least-24-characters>
SKY_REPORT_TO_PHONE=<authorized-recipient-in-international-format>
SKY_AGENT_NAME=SkyCompanion Assistant
```

Keep `PROJECT_ID` and `PROJECT_SECRET` server-side; never put them on the phone. This single-user prototype accepts only the configured sender's private conversation and binds persistent history to that recipient. Starting the service may send queued messages; never test with someone else's number.

1. With dependencies installed, `npm run start` listens at 127.0.0.1:8787.
2. Provide an HTTPS origin reachable by the phone; localhost on iPhone is not the computer. Physical-device testing previously used an explicitly authorized temporary Cloudflare tunnel.
3. Rebuild the app. In Assistant and trip history → Photon connection, save HTTPS origin and upload token, enable Sync trips with Photon, then start a new trip. The token is kept in Keychain.
4. Ask/correct on the messages page. Read new assistant replies aloud remains subordinate to mute/obstacle priority.
5. Before changing service/account, end the trip, drain pending data, disable sync and save new settings. Deleting local Photon data removes pending records and the phone token, not server history.

Only structured reminder records and user feedback upload through this channel, not images, video or microphone audio. A bounded persistent phone queue retries with stable IDs/backoff. Running while DJI Fly is foreground remains subject to iOS lifecycle constraints.

## Using feedback for model improvement

`SkyCompanionDiagnostics/case-…-feedback.json` links same-prefix evidence. If Include image in reports is enabled and the matching frame exists, a still is saved. Structured-only feedback remains valid feedback but is not a complete training sample.

Bearer-authenticated `GET /v1/feedback` returns unreviewed corrections, original alerts and trip source. Review image/video → confirm true classes/boxes/masks → add reviewed examples → train offline → fixed-test regression → validate before updating the phone model. This integration did not change weights or measure accuracy gains.

## Code map

| Layer | File | Responsibility |
|---|---|---|
| Phone UI | `ios/OnDevice/CompanionScreen.swift` | Configuration, messages, questions, corrections, accessibility |
| Client | `ios/OnDevice/PhotonCompanion.swift` | Keychain, HTTPS, bounded persistence, retry, inbox |
| Session | `ios/OnDevice/LocalSessionModel.swift` | Trips, speech-start events, summaries, same-frame feedback |
| Audio | `ios/OnDevice/LocalVoiceController.swift` | Utterance-bound start callback; cancellation cannot falsely count playback |
| Pure logic | `ios/CaptureCore/Sources/CaptureCore/CompanionSpeech.swift` | Priority, expiry, summary counts |
| Protocol | `ios/CaptureCore/Sources/CaptureCore/PhotonProtocol.swift` | Encoding, acknowledgements and freshness |
| Service | `skycompanion/src/index.ts`, `store.ts`, `http.ts`, `agent.ts` | Message ingestion, atomic history, Q&A/feedback, summary outbox |

## Recorded validation and remaining work

- Initial integration: 105 Swift tests, including priority, expiry, summary idempotence, recorded sources, rear-following classification and protocol.
- Service English update: 16 tests and TypeScript check passed, covering non-English input/old trips with English replies, raw-feedback preservation, authentication, atomic batches, retries/restarts, isolation, outbox failure and bounds. Six related Swift assistant tests and an English device build passed.
- Swift → TypeScript → Swift contract passed. Rerun:

  ```sh
  python3 scripts/test_photon_contract.py --photon-dir /Users/stanley/Documents/ChatGPT/Hackathon/SkyCompanion/skycompanion
  ```

- Debug simulator build passed after an initial exit 74 from restricted Xcode cache/simulator-service access. Existing Vision/path SDK deprecation warnings remain.
- An isolated iPhone 18 Pro / iOS 27 simulator installed/opened the Assistant screen; text/control rendering was inspected and the temporary device subsequently removed. [Screenshot](validation/photon-2026-09-26/assistant.png), [hashes/record](validation/photon-2026-09-26/validation.json). Screenshots are not VoiceOver/acoustic acceptance.
- Physical Debug signing/install/launch passed on iPhone 15 Plus. Existing `.env` was neither read nor modified by the integration workflow; Node loaded existing credentials, with added configuration in a separate private file. Debug launch provisioning wrote the phone upload token to Keychain, not the app bundle.
- The authorized live service/tunnel returned 401 without a token and 200 with one. Device log: `Photon device sync OK: pending=0, inbox=2, cursor=2`.
- A clearly marked synthetic-obstacle integration summary was sent. The user confirmed the first summary and replied asking why; one inbound message led to an explanation accepted by the SDK. Both outbound attempts succeeded first try, pending=0/failed=0. The second explanation's receipt/read was not separately confirmed.
- After the English service update, a new `Integration test: simulated obstacle` summary was sent; device inbox=3/cursor=3/pending=0, all three outbox entries accepted on first attempts. [Live record](validation/photon-2026-09-26/live-validation.json).
- Pending: real-trip upload, VoiceOver, audible replies/obstacle interruption, DJI background coexistence and offline recovery. Network/inbox synchronization was real; obstacles were synthetic. SDK sent is not read, and a crash after transport acceptance can still duplicate an external message.

## Local service restart reference

Run in the Photon server directory. Private gitignored `data/local-runtime/config.json` is mode 600; runtime directory mode 700. It holds upload token, authorized number and HTTPS origin; do not share/commit it. Live history `data/live-agent-state.json` is separate from temporary test stores.

Check whether service/tunnel are already running before restarting. Mac sleep, process exit and network loss interrupt temporary hosting; Cloudflare temporary origins generally change after restart. Use separate terminals:

```sh
npm run start:local
python3 scripts/start-tunnel.py
```

The tunnel helper saves the new origin without printing the token. When the phone has no pending uploads, connect it and provision the installed Debug build:

```sh
python3 scripts/provision-device.py 00008120-001A10D002E2201E
```

This restarts the app, securely passes configuration and displays sync logs; it does not send a synthetic test. Release has no environment-provisioning hook. Pending data tied to the old service prevents switching; restore/drain that service instead of deleting unsent records. Long-term deployment requires a stable HTTPS origin.

Field sequence: enable sync/start test trip → produce alert → ask why → introduce obstacle during reply → end/check one summary → correct a specific alert → end another trip offline → reconnect/check counts. Recorded-video tests must retain their recorded-demo label.
