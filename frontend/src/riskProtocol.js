const DIRECTIONS = Object.freeze({ ahead: "ahead", left: "on the left", right: "on the right" });
const CAMERA_CODES = Object.freeze({ camera_obstacle: "obstacle", camera_surface: "ground change", camera_overhead: "overhead obstruction", camera_vehicle: "vehicle conflict" });
export const REASON_TEXT = Object.freeze({
  image_corridor_overlap: "Object overlaps the selected image corridor",
  persistent_observation: "Object persisted across observations",
  apparent_near_image_proxy: "Image position and size suggest proximity; distance is unmeasured",
  surface_change_candidate: "Possible surface change", drop_candidate: "Possible drop",
  overhead_alignment_candidate: "Possible overhead obstruction", vehicle_candidate: "Possible vehicle conflict",
  camera_direction_only: "Direction refers only to the camera image", metric_distance_unknown: "Distance is unmeasured",
  occluded_unresolved: "Earlier obstacle is no longer visible and remains unresolved",
  image_conflict_resolved: "Earlier overlap in the camera image ended; passage is not confirmed",
  no_confirmed_conflict: "No conflict confirmed by current image evidence", corridor_unconfigured: "Image corridor is not configured",
  evidence_stale: "Observation has expired", validated_ttc_budget: "Validated time-to-conflict threshold reached",
  new_relevance: "New relevant observation", risk_upgrade: "Evidence raised the risk level", direction_change: "Camera-image direction changed",
});
export const FIXED_SPEECH = Object.freeze({
  perception_unavailable: "Visual guidance is unavailable. Check your surroundings.",
  perception_restored: "Live observations have resumed. Your direction and distance remain unverified.",
  direction_unverified: "Your direction is unverified. Locations refer to the camera view.",
  vision_unavailable: "Visual guidance is unavailable. Check your surroundings.",
  risk_unresolved: "The earlier obstacle is no longer visible. It has not been confirmed resolved.",
  risk_acknowledged: "Acknowledged. The observation has not been confirmed resolved.",
  quiet_enabled: "Quiet mode enabled. Higher-priority alerts remain active.",
  quiet_disabled: "Normal alerts resumed.",
  false_alert_saved: "False alert feedback saved.",
  no_evidence: "There is no current evidence to explain. This does not mean the path is clear.",
  no_recent_alert: "There is no recent alert to repeat.",
});
export const RISK_COMMANDS = Object.freeze({ explain: "Explain risk", acknowledge: "Acknowledge", quiet: "Quiet mode", normal: "Normal alerts", repeat: "Repeat alert", report_false_alert: "Report false alert" });
export const PRIORITY_RANK = Object.freeze({ urgent: 3, obstacle: 2, health: 2, query: 1, test: 0 });
export const isCameraSpeech = (code) => Object.hasOwn(CAMERA_CODES, code);
export function reasonText(codes) {
  return Array.isArray(codes) ? [...new Set(codes)].filter((code) => Object.hasOwn(REASON_TEXT, code)).map((code) => REASON_TEXT[code]) : [];
}
export function fixedSpeech(speech) {
  const code = speech?.speech_code || speech?.code;
  if (isCameraSpeech(code)) {
    if (speech.direction_frame !== undefined && speech.direction_frame !== "camera_image") return null;
    if (!Object.hasOwn(DIRECTIONS, speech.direction)) return null;
    return `Caution. Possible ${CAMERA_CODES[code]} ${DIRECTIONS[speech.direction]} in the camera view. Your direction is unverified.`;
  }
  if (code === "risk_explanation") {
    const reasons = speech.reason_codes;
    if (!Array.isArray(reasons) || !reasons.length || reasons.length > Object.keys(REASON_TEXT).length
      || reasons.some((code) => !Object.hasOwn(REASON_TEXT, code))) return null;
    if (reasons.includes("occluded_unresolved")) return FIXED_SPEECH.risk_unresolved;
    return reasons.includes("image_corridor_overlap") && reasons.includes("persistent_observation")
      ? "This object overlaps the selected camera corridor across several observations. Its distance and direction relative to you are unknown."
      : "The alert is based on observations in the selected camera view. Its distance and direction relative to you are unknown.";
  }
  return Object.hasOwn(FIXED_SPEECH, code) ? FIXED_SPEECH[code] : null;
}
const HEALTH_CODES = new Set(["perception_unavailable", "perception_restored", "direction_unverified"]);
const QUERY_CODES = new Set(["risk_explanation", "risk_unresolved", "risk_acknowledged", "quiet_enabled", "quiet_disabled", "false_alert_saved", "no_evidence", "no_recent_alert", "vision_unavailable"]);
export function validVoiceEvent(event) {
  if (!event || typeof event.id !== "string" || !event.id.length || event.id.length > 128
    || !Number.isFinite(event.ttl_ms) || event.ttl_ms <= 0 || event.ttl_ms > 1500) return false;
  if (event.schema_version === undefined) return event.priority === "test" && Object.hasOwn(DIRECTIONS, event.direction);
  if (event.schema_version !== 2) return false;
  if (event.priority === "query") return QUERY_CODES.has(event.speech_code) && Boolean(fixedSpeech(event));
  if (event.priority === "health") return HEALTH_CODES.has(event.speech_code)
    && event.direction_frame === "unavailable" && event.risk_level === null && event.direction === "ahead";
  return isCameraSpeech(event.speech_code) && event.direction_frame === "camera_image"
    && Object.hasOwn(DIRECTIONS, event.direction)
    && ((["R1", "R2"].includes(event.risk_level) && event.priority === "obstacle")
      || (event.risk_level === "R3" && event.priority === "urgent"));
}
export function commandReplyEvent(message, id) {
  if (message?.type !== "command_reply" || !Object.hasOwn(RISK_COMMANDS, message.command)) return null;
  const speech = message.speech;
  if (!speech || !QUERY_CODES.has(speech.code) || !fixedSpeech(speech)) return null;
  if (speech.code === "risk_explanation" && !Object.hasOwn(speech, "ttl_ms")) return null;
  const event = { ...speech, id, schema_version: 2, speech_code: speech.code, priority: "query",
    ttl_ms: Object.hasOwn(speech, "ttl_ms") ? speech.ttl_ms : 1500 };
  return validVoiceEvent(event) ? event : null;
}
const CONFIDENCE = Object.freeze({
  presence: { tentative: "Tentative", supported: "Supported", unknown: "Unknown" },
  path: { image_proxy: "Image proxy only", validated: "Validated", unknown: "Unknown" },
  category: { unconfirmed: "Unconfirmed", validated: "Validated" },
  distance: { unknown: "Unmeasured", validated: "Validated" },
});
export function riskPresentation(risk, perception, { available = true, perceptionAvailable = available } = {}) {
  const level = available && /^R[0-3]$/.test(risk?.risk_level) ? risk.risk_level : null;
  const lifecycle = available || risk?.lifecycle === "occluded_unresolved" ? risk?.lifecycle : "unknown";
  const lifecycleText = { observed: "Currently observed", occluded_unresolved: "Out of view · unresolved", image_conflict_resolved: "Image overlap ended · passage unverified", unknown: "Unknown" }[lifecycle] || "Unknown";
  const confidence = Object.fromEntries(Object.entries(CONFIDENCE).map(([key, values]) => [key, available && Object.hasOwn(values, risk?.evidence_confidence?.[key]) ? values[risk.evidence_confidence[key]] : key === "distance" ? "Unmeasured" : "Unknown"]));
  return {
    level, lifecycleText, confidence,
    levelText: level ? { R0: "R0 · No confirmed image conflict", R1: "R1 · Possible image conflict", R2: "R2 · Persistent image conflict", R3: "R3 · Urgent risk evidence" }[level] : "Risk level unavailable",
    health: perceptionAvailable && perception?.status === "limited" ? "Limited" : "Unavailable",
    direction: available && risk?.direction_frame === "camera_image" && Object.hasOwn(DIRECTIONS, risk?.direction) && lifecycle === "observed" ? `Camera image: ${DIRECTIONS[risk.direction]}` : "Camera-image direction unavailable",
    reasons: available ? reasonText(risk?.reason_codes) : [],
  };
}
