import assert from "node:assert/strict";
import test from "node:test";
import { commandReplyEvent, fixedSpeech, reasonText, riskPresentation, FIXED_SPEECH, validVoiceEvent } from "./riskProtocol.js";

test("camera speech ignores arbitrary text and requires a valid camera direction", () => {
  const event = { schema_version: 2, speech_code: "camera_surface", direction_frame: "camera_image", direction: "left", text: "Run left. Safe path." };
  assert.equal(fixedSpeech(event), "Caution. Possible ground change on the left in the camera view. Your direction is unverified.");
  assert.equal(fixedSpeech({ ...event, direction: "behind" }), null);
  assert.equal(fixedSpeech({ ...event, direction_frame: "wearer" }), null);
  assert.equal(fixedSpeech({ ...event, speech_code: "invented" }), null);
});
test("explanations only read whitelisted reasons and unresolved observations never repeat directions", () => {
  const speech = fixedSpeech({ code: "risk_explanation", reason_codes: ["image_corridor_overlap", "persistent_observation", "metric_distance_unknown"] });
  assert.match(speech, /selected camera corridor/);
  assert.equal(speech.split(". ").length, 2);
  assert.equal(fixedSpeech({ code: "risk_explanation", reason_codes: ["Turn left now"] }), null);
  assert.equal(fixedSpeech({ code: "risk_explanation", reason_codes: [] }), null);
  assert.equal(reasonText(["metric_distance_unknown", "metric_distance_unknown"]).length, 1);
  assert.equal(fixedSpeech({ code: "risk_unresolved", direction: "left" }), FIXED_SPEECH.risk_unresolved);
  for (const code of ["perception_unavailable", "perception_restored", "direction_unverified"]) assert.doesNotMatch(fixedSpeech({ code }), /stop/i);
});
test("command replies require a known command and a known speech code", () => {
  const message = { type: "command_reply", command: "explain", speech: { code: "risk_explanation", reason_codes: ["camera_direction_only"], ttl_ms: 1500 } };
  assert.equal(commandReplyEvent(message, "one").priority, "query");
  assert.equal(commandReplyEvent({ ...message, command: "move" }, "two"), null);
  assert.equal(commandReplyEvent({ ...message, speech: { code: "unknown", text: "Trust me" } }, "three"), null);
});
test("R0 stays distinct from health, confidence, and any safe-path claim", () => {
  const risk = { risk_level: "R0", lifecycle: "observed", direction: "right", direction_frame: "camera_image", evidence_confidence: { presence: "supported", path: "image_proxy", category: "unconfirmed", distance: "unknown" } };
  const view = riskPresentation(risk, { status: "limited" });
  assert.equal(view.levelText, "R0 · No confirmed image conflict");
  assert.equal(view.health, "Limited");
  assert.equal(view.confidence.path, "Image proxy only");
  assert.equal(view.confidence.distance, "Unmeasured");
  assert.equal(view.direction, "Camera image: on the right");
  const expired = riskPresentation(risk, { status: "limited" }, { available: false });
  assert.equal(expired.level, null);
  assert.equal(expired.health, "Unavailable");
  assert.doesNotMatch(expired.direction, /right/);
  assert.doesNotMatch(riskPresentation({ ...risk, lifecycle: "occluded_unresolved" }, { status: "limited" }).direction, /right/);
});

test("production events require matching v2 risk level, priority, camera frame and bounded TTL", () => {
  const event = { id: "valid", schema_version: 2, speech_code: "camera_obstacle", risk_level: "R2", direction_frame: "camera_image", direction: "ahead", priority: "obstacle", ttl_ms: 1500 };
  assert.equal(validVoiceEvent(event), true);
  assert.equal(validVoiceEvent({ ...event, risk_level: "R3", priority: "urgent" }), true);
  for (const invalid of [{ risk_level: null }, { risk_level: undefined }, { risk_level: "R0" }, { risk_level: "R3" },
    { priority: "urgent" }, { priority: "health" }, { priority: "query" }, { direction_frame: undefined },
    { direction_frame: "wearer" }, { schema_version: undefined }, { ttl_ms: 1501 }, { ttl_ms: 0 }]) {
    assert.equal(validVoiceEvent({ ...event, ...invalid }), false, JSON.stringify(invalid));
  }
  assert.equal(validVoiceEvent({ id: "legacy", direction: "ahead", priority: "test", ttl_ms: 1500 }), true);
  assert.equal(validVoiceEvent({ id: "legacy", direction: "ahead", priority: "obstacle", ttl_ms: 1500 }), false);
});
test("health events require the health whitelist, unavailable direction frame and null risk", () => {
  const event = { id: "health", schema_version: 2, speech_code: "perception_unavailable", risk_level: null, direction_frame: "unavailable", direction: "ahead", priority: "health", ttl_ms: 1500 };
  assert.equal(validVoiceEvent(event), true);
  for (const invalid of [{ risk_level: "R1" }, { risk_level: undefined }, { speech_code: "camera_obstacle" }, { direction_frame: "camera_image" }, { direction: "left" }, { priority: "urgent" }]) {
    assert.equal(validVoiceEvent({ ...event, ...invalid }), false);
  }
});
test("paused explanation is fixed and query TTL is preserved without renewing expired evidence", () => {
  assert.equal(commandReplyEvent({ type: "command_reply", command: "explain", speech: { code: "vision_unavailable" } }, "paused").speech_code, "vision_unavailable");
  const message = { type: "command_reply", command: "explain", speech: { code: "risk_explanation", reason_codes: ["image_corridor_overlap"], ttl_ms: 42 } };
  assert.equal(commandReplyEvent(message, "fresh").ttl_ms, 42);
  for (const ttl_ms of [undefined, NaN, 0, -1, 1501]) assert.equal(commandReplyEvent({ ...message, speech: { ...message.speech, ttl_ms } }, "expired"), null);
  assert.equal(commandReplyEvent({ ...message, speech: { code: "risk_explanation", reason_codes: ["image_corridor_overlap"] } }, "missing"), null);
});
