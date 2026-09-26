import { appendFile, mkdir, readFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { WarningEvent } from "./agent.ts";

export type PhoneEvent = {
  event_id: string;
  session_id: string;
  observed_at_ms: number;
  processed_at_ms: number;
  video_timestamp_ms?: number | null;
  frame_id: number;
  type: string;
  direction: "left" | "center" | "right" | "unknown";
  warning_text: string;
  target_id: number | string;
  avoid_direction: "left" | "right" | "unknown";
  approaching: boolean | "unknown";
  evidence: string[];
};

export type StoredEvent = PhoneEvent & { received_at_ms: number };
const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const shortString = (value: unknown, max = 200): value is string =>
  typeof value === "string" && value.length > 0 && value.length <= max;
const timestamp = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;

export function parseBatch(value: unknown): PhoneEvent[] {
  if (!isObject(value) || value.schema_version !== "1.0" || !Array.isArray(value.events) ||
      value.events.length < 1 || value.events.length > 50) throw new Error("Invalid event batch");
  return value.events.map((item: unknown) => {
    if (!isObject(item) || !shortString(item.event_id, 128) || !shortString(item.session_id, 128) ||
        !timestamp(item.observed_at_ms) || !timestamp(item.processed_at_ms) ||
        item.processed_at_ms < item.observed_at_ms ||
        !Number.isSafeInteger(item.frame_id) || (item.frame_id as number) < 0 ||
        !shortString(item.type, 64) || !shortString(item.warning_text, 200) ||
        !["left", "center", "right", "unknown"].includes(String(item.direction)) ||
        !["left", "right", "unknown"].includes(String(item.avoid_direction)) ||
        ![true, false, "unknown"].includes(item.approaching as string | boolean) ||
        !(typeof item.target_id === "string" && shortString(item.target_id, 128) ||
          typeof item.target_id === "number" && Number.isSafeInteger(item.target_id)) ||
        !Array.isArray(item.evidence) || item.evidence.length > 20 ||
        !item.evidence.every((x: unknown) => shortString(x, 128)) ||
        !(item.video_timestamp_ms === undefined || item.video_timestamp_ms === null ||
          typeof item.video_timestamp_ms === "number" && Number.isFinite(item.video_timestamp_ms) && item.video_timestamp_ms >= 0)) {
      throw new Error("Invalid phone event");
    }
    return item as PhoneEvent;
  });
}

export class EventStore {
  private readonly events = new Map<string, StoredEvent>();
  private pending: Promise<unknown> = Promise.resolve();
  readonly path: string;
  constructor(path: string) { this.path = path; }

  async load(): Promise<void> {
    let data: string;
    try { data = await readFile(this.path, "utf8"); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
      throw error;
    }
    for (const line of data.split("\n")) {
      if (!line.trim()) continue;
      const item = JSON.parse(line) as StoredEvent;
      this.events.set(item.event_id, item);
    }
  }

  async add(batch: PhoneEvent[], now = Date.now()): Promise<StoredEvent[]> {
    const task = this.pending.then(async () => {
      const fresh: StoredEvent[] = [];
      for (const event of batch) {
        if (this.events.has(event.event_id) || fresh.some(x => x.event_id === event.event_id)) continue;
        fresh.push({ ...event, received_at_ms: now });
      }
      if (fresh.length) {
        await mkdir(dirname(this.path), { recursive: true });
        await appendFile(this.path, fresh.map(x => JSON.stringify(x)).join("\n") + "\n", "utf8");
        for (const event of fresh) this.events.set(event.event_id, event);
      }
      return fresh;
    });
    this.pending = task.catch(() => undefined);
    return task;
  }

  latestSessionEvents(): WarningEvent[] {
    const all = [...this.events.values()];
    if (!all.length) return [];
    const latest = all.reduce((a, b) => b.observed_at_ms > a.observed_at_ms ? b : a);
    return all.filter(x => x.session_id === latest.session_id)
      .sort((a, b) => a.observed_at_ms - b.observed_at_ms || a.frame_id - b.frame_id)
      .map(x => ({ id: x.event_id, sessionId: x.session_id, frameId: x.frame_id,
        videoTimestampMs: x.video_timestamp_ms ?? 0, observedAtMs: x.observed_at_ms,
        receivedAtMs: x.received_at_ms, text: x.warning_text, targetId: x.target_id,
        type: x.type, direction: x.direction, evidence: x.evidence,
        approaching: x.approaching, avoidDirection: x.avoid_direction }));
  }
}
