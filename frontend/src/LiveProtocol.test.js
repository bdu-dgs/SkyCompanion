import assert from "node:assert/strict";
import test from "node:test";
import { EMPTY_LIVE_STATE, invalidatesDisplay, pointerRoi, sameFrameContext, validRoi } from "./liveProtocol.js";

const receiving = { ...EMPTY_LIVE_STATE, session_id: "phone-1", revision: 3,
  connection: "connected", capture: "receiving", dimensions: [960, 540] };

test("crop accepts the full image and refuses outside, empty or nonfinite coordinates", () => {
  assert.equal(validRoi([0, 0, 1, 1]), true);
  assert.equal(validRoi([0.1, 0.2, 0.8, 0.6]), true);
  for (const roi of [null, [0, 0, 0, 1], [-0.1, 0, 1, 1], [0.9, 0, 0.2, 1], [0, NaN, 1, 1]]) {
    assert.equal(validRoi(roi), false);
  }
});

test("dragging in either direction selects the same normalized image area", () => {
  assert.deepEqual(pointerRoi([0.25, 0.25], [0.75, 0.75]), [0.25, 0.25, 0.5, 0.5]);
  assert.deepEqual(pointerRoi([0.75, 0.75], [0.25, 0.25]), [0.25, 0.25, 0.5, 0.5]);
});

test("late frames cannot cross session, revision, pause, or disconnect boundaries", () => {
  const frame = { session_id: "phone-1", revision: 3 };
  assert.equal(sameFrameContext(frame, receiving), true);
  for (const changed of [{ session_id: "phone-2" }, { revision: 4 },
    { connection: "disconnected" }, { capture: "paused" }, { capture: "no_frames" }]) {
    assert.equal(sameFrameContext(frame, { ...receiving, ...changed }), false);
  }
});

test("lifecycle changes invalidate in-flight decode; periodic metrics do not", () => {
  assert.equal(invalidatesDisplay(receiving, { ...receiving, metrics: { received_fps: 5 } }), false);
  for (const changed of [{ session_id: "phone-2" }, { revision: 4 }, { capture: "no_frames" },
    { connection: "ended" }, { analysis_enabled: true }, { dimensions: [540, 960] },
    { model: { state: "error" } }]) {
    assert.equal(invalidatesDisplay(receiving, { ...receiving, ...changed }), true);
  }
});
