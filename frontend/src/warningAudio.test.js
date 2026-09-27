import assert from "node:assert/strict";
import test from "node:test";
import { includesMac, WarningAudio, WARNING_TEXT } from "./warningAudio.js";

function fixture({ unavailable = false, speechAvailable = true } = {}) {
  let time = 0, nextTimer = 0;
  const timers = new Map(), statuses = [], utterances = [];
  const audio = {
    src: "", plays: [], pauses: 0, fail: false, defer: false, pendingResolves: [],
    play() {
      this.plays.push(this.src);
      if (this.fail) return Promise.reject(new Error("Playback denied"));
      if (this.defer) return new Promise((resolve) => this.pendingResolves.push(resolve));
      return Promise.resolve();
    },
    pause() { this.pauses += 1; },
    finish() { this.onended?.(); },
  };
  const speech = { canceled: 0, fail: false, defer: false,
    speak(utterance) {
      if (this.fail) throw new Error("Speech unavailable");
      utterances.push(utterance);
      if (!this.defer) utterance.onstart?.();
    }, cancel() { this.canceled += 1; },
  };
  const player = new WarningAudio({ now: () => time, audioFactory: () => audio,
    loadClips: async () => {
      if (unavailable) throw new Error("Local clip service unavailable");
      return { urls: { ahead: "clip:ahead", left: "clip:left", right: "clip:right" } };
    }, speech: speechAvailable ? speech : null, utteranceFactory: (text) => ({ text }),
    setTimer: (fn, delay) => { const id = ++nextTimer; timers.set(id, { fn, when: time + delay }); return id; },
    clearTimer: (id) => timers.delete(id), onStatus: (status) => statuses.push(status),
  });
  const advance = (ms) => {
    time += ms;
    for (;;) {
      const entry = [...timers].filter(([, timer]) => timer.when <= time).sort((a, b) => a[1].when-b[1].when)[0];
      if (!entry) break;
      timers.delete(entry[0]); entry[1].fn();
    }
  };
  return { player, audio, speech, statuses, utterances, advance, now: () => time,
    async ready() { await player.unlock(); player.setOutput("mac"); },
    clipsPlayed: () => audio.plays.filter((src) => src.startsWith("clip:")) };
}
const alert = (id, direction = "ahead", priority = "test", ttl_ms = 1500) => ({ id, direction, priority, ttl_ms });
const settle = async () => { await Promise.resolve(); await Promise.resolve(); };

test("Mac playback requires a user unlock and an output authorized by server state", async () => {
  const f = fixture();
  f.player.setOutput("mac");
  assert.equal(f.player.enqueue(alert("blocked")), false);
  assert.equal(f.audio.plays.length, 0);
  await f.player.unlock();
  f.player.setOutput("phone");
  assert.equal(f.player.enqueue(alert("phone-only")), false);
  f.player.setOutput("both");
  assert.equal(f.player.enqueue(alert("both")), true);
  await settle();
  assert.deepEqual(f.clipsPlayed(), ["clip:ahead"]);
  assert.equal(includesMac("off"), false);
});

test("TTL deducts server frame age and time spent waiting in the browser", async () => {
  const f = fixture(); await f.ready();
  f.advance(400);
  assert.equal(f.player.enqueue(alert("old"), { receivedAt: 0, ageMs: 1100 }), false);
  assert.equal(f.clipsPlayed().length, 0);
  assert.equal(f.player.enqueue(alert("fresh"), { receivedAt: 400, ageMs: 50 }), true);
  await settle();
  assert.equal(f.clipsPlayed().length, 1);
});

test("only the newest waiting alert is retained, and duplicates never replay", async () => {
  const f = fixture(); await f.ready();
  f.player.enqueue(alert("first")); await settle();
  f.player.enqueue(alert("old-waiter", "left"));
  f.player.enqueue(alert("new-waiter", "right"));
  assert.equal(f.player.pending.id, "new-waiter");
  assert.equal(f.player.enqueue(alert("first")), false);
  f.audio.finish(); await settle();
  assert.deepEqual(f.clipsPlayed(), ["clip:ahead", "clip:right"]);
  f.audio.finish();
  assert.equal(f.player.enqueue(alert("new-waiter", "right")), false);
});

test("an expired queued alert is discarded when the active clip finishes", async () => {
  const f = fixture(); await f.ready();
  f.player.enqueue(alert("first")); await settle();
  f.player.enqueue(alert("waiting", "left", "test", 100));
  f.advance(110);
  f.audio.finish();
  assert.deepEqual(f.clipsPlayed(), ["clip:ahead"]);
  assert.equal(f.player.active, null);
  assert.equal(f.statuses.at(-1).state, "expired");
});

test("an obstacle interrupts a test; a test cannot interrupt or queue behind an obstacle", async () => {
  const f = fixture(); await f.ready();
  f.player.enqueue(alert("test", "ahead", "test")); await settle();
  const lateTestEnd = f.audio.onended;
  f.player.enqueue(riskAlert("danger", { direction: "left" })); await settle();
  lateTestEnd();
  assert.equal(f.player.active.id, "danger");
  assert.equal(f.player.enqueue(alert("lower-priority", "right", "test")), false);
  assert.equal(f.player.pending, null);
  assert.deepEqual(f.clipsPlayed(), ["clip:ahead"]);
  assert.match(f.utterances[0].text, /on the left/);
});

test("pause/disconnect cancellation removes active and pending audio and ignores late callbacks", async () => {
  const f = fixture(); await f.ready();
  f.player.enqueue(alert("playing")); await settle();
  const lateEnd = f.audio.onended;
  f.player.enqueue(alert("pending", "right"));
  f.player.cancel("Video paused");
  lateEnd();
  f.advance(2000);
  assert.equal(f.player.active, null);
  assert.equal(f.player.pending, null);
  assert.deepEqual(f.clipsPlayed(), ["clip:ahead"]);
});

test("changing output immediately cancels audio even between Mac and Both", async () => {
  const f = fixture(); await f.ready();
  f.player.enqueue(alert("playing")); await settle();
  f.player.enqueue(alert("queued", "left"));
  f.player.setOutput("both");
  assert.equal(f.player.active, null);
  assert.equal(f.player.pending, null);
  f.player.setOutput("off");
  assert.equal(f.player.enqueue(alert("off")), false);
});

test("audio still waiting to start is canceled at its deadline; late promise resolution cannot revive it", async () => {
  const f = fixture(); await f.ready();
  f.audio.defer = true;
  f.player.enqueue(alert("slow", "ahead", "test", 100));
  f.advance(100);
  assert.equal(f.player.active, null);
  f.audio.pendingResolves[0](); await settle();
  assert.equal(f.player.active, null);
  assert.equal(f.statuses.at(-1).state, "expired");
});

test("local playback failure uses fixed English browser speech and reports the fallback", async () => {
  const f = fixture(); await f.ready();
  f.audio.fail = true;
  f.player.enqueue({ ...alert("fallback", "left"), text: "Untrusted class name train" }); await settle();
  assert.equal(f.utterances.length, 1);
  assert.equal(f.utterances[0].text, WARNING_TEXT.left);
  assert.equal(f.utterances[0].lang, "en-US");
  assert.equal(f.statuses.at(-1).state, "fallback");
  f.utterances[0].onerror();
  assert.equal(f.statuses.at(-1).state, "error");
  assert.equal(f.player.active, null);
});

test("missing local assets are explicit; available browser voice remains a user-authorized fallback", async () => {
  const f = fixture({ unavailable: true }); await f.ready();
  assert.equal(f.player.unlocked, true);
  assert.equal(f.statuses.at(-1).state, "fallback");
  f.player.enqueue(alert("speech"));
  assert.equal(f.utterances[0].text, WARNING_TEXT.ahead);
  const noFallback = fixture({ unavailable: true, speechAvailable: false });
  assert.equal(await noFallback.player.unlock(), false);
  assert.equal(noFallback.statuses.at(-1).state, "error");
});

test("a mid-playback failure cannot start a delayed speech fallback after the original deadline", async () => {
  const f = fixture(); await f.ready();
  f.player.enqueue(alert("mid-playback", "right", "test", 100)); await settle();
  f.advance(50);
  f.speech.defer = true;
  f.audio.onerror();
  assert.equal(f.utterances.length, 1);
  f.advance(50);
  assert.equal(f.player.active, null);
  f.utterances[0].onstart();
  assert.equal(f.player.active, null);
  assert.equal(f.statuses.at(-1).state, "expired");
});

test("default timer adapters retain the browser global receiver during unlock and playback", async (t) => {
  const f = fixture(), timers = new Map();
  let timerId = 0;
  t.mock.method(globalThis, "setTimeout", function (callback, delay) {
    assert.equal(this, globalThis, "WebKit timers require the Window receiver");
    const id = ++timerId;
    timers.set(id, { callback, delay });
    return id;
  });
  t.mock.method(globalThis, "clearTimeout", function (id) {
    assert.equal(this, globalThis, "WebKit timers require the Window receiver");
    timers.delete(id);
  });
  const player = new WarningAudio({ now: f.now, audioFactory: () => f.audio,
    loadClips: async () => ({ urls: { ahead: "clip:ahead" } }), speech: f.speech });
  assert.equal(await player.unlock(), true);
  player.setOutput("mac");
  assert.equal(player.enqueue(alert("native-receiver")), true);
  await settle();
  assert.equal(player.active.started, true);
  player.cancel();
  assert.equal(timers.size, 0);
});

test("a synchronous audio construction failure is reported and the next user click can retry", async () => {
  const f = fixture();
  f.player.audioFactory = () => { throw new TypeError("Audio unavailable"); };
  assert.equal(await f.player.unlock(), false);
  assert.equal(f.player.unlocking, null);
  assert.equal(f.statuses.at(-1).state, "error");
  assert.match(f.statuses.at(-1).message, /Audio unavailable/);
  f.player.audioFactory = () => f.audio;
  assert.equal(await f.player.unlock(), true);
  assert.equal(f.statuses.at(-1).state, "ready");
});

test("an unexpected unlock rejection clears its pending state and permits retry", async () => {
  const f = fixture(), clearTimer = f.player.clearTimer;
  let failOnce = true;
  f.player.clearTimer = (id) => {
    clearTimer(id);
    if (failOnce) { failOnce = false; throw new TypeError("Illegal invocation"); }
  };
  assert.equal(await f.player.unlock(), false);
  assert.equal(f.player.unlocking, null);
  assert.equal(f.player.unlocked, false);
  assert.equal(f.statuses.at(-1).state, "error");
  assert.match(f.statuses.at(-1).message, /Illegal invocation/);
  assert.equal(await f.player.unlock(), true);
  assert.equal(f.player.unlocking, null);
  assert.equal(f.statuses.at(-1).state, "ready");
});

const riskAlert = (id, overrides = {}) => ({ ...alert(id), schema_version: 2, priority: "obstacle", risk_level: "R1", speech_code: "camera_obstacle", direction_frame: "camera_image", ...overrides });
test("v2 risk alerts never play legacy Stop clips even when clips are ready", async () => {
  const f = fixture(); await f.ready();
  assert.equal(f.player.enqueue(riskAlert("v2", { direction: "left", text: "Stop now" })), true);
  assert.deepEqual(f.clipsPlayed(), []);
  assert.equal(f.utterances[0].text, "Caution. Possible obstacle on the left in the camera view. Your direction is unverified.");
});
test("urgent alerts interrupt queries and lower-priority replies cannot queue behind them", async () => {
  const f = fixture(); await f.ready();
  f.player.enqueue(riskAlert("query", { speech_code: "risk_explanation", reason_codes: ["image_corridor_overlap"], priority: "query" }));
  const lateEnd = f.utterances[0].onend;
  f.player.enqueue(riskAlert("urgent", { priority: "urgent", risk_level: "R3" }));
  lateEnd();
  assert.equal(f.player.active.id, "urgent");
  assert.equal(f.player.enqueue(riskAlert("reply", { speech_code: "risk_acknowledged", priority: "query" })), false);
  assert.equal(f.player.pending, null);
});
test("invalid v2 speech and unknown protocol versions are rejected without legacy fallback", async () => {
  const f = fixture(); await f.ready();
  for (const overrides of [{ speech_code: "unknown" }, { direction: "back" }, { priority: "invented" }, { schema_version: 3 }]) {
    assert.equal(f.player.enqueue(riskAlert(JSON.stringify(overrides), overrides)), false);
  }
  assert.deepEqual(f.clipsPlayed(), []);
  assert.equal(f.utterances.length, 0);
});
test("camera freshness cancellation removes active and queued evidence but allows health speech", async () => {
  const f = fixture(); await f.ready();
  f.player.enqueue(riskAlert("camera"));
  f.player.enqueue(riskAlert("next-camera"));
  const lateStart = f.utterances[0].onstart;
  f.player.cancelEvidence("Expired");
  lateStart();
  assert.equal(f.player.active, null);
  assert.equal(f.player.pending, null);
  f.player.enqueue(riskAlert("health", { speech_code: "perception_unavailable", priority: "health", direction_frame: "unavailable", risk_level: null }));
  f.player.cancelEvidence("No current camera evidence");
  assert.equal(f.player.active.id, "health");
  assert.doesNotMatch(f.utterances.at(-1).text, /stop/i);
});
test("a v2 alert cannot fall back to old clips when browser speech is unavailable", async () => {
  const f = fixture({ speechAvailable: false }); await f.ready();
  f.player.enqueue(riskAlert("unavailable"));
  assert.deepEqual(f.clipsPlayed(), []);
  assert.equal(f.player.active, null);
  assert.equal(f.statuses.at(-1).state, "error");
});

test("state invalidation preserves a new health notice delivered after a voice stop", async () => {
  const f = fixture(); await f.ready();
  f.player.enqueue(riskAlert("old"));
  f.player.cancel();
  f.player.enqueue(riskAlert("health-after-stop", { speech_code: "perception_unavailable", priority: "health", direction_frame: "unavailable", risk_level: null }));
  f.player.cancelContext("State unavailable");
  assert.equal(f.player.active.id, "health-after-stop");
  f.player.cancel();
  assert.equal(f.player.active, null);
});
test("browser voice prefers an available natural English voice", async () => {
  const f = fixture(); await f.ready();
  const natural = { name: "English Enhanced", lang: "en-US", localService: true };
  f.speech.getVoices = () => [{ name: "French", lang: "fr-FR" }, { name: "English Basic", lang: "en-US" }, natural];
  f.player.enqueue(riskAlert("natural"));
  assert.equal(f.utterances[0].voice, natural);
});

test("health notices cannot replace or interrupt an obstacle; an obstacle can interrupt health", async () => {
  const f = fixture(); await f.ready();
  const health = (id) => riskAlert(id, { speech_code: "perception_restored", priority: "health", direction_frame: "unavailable", risk_level: null });
  f.player.enqueue(riskAlert("active-obstacle"));
  f.player.enqueue(riskAlert("pending-obstacle"));
  assert.equal(f.player.enqueue(health("health-after-obstacle")), false);
  assert.equal(f.player.active.id, "active-obstacle");
  assert.equal(f.player.pending.id, "pending-obstacle");
  f.player.cancel();
  f.player.enqueue(health("active-health"));
  f.player.enqueue(riskAlert("new-obstacle"));
  assert.equal(f.player.active.id, "new-obstacle");
});
test("v2 age and local waiting time are deducted before any browser speech begins", async () => {
  const f = fixture(); await f.ready();
  f.advance(200);
  assert.equal(f.player.enqueue(riskAlert("too-old"), { receivedAt: 0, ageMs: 1300 }), false);
  assert.equal(f.utterances.length, 0);
  f.speech.defer = true;
  assert.equal(f.player.enqueue(riskAlert("only-50ms"), { receivedAt: 200, ageMs: 1450 }), true);
  f.advance(50);
  assert.equal(f.player.active, null);
  f.utterances[0].onstart();
  assert.equal(f.player.active, null);
});
test("non-test legacy production alerts cannot reach either voice backend", async () => {
  const f = fixture(); await f.ready();
  assert.equal(f.player.enqueue(alert("legacy-production", "ahead", "obstacle")), false);
  assert.deepEqual(f.clipsPlayed(), []);
  assert.equal(f.utterances.length, 0);
});

test("R1 to R2 escalation interrupts same-priority speech and discards queued lower-risk updates", async () => {
  const f = fixture(); await f.ready();
  f.player.enqueue(riskAlert("r1-active"));
  const lateEnd = f.utterances[0].onend;
  f.player.enqueue(riskAlert("r1-queued"));
  assert.equal(f.player.active.id, "r1-active");
  assert.equal(f.player.pending.id, "r1-queued");
  assert.equal(f.player.enqueue(riskAlert("r2-upgrade", { risk_level: "R2" })), true);
  assert.equal(f.player.active.id, "r2-upgrade");
  assert.equal(f.player.active.risk_level, "R2");
  assert.equal(f.player.pending, null);
  assert.equal(f.utterances.length, 2);
  lateEnd();
  assert.equal(f.player.active.id, "r2-upgrade");
  f.player.enqueue(riskAlert("r2-same-level", { risk_level: "R2" }));
  assert.equal(f.player.active.id, "r2-upgrade");
  assert.equal(f.player.pending.id, "r2-same-level");
});

test("an expired risk upgrade cannot interrupt a current alert", async () => {
  const f = fixture(); await f.ready();
  f.player.enqueue(riskAlert("r1-current"));
  assert.equal(f.player.enqueue(riskAlert("expired-r2", { risk_level: "R2" }), { ageMs: 1500 }), false);
  assert.equal(f.player.active.id, "r1-current");
  assert.equal(f.utterances.length, 1);
});
