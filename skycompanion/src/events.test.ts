import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { EventStore, parseBatch } from "./events.ts";
import { createPhoneApi } from "./http_api.ts";

const now = Date.now();
const event = (id: string, observed = now, session = "walk-1") => ({
  event_id: id, session_id: session, observed_at_ms: observed,
  processed_at_ms: observed + 50, video_timestamp_ms: 1234, frame_id: 12,
  type: "person", direction: "center", warning_text: "Stop. Pedestrian ahead.",
  target_id: 7, avoid_direction: "unknown", approaching: "unknown", evidence: ["corridor"],
});

test("phone event API deduplicates replay, preserves both clocks, and excludes stale pushes", async () => {
  const dir = await mkdtemp(join(tmpdir(), "sky-phone-"));
  const path = join(dir, "events.jsonl");
  const store = new EventStore(path);
  const pushed: string[] = [];
  const server = createPhoneApi(store, "test-only-token", e => pushed.push(e.event_id));
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  const base = `http://127.0.0.1:${address.port}`;
  const post = (url: string, body: unknown, auth = true) => fetch(base + url, {
    method: "POST", headers: { "content-type": "application/json",
      ...(auth ? { authorization: "Bearer test-only-token" } : {}) }, body: JSON.stringify(body),
  });
  try {
    assert.equal((await post("/v1/events", { schema_version: "1.0", events: [event("a")] }, false)).status, 401);
    const batch = { schema_version: "1.0", events: [event("a"), event("old", now - 60_000)] };
    const first = await (await post("/v1/events", batch)).json() as { accepted: number; duplicates: number };
    assert.equal(first.accepted, 2);
    assert.equal(first.duplicates, 0);
    assert.deepEqual(pushed, ["a"]);
    const replay = await (await post("/v1/events", batch)).json() as { accepted: number; duplicates: number };
    assert.equal(replay.accepted, 0);
    assert.equal(replay.duplicates, 2);
    assert.deepEqual(pushed, ["a"]);
    const answer = await (await post("/v1/query", { question: "What happened?" })).json() as { answer: string };
    assert.match(answer.answer, /Pedestrian ahead/);
    const stored = store.latestSessionEvents();
    assert.equal(stored.length, 2);
    assert.equal(stored.at(-1)?.observedAtMs, now);
    assert.ok((stored.at(-1)?.receivedAtMs ?? 0) >= now);
    const reloaded = new EventStore(path);
    await reloaded.load();
    assert.equal(reloaded.latestSessionEvents().length, 2);
    await reloaded.add(parseBatch({ schema_version: "1.0", events: [event("later-walk", now + 1000, "walk-2")] }), now + 1000);
    assert.deepEqual(reloaded.latestSessionEvents().map(x => x.id), ["later-walk"]);
    assert.throws(() => parseBatch({ schema_version: "1.0", events: [{ ...event("bad"), observed_at_ms: "yesterday" }] }));
  } finally {
    await new Promise<void>(resolve => server.close(() => resolve()));
    await rm(dir, { recursive: true, force: true });
  }
});
