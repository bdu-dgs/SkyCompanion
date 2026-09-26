import { createReadStream } from "node:fs";
import { access } from "node:fs/promises";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

type Hazard = { target_id?: number | string; type?: string; direction?: string; approaching?: boolean | "unknown"; evidence?: string[] };
type FrameRecord = {
  schema_version?: string;
  frame_id?: number;
  video_timestamp_ms?: number;
  hazards?: Hazard[];
  warning?: { speak?: boolean; text?: string; target_id?: number | string; avoid_direction?: string };
};
export type WarningEvent = {
  id: string;
  frameId: number;
  videoTimestampMs: number;
  text: string;
  targetId: number | string;
  type: string;
  direction: string;
  evidence: string[];
  approaching: boolean | "unknown";
  avoidDirection: string;
  sessionId?: string;
  observedAtMs?: number;
  receivedAtMs?: number;
};

export const defaultFramesPath = fileURLToPath(new URL("../../run/frames.jsonl", import.meta.url));

export function eventFromFrame(frame: FrameRecord): WarningEvent | null {
  const warning = frame.warning;
  if (frame.schema_version !== "1.0" || !warning?.speak ||
      typeof frame.frame_id !== "number" || typeof frame.video_timestamp_ms !== "number") return null;
  const hazard = frame.hazards?.find((item) => item.target_id === warning.target_id);
  return {
    id: `${frame.frame_id}:${String(warning.target_id ?? "unknown")}`,
    frameId: frame.frame_id,
    videoTimestampMs: frame.video_timestamp_ms,
    text: warning.text || "Warning issued",
    targetId: warning.target_id ?? "unknown",
    type: hazard?.type ?? "unknown",
    direction: hazard?.direction ?? "unknown",
    evidence: hazard?.evidence ?? [],
    approaching: hazard?.approaching ?? "unknown",
    avoidDirection: warning.avoid_direction ?? "unknown",
  };
}

export async function loadEvents(path: string): Promise<WarningEvent[] | null> {
  try { await access(path); } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
  const events: WarningEvent[] = [];
  const lines = createInterface({ input: createReadStream(path, { encoding: "utf8" }), crlfDelay: Infinity });
  for await (const line of lines) {
    if (!line.trim()) continue;
    try {
      const event = eventFromFrame(JSON.parse(line) as FrameRecord);
      if (event) events.push(event);
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
      // A live producer may still be writing its final line.
    }
  }
  return events;
}

function timeLabel(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
function typeLabel(type: string): string {
  return type;
}
function directionLabel(direction: string): string {
  return direction === "center" ? "ahead" : direction;
}
function eventLine(event: WarningEvent): string {
  const label = event.observedAtMs === undefined
    ? `video ${timeLabel(event.videoTimestampMs)} (frame ${event.frameId})`
    : `${new Date(event.observedAtMs).toISOString().replace("T", " ").replace(".000Z", " UTC")} (frame ${event.frameId})`;
  return `${label}: ${typeLabel(event.type)} ${directionLabel(event.direction)}; "${event.text}"`;
}
function reasonLine(event: WarningEvent): string {
  const facts: string[] = [];
  if (event.evidence.includes("separate_stairs_model")) facts.push("a dedicated stair model detected a candidate");
  if (event.evidence.includes("bbox_footpoint_in_configured_corridor")) facts.push("target inside the configured walking corridor");
  if (event.evidence.some((item) => item.startsWith("relative_image_region_"))) facts.push("target in a nearer image region");
  if (event.evidence.some((item) => item.startsWith("consecutive_track_frames_"))) facts.push("confirmed across tracked frames");
  if (event.approaching === "unknown") facts.push("approach could not be confirmed");
  if (event.avoidDirection === "unknown") facts.push("no safe avoidance direction was verified");
  if (event.evidence.includes("step_height_and_ascent_direction_unknown")) facts.push("step height and ascent direction are unknown");
  return `Evidence: ${facts.join("; ") || "no further evidence in the record"}.`;
}

export function answerQuestion(question: string, events: WarningEvent[] | null): string {
  const q = question.trim().toLowerCase();
  if (/^(help|menu|commands?)$/u.test(q)) return "Ask: What happened? Why did you warn me? Trip summary? You can also ask about pedestrian or car warnings.";
  if (!events) return "No phone events have been synchronized yet.";
  if (!events.length) return "No spoken warning events were recorded in this session.";

  const filter = /stairs?|steps?/u.test(q) ? "stairs" : /pedestrian|person/u.test(q) ? "person" :
    /bicycle|bike/u.test(q) ? "bicycle" : /car/u.test(q) ? "car" : null;
  const matches = filter ? events.filter((event) => event.type === filter) : events;
  if (!matches.length) return `No ${filter} warning was recorded in this session.`;
  const last = matches.at(-1)!;
  if (/why|reason|evidence/u.test(q)) return `${eventLine(last)}\n${reasonLine(last)}`;
  if (/summary|report|how many|count/u.test(q)) {
    const counts = new Map<string, number>();
    for (const event of matches) counts.set(event.type, (counts.get(event.type) ?? 0) + 1);
    const detail = [...counts].map(([kind, count]) => `${typeLabel(kind)} ${count}`).join(", ");
    return `${matches.length} warnings recorded (${detail}). Latest: ${eventLine(last)}. These count spoken warnings, not distinct objects.`;
  }
  if (/last|recent|happen|what|where|when/u.test(q)) return `Latest warning: ${eventLine(last)}.`;
  return "I can answer from recorded warnings. Ask: What happened? Why did you warn me? Trip summary?";
}

export function answerSynchronizedQuestion(question: string, events: WarningEvent[], now = Date.now()): string {
  const answer = answerQuestion(question, events.length ? events : null);
  const latest = events.at(-1);
  if (!latest?.observedAtMs) return answer;
  const age = now - latest.observedAtMs;
  if (age <= 15_000 && age >= -5_000) return answer;
  return `No current live update; this answer uses synchronized history only.\n${answer}`;
}
