# SkyCompanion iMessage agent

Spectrum receives iMessage questions. The agent reads SkyCompanion's current JSONL file and answers from recorded spoken warnings. Detection and immediate speech remain in the Python program.

## Environment

Before running, open `.env` and fill in the values:

From your project Settings on the [Photon dashboard](https://app.photon.codes):

- `PROJECT_ID`
- `PROJECT_SECRET`

## Run

```sh
npm install
npm run start
```

Run `python sky_companion.py` in the parent directory to produce `run/frames.jsonl`, then keep this agent running with `npm run start`. The agent rereads the file for each question, so new warning events become queryable without restarting it. `SKYCOMPANION_FRAMES_PATH` can point to another JSONL file for a recorded demo (for example `run/final/frames.jsonl`). The path must be readable from this process.

Try `What happened?`, `Why did you warn me?`, `Trip summary?`, or `刚才发生了什么？`, `为什么提醒？`, `本次汇报？`. Only frames with `warning.speak=true` become events. The report counts spoken warnings, not distinct objects. Answers cite video time and frame ID and preserve unknown judgments.

Run `npm test` and `npm run typecheck` to check the event rules locally, without sending iMessages. This is event retrieval with fixed response templates; open-ended RAG and an on-device language model have not yet been implemented.
