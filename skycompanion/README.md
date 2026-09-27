# SkyCompanion Assistant — Photon agent

This service replaces the echo loop with a callable, deterministic trip assistant. The iOS app uploads only reminders whose speech actually started, ends each trip, polls the assistant inbox, asks questions, and reports corrections. Photon sends concise trip summaries and replies to one configured user's iMessage. It does not run the vision model or perform online training.

## Setup

Keep the existing `PROJECT_ID` and `PROJECT_SECRET` in your private `.env`. Also configure:

```dotenv
SKY_INGEST_TOKEN=<at least 24 random characters, same token as iOS>
SKY_REPORT_TO_PHONE=<the consenting user's E.164 number, such as +15551234567>
SKY_AGENT_NAME=SkyCompanion Assistant
SKY_PORT=8787
SKY_STATE_PATH=data/agent-state.json
```

Only that phone number can query the history via a direct iMessage conversation. Group conversations, missing sender identity, other senders, and outbound echoes are ignored. The persistent state binds to this recipient: use a new state path for a different account. Register the recipient in the Photon project's user allowlist when using a shared line. The visible sender number/profile remains controlled by Photon/Apple; `SKY_AGENT_NAME` names the assistant in the app and help responses.

Run `npm run start` after configuring. `start`/`dev` explicitly load `.env`. Missing settings fail with variable names, never secret values. The API binds **127.0.0.1:8787**. For a real phone, expose it through an authenticated HTTPS reverse proxy/tunnel on the development Mac or deploy behind HTTPS; use that HTTPS base URL in the app. Do not use `localhost` on a physical phone to refer to your Mac, and do not put the token in URLs. This is a single-user, single-process prototype, not a multi-tenant server.

Photon connection failure leaves local trip storage and inbox available. Cloud startup reconnects at most five times; fix connectivity/configuration and restart afterwards. `npm run start` connects to Photon and may send queued messages; tests do neither.

## App API

Every endpoint requires `Authorization: Bearer <SKY_INGEST_TOKEN>`. JSON responses use `Cache-Control: no-store`.

- `POST /v1/sync` with `Content-Type: application/json`, `{ "records": [...] }`: 1–50 records, at most 256 KB. Returns `{ "accepted": 3, "duplicates": 0 }`. A batch commits entirely or is rejected entirely. The sum always equals its record count on success. Preserve start → alerts → end order in the offline queue. Retrying identical record IDs is safe; changed content under the same ID is a conflict.
- `GET /v1/messages?after=0`: `{ "messages": [{ "id": "...", "sequence": 1, "session_id": "...", "kind": "summary", "text": "...", "created_at_ms": 1790424000000 }], "cursor": 1, "agent_name": "SkyCompanion Assistant" }`. At most 100 messages per page. Advance cursor only after handling the page, and continue polling independently of uploads. `kind` is `summary`, `answer`, or `feedback`.
- `GET /v1/feedback`: `{ "feedback": [...] }` with the correction, `status: "unreviewed"`, original alert including evidence/frame ID, and trip source. This is the review/training export; no images or labels are invented.
- `GET /v1/preferences`: returns the saved preference document below, including the last phone acknowledgement.
- `POST /v1/preferences/applied` with `Content-Type: application/json`, `{ "revision": 1 }`: the phone confirms that it has persisted and applied a revision. Returns the preference document. Invalid revisions return 400; revisions newer than the saved preferences return 409. Old or duplicate acknowledgements cannot roll back the last applied revision.
- `GET /v1/delivery`: counts of `pending`, `sent`, and `failed` iMessage outbox entries. `sent` means the provider send completed, not that the person read it. The sync acknowledgement and app inbox never claim iMessage delivery.

Every record has `{id, kind, session_id, at_ms}`. IDs are 1–160 characters in `[A-Za-z0-9_.:-]`. UTC timestamps are integer milliseconds since epoch, from year 2000 through 5 minutes ahead of server time. Extra fields by kind:

| kind | Required fields |
| --- | --- |
| start | `source: "drone" \| "video"`, `locale: "en" \| "zh"` |
| alert | `frame_id` nonnegative safe integer, `event_id`, `category` (100 chars), `direction: "left" \| "center" \| "right" \| "unknown"`, `text` (1,000 chars), `evidence` (up to 16 strings of 300 chars), `observed_at_ms`, `speech_status: "started"` |
| end | `reason` (500 chars) |
| feedback | `event_id` in the same trip, `note` (1,000 chars) |
| query | `question` (1,000 chars) |

Direction describes the image frame. Historical answers include their UTC observation time and explicitly cannot guide present movement. Recorded-video trips are labeled as recorded demos. Summary counts represent recorded reminders, not distinct real objects. Zero reminders never imply the route was safe. A session produces only one logical automatic end summary, including across retransmission or restart; corrections after a summary are separately acknowledged. An explicit summary query can intentionally repeat a summary.

## Questions and corrections

All generated assistant replies, summaries and correction confirmations use English, including trips previously marked `zh`. Commands use English aliases. Original evidence and correction notes remain unchanged in storage; CJK excerpts in English replies are replaced with an explicit notice that the original is retained, not an invented translation. Previously sent messages remain historical records.

Ask `summary`, `recent`, `why`, or `help`. Send `wrong latest: it was a tree, not a pole`; replace `latest` with the exact event ID to disambiguate. The reply identifies which recorded alert is being corrected. Unknown or other-trip event IDs are rejected. Use the app's correction control for a selected event. Each query/reply/correction is also persisted in the app inbox for speech.

For this Mac's configured live setup, run `npm run start:local` to use the private `data/local-runtime/config.json` without editing `.env`. Run `python3 scripts/start-tunnel.py` in a second terminal to create the explicitly authorized temporary Cloudflare HTTPS tunnel and save its new origin. Then run `python3 scripts/provision-device.py <device-UDID>` to provision the installed Debug iPhone app. A renewed HTTPS tunnel can reconnect with the exact same saved token while preserving pending records and the inbox cursor; changing accounts still requires an empty queue. The upload token is passed privately and stored in Keychain; it is never bundled into the app. Do not start duplicate servers or tunnels. Keep the Mac awake and both processes running during the demo.

Feedback remains **unreviewed**. Export it, verify the original frame/video against the report, create reviewed labels, retrain offline, and evaluate against a held-out set before replacing a model. Saving feedback alone does not improve measured model performance. An event/frame reference without retained source footage is not sufficient training data.

## Personalized alerts through iMessage

The assistant accepts bounded natural-language English preference commands, even before the first trip. This is a deterministic parser, not an open-ended LLM. Examples:

- `Please say less, mute trees and poles, alert interval 30 seconds`
- `I want fewer warnings`, `be more detailed`, `Don't mention trees`, `stop mentioning trees`, `say more`, `normal detail`, `enable trees`, `my preferences`, `reset preferences`
- `Say less, mute trees and poles, alert interval 30 seconds`
- `Enable trees, say more`, `my preferences`, `reset preferences`

Supported ordinary categories are `tree`, `pole`, `person`, `vehicle`, `bicycle`, `stairs`, `curb`, and `obstacle`. Preferences select minimal/standard/detailed speech, ordinary category filtering, and a minimum interval of 8–120 seconds between ordinary new alerts. Unchanged obstacles are not periodically repeated. **Immediate-action and urgent collision alerts remain enabled** regardless of ordinary filters or this interval. Unsupported categories or conditions, conflicting commands, and incomplete combinations produce a clarification without applying any part of the request. Alert corrections still use the separate `wrong latest: ...` format.

Preferences are saved atomically with the reply and inbound deduplication ID. Every effective change increments `revision`; resets create a new revision. Old state files receive defaults. Generated confirmations remain English and explicitly say whether a revision is waiting for the phone or was confirmed applied. Acknowledgement is a last-known status, not proof that a phone is currently online; querying settings includes the confirmation time.

`GET /v1/preferences` returns this document (example after a preference change, before application):

```json
{
  "schema_version": 1,
  "revision": 1,
  "verbosity": "minimal",
  "muted_categories": ["pole", "tree"],
  "repeat_interval_seconds": 30,
  "urgent_alerts_enabled": true,
  "updated_at_ms": 1790500800000,
  "applied_revision": null,
  "applied_at_ms": null
}
```

Defaults are revision 0, standard detail, no muted categories, 8 seconds, and `updated_at_ms: 0`. The iOS app fetches preferences with the same bearer token, validates schema 1, persists them locally, applies them without blocking obstacle processing, and then acknowledges the applied revision. Offline operation retains the last locally saved settings. The service never claims a saved revision is active until the phone acknowledges it. The API field `repeat_interval_seconds` retains its protocol name, but means a minimum interval between ordinary new alerts; it does not schedule recurring speech. The command `repeat every 30 seconds` is retained as an alias with that meaning explicitly explained in the reply. No model retraining is involved.

## Speech and priority

The service sends text and a matching app inbox entry. A remote iMessage service cannot force Apple's system VoiceOver to speak or control its priority. The iOS app owns accessible presentation and its speech queue: assistant messages wait behind obstacle alerts, and obstacle alerts may interrupt them. When the app is backgrounded or stopped, speech follows iOS notification/VoiceOver settings; immediate automatic speech is not guaranteed. Immediate obstacle processing never waits for this API or Photon.

## Persistence and delivery limits

`data/agent-state.json` stores records, deduplication IDs, inbox, and outbox in one atomic rename, with private file permissions. Keep a secure backup, do not commit it, and run one service process per state file. Storage caps at 100,000 records/inbound IDs and then rejects new work; archive the full state while stopped and configure a new path before resuming with new trip IDs. This demo uses synchronous JSON writes and is suitable for one demo user; production needs a database and retention policy.

The outbox sends serially and retries failures at most five times with exponential backoff. Logical summary/inbox creation is idempotent. **Exactly-once external iMessage delivery is not guaranteed**: a process crash or transport timeout after Apple accepts a send but before local acknowledgement can cause a repeated message. Failed entries remain stored for inspection; they are not automatically requeued indefinitely.

## Validation

```sh
npm run typecheck
npm test
```

Tests use temporary state, a loopback HTTP server, and a simulated transport; they never load `.env`, connect to Photon, or send real messages. Real-account delivery and iOS VoiceOver/audio behavior require a device integration test.
