import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { answerQuestion, eventFromFrame, loadEvents } from "./agent.ts";

const warningFrame = {
  schema_version: "1.0", frame_id: 14, video_timestamp_ms: 700,
  hazards: [{ target_id: 5, type: "person", direction: "center", approaching: "unknown" as const,
    evidence: ["bbox_footpoint_in_configured_corridor", "relative_image_region_medium", "consecutive_track_frames_2"] }],
  warning: { speak: true, text: "Stop. Pedestrian ahead.", target_id: 5, avoid_direction: "unknown" },
};

test("only spoken warnings become events, with matching hazard evidence", () => {
  assert.equal(eventFromFrame({ ...warningFrame, warning: { ...warningFrame.warning, speak: false } }), null);
  const event = eventFromFrame(warningFrame);
  assert.equal(event?.id, "14:5");
  assert.equal(event?.type, "person");
  assert.equal(event?.approaching, "unknown");
  assert.match(answerQuestion("Why did you warn me?", [event!]), /0:00.*person/u);
  assert.match(answerQuestion("Why did you warn me?", [event!]), /approach could not be confirmed/u);
});

test("reads a growing JSONL file and answers reports without inventing a safe direction", async () => {
  const dir = await mkdtemp(join(tmpdir(), "sky-agent-"));
  const path = join(dir, "frames.jsonl");
  try {
    await writeFile(path, [
      JSON.stringify({ ...warningFrame, warning: { ...warningFrame.warning, speak: false } }),
      JSON.stringify(warningFrame),
      '{"incomplete":',
    ].join("\n"));
    const events = await loadEvents(path);
    assert.equal(events?.length, 1);
    assert.match(answerQuestion("Trip summary", events!), /1 warnings recorded/u);
    assert.match(answerQuestion("Why did you warn me?", events!), /no safe avoidance direction was verified/u);
    assert.match(answerQuestion("How many car warnings?", events!), /No car warning was recorded/u);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("stair model events remain searchable even with a generic short audio cue", () => {
  const event = eventFromFrame({
    schema_version: "1.0", frame_id: 21, video_timestamp_ms: 2100,
    hazards: [{ target_id: "stairs:3", type: "stairs", direction: "center", approaching: "unknown",
      evidence: ["separate_stairs_model", "bbox_footpoint_in_configured_corridor", "consecutive_track_frames_2"] }],
    warning: { speak: true, text: "Stop. Obstacle ahead.", target_id: "stairs:3", avoid_direction: "unknown" },
  });
  assert.equal(event?.type, "stairs");
  assert.match(answerQuestion("Where were the stairs?", [event!]), /stairs/u);
});
