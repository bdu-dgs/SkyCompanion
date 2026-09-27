import { fixedSpeech, isCameraSpeech, PRIORITY_RANK, validVoiceEvent } from "./riskProtocol.js";
export const WARNING_TEXT = Object.freeze({
  ahead: "Stop. Obstacle ahead.", left: "Stop. Obstacle left.", right: "Stop. Obstacle right.",
});
const SILENCE = "data:audio/wav;base64,UklGRsQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
export const includesMac = (output) => output === "mac" || output === "both";

async function loadLocalClips() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  const urls = {};
  try {
    const response = await fetch("/api/tts/manifest", { signal: controller.signal, cache: "no-store" });
    if (!response.ok) throw new Error(`Audio manifest returned ${response.status}.`);
    const manifest = await response.json();
    if (!manifest.ready) throw new Error("Local SkyCompanion clips are not ready.");
    const loaded = await Promise.allSettled(Object.keys(WARNING_TEXT).map(async (direction) => {
      const clip = manifest.clips?.[direction];
      const expected = `/api/tts/clips/en-obstacle-${direction}.wav`;
      if (!clip?.ready || clip.url !== expected) throw new Error(`The ${direction} clip is unavailable.`);
      const audio = await fetch(expected, { signal: controller.signal });
      if (!audio.ok) throw new Error(`The ${direction} clip returned ${audio.status}.`);
      urls[direction] = URL.createObjectURL(await audio.blob());
    }));
    const failure = loaded.find((result) => result.status === "rejected");
    if (failure) throw failure.reason;
    return { urls, dispose: () => Object.values(urls).forEach((url) => URL.revokeObjectURL(url)) };
  } catch (error) {
    controller.abort();
    Object.values(urls).forEach((url) => URL.revokeObjectURL(url));
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

/** One active alert and at most one pending alert. TTL limits when playback may start. */
export class WarningAudio {
  constructor({
    now = () => performance.now(), audioFactory = () => new Audio(),
    loadClips = loadLocalClips, speech = globalThis.speechSynthesis,
    utteranceFactory = (text) => new SpeechSynthesisUtterance(text),
    setTimer = (...args) => globalThis.setTimeout(...args),
    clearTimer = (id) => globalThis.clearTimeout(id), onStatus = () => {},
  } = {}) {
    Object.assign(this, { now, audioFactory, loadClips, speech, utteranceFactory, setTimer, clearTimer, onStatus });
    this.enabled = false;
    this.unlocked = false;
    this.disposed = false;
    this.audio = null;
    this.clips = null;
    this.active = null;
    this.pending = null;
    this.seen = new Map();
    this.unlocking = null;
  }

  status(state, message) {
    if (!this.disposed) this.onStatus({ state, message, unlocked: this.unlocked });
  }

  // Must be called directly from a user click, never from a frame or state message.
  unlock() {
    if (this.disposed) return Promise.resolve(false);
    if (this.unlocked) return Promise.resolve(true);
    if (this.unlocking) return this.unlocking;
    try {
      this.audio = this.audioFactory();
      this.audio.preload = "auto";
      this.audio.src = SILENCE;
    } catch (error) {
      this.status("error", `Could not prepare audio: ${error?.message || "Browser audio is unavailable."} Click Enable voice to retry.`);
      return Promise.resolve(false);
    }
    let unlockPlay;
    try { unlockPlay = this.audio.play(); } catch (error) { unlockPlay = Promise.reject(error); }
    this.status("loading", "Preparing local SkyCompanion voice…");
    this.unlocking = (async () => {
      let audioAllowed = true;
      let unlockTimer;
      try {
        await Promise.race([unlockPlay, new Promise((_, reject) => {
          unlockTimer = this.setTimer(() => reject(new Error("Audio permission timed out.")), 2000);
        })]);
      } catch { audioAllowed = false; }
      finally { this.clearTimer(unlockTimer); }
      this.audio.pause();
      let failure = audioAllowed ? "" : "Browser blocked local audio playback.";
      if (audioAllowed) {
        try {
          this.clips = await this.loadClips();
        } catch (error) {
          failure = error?.message || "Could not preload local clips.";
        }
      }
      if (this.disposed) { this.clips?.dispose?.(); this.clips = null; return false; }
      this.unlocked = Boolean(this.clips || this.speech?.speak);
      if (this.clips) this.status("ready", "Local SkyCompanion clips ready on this Mac.");
      else if (this.unlocked) this.status("fallback", `${failure} Browser voice will be used as a fallback.`);
      else this.status("error", `${failure} No browser voice fallback is available. Click Enable voice to retry.`);
      return this.unlocked;
    })().catch((error) => {
      this.unlocked = false;
      this.status("error", `Could not prepare audio: ${error?.message || "Unexpected browser audio error."} Click Enable voice to retry.`);
      return false;
    }).finally(() => { this.unlocking = null; });
    return this.unlocking;
  }

  setOutput(output) {
    const enabled = includesMac(output);
    const changed = this.output !== output;
    if (changed) this.cancel();
    this.output = output;
    this.enabled = enabled;
    if (changed) {
      if (!enabled) this.status("idle", "Mac voice is off.");
      else if (!this.unlocked) this.status("locked", "Click Enable Mac audio or Test voice to allow playback on this page.");
      else if (this.clips) this.status("ready", "Local SkyCompanion clips ready on this Mac.");
      else this.status("fallback", "Local clips are unavailable. Browser voice fallback is enabled.");
    }
  }

  enqueue(event, { ageMs = 0, receivedAt = this.now() } = {}) {
    if (this.disposed || !this.enabled) return false;
    if (!this.unlocked) {
      this.status("locked", "Mac audio needs a user click. Click Enable Mac audio or Test voice.");
      return false;
    }
    if (!validVoiceEvent(event) || this.seen.has(event.id)) return false;
    if (!Number.isFinite(event.ttl_ms) || event.ttl_ms <= 0 || !Number.isFinite(ageMs) || ageMs < 0
      || !Number.isFinite(receivedAt)) return false;
    const v2 = event.schema_version === 2;
    if (event.schema_version !== undefined && !v2) return false;
    const text = v2 ? fixedSpeech(event) : WARNING_TEXT[Object.hasOwn(WARNING_TEXT, event.direction) ? event.direction : "ahead"];
    if (!text || (v2 && !Object.hasOwn(PRIORITY_RANK, event.priority))) return false;
    this.seen.set(event.id, true);
    if (this.seen.size > 256) this.seen.delete(this.seen.keys().next().value);
    const item = { id: event.id, direction: Object.hasOwn(WARNING_TEXT, event.direction) ? event.direction : "ahead",
      v2, text, cameraEvidence: v2 && (isCameraSpeech(event.speech_code) || event.speech_code === "risk_explanation"),
      priority: v2 ? event.priority : event.priority === "test" ? "test" : "obstacle",
      risk_level: v2 && isCameraSpeech(event.speech_code) ? event.risk_level : null,
      deadline: receivedAt + Math.min(event.ttl_ms, 5000) - ageMs };
    if (item.deadline <= this.now()) { this.status("expired", "An expired alert was skipped."); return false; }
    const rank = (entry) => PRIORITY_RANK[entry.priority] + (entry.priority === "obstacle" ? 0.5 : 0);
    if (this.active && rank(item) < rank(this.active)) {
      this.status("busy", "Lower-priority speech skipped while an alert is playing.");
      return false;
    }
    const riskUpgrade = this.active?.risk_level && item.risk_level && item.risk_level > this.active.risk_level;
    if (this.active && (rank(item) > rank(this.active) || riskUpgrade)) this.cancel();
    if (this.active) {
      if (!this.pending || rank(item) >= rank(this.pending)) this.pending = item;
      return true;
    }
    this.start(item);
    return true;
  }

  current(item) { return !this.disposed && this.enabled && this.active === item; }

  start(item) {
    if (!this.enabled || this.disposed || item.deadline <= this.now()) {
      this.status("expired", "An expired alert was skipped.");
      return;
    }
    this.active = item;
    item.started = false;
    item.startTimer = this.setTimer(() => {
      if (this.current(item) && !item.started) {
        this.stopActive();
        this.status("expired", "Alert audio did not start before its deadline.");
        this.drain();
      }
    }, item.deadline - this.now());
    const started = () => {
      if (!this.current(item) || item.started) return;
      if (item.deadline <= this.now()) {
        this.stopActive();
        this.status("expired", "An expired alert was canceled before playback.");
        this.drain();
        return;
      }
      item.started = true;
      this.clearTimer(item.startTimer);
      item.endTimer = this.setTimer(() => {
        if (this.current(item)) { this.stopActive(); this.status("error", "Audio playback did not finish. It was canceled."); this.drain(); }
      }, 10000);
    };
    const ended = () => {
      if (!this.current(item)) return;
      this.stopActive();
      this.status("ready", "Alert playback finished. Browser status does not confirm audible sound.");
      this.drain();
    };
    item.startedCallback = started;
    item.endedCallback = ended;
    // Version 2 is never mapped to the legacy Stop WAV assets.
    const source = item.v2 ? null : this.clips?.urls[item.direction];
    if (!source) { this.fallback(item, item.v2 ? "Using the risk protocol voice." : "Local SkyCompanion audio is unavailable."); return; }
    this.audio.src = source;
    this.audio.onended = ended;
    this.audio.onerror = () => this.fallback(item, "Local SkyCompanion playback failed.");
    this.status("playing", `Playing local voice: ${item.text}`);
    try {
      Promise.resolve(this.audio.play()).then(() => { if (!item.usingFallback) started(); }, () => this.fallback(item, "Browser blocked or failed local audio playback."));
    } catch { this.fallback(item, "Could not start local audio playback."); }
  }

  fallback(item, reason) {
    if (!this.current(item) || item.usingFallback) return;
    item.usingFallback = true;
    this.audio.onended = null;
    this.audio.onerror = null;
    this.audio.pause();
    if (item.deadline <= this.now()) {
      this.stopActive(); this.status("expired", `${reason} The alert expired; fallback was skipped.`); this.drain(); return;
    }
    if (!this.speech?.speak) {
      this.stopActive(); this.status("error", `${reason} No browser voice fallback is available.`); this.drain(); return;
    }
    this.clearTimer(item.startTimer);
    this.clearTimer(item.endTimer);
    item.started = false;
    item.startTimer = this.setTimer(() => {
      if (this.current(item) && !item.started) {
        this.stopActive(); this.status("expired", "Browser voice did not start before the alert expired."); this.drain();
      }
    }, item.deadline - this.now());
    try {
      const utterance = this.utteranceFactory(item.text);
      utterance.lang = "en-US";
      const voices = this.speech.getVoices?.() || [];
      const english = voices.filter((voice) => /^en(?:-|_)/i.test(voice.lang || ""));
      const voiceScore = (voice) => (/natural|enhanced|premium/i.test(voice.name || "") ? 4 : 0)
        + (voice.localService ? 2 : 0) + (/^en-US$/i.test(voice.lang || "") ? 1 : 0);
      const selectedVoice = english.sort((a, b) => voiceScore(b) - voiceScore(a))[0];
      if (selectedVoice) utterance.voice = selectedVoice;
      utterance.onstart = item.startedCallback;
      utterance.onend = item.endedCallback;
      utterance.onerror = () => {
        if (this.current(item)) { this.stopActive(); this.status("error", "Local audio and browser voice both failed. Check audio permissions and output."); this.drain(); }
      };
      this.status("fallback", `${reason} Using browser voice: ${item.text}`);
      this.speech.speak(utterance);
    } catch {
      this.stopActive(); this.status("error", "Browser voice fallback failed to start."); this.drain();
    }
  }

  stopActive() {
    const previous = this.active;
    this.active = null; // Invalidate late media callbacks before pause/cancel.
    if (previous) { this.clearTimer(previous.startTimer); this.clearTimer(previous.endTimer); }
    if (this.audio) {
      this.audio.onended = null; this.audio.onerror = null; this.audio.pause();
      try { this.audio.currentTime = 0; } catch { /* Some browsers cannot seek before metadata exists. */ }
    }
    this.speech?.cancel?.();
  }

  drain() {
    const next = this.pending;
    this.pending = null;
    if (next) this.start(next);
  }

  cancelContext(message) {
    if (this.pending?.priority !== "health") this.pending = null;
    if (this.active && this.active.priority !== "health") {
      this.stopActive();
      if (message) this.status("idle", message);
      this.drain();
    }
  }

  cancelEvidence(message) {
    if (this.pending?.cameraEvidence) this.pending = null;
    if (this.active?.cameraEvidence) {
      this.stopActive();
      if (message) this.status("idle", message);
      this.drain();
    }
  }

  cancel(message) {
    this.pending = null;
    this.stopActive();
    if (message) this.status("idle", message);
  }

  dispose() {
    this.disposed = true;
    this.enabled = false;
    this.cancel();
    this.clips?.dispose?.();
    this.clips = null;
  }
}
