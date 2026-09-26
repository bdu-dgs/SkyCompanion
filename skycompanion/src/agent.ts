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
function typeLabel(type: string, zh: boolean): string {
  return zh ? ({ person: "行人", bicycle: "自行车", car: "汽车", motorcycle: "摩托车", bus: "公交车", truck: "卡车" } as Record<string, string>)[type] ?? "障碍物" : type;
}
function directionLabel(direction: string, zh: boolean): string {
  return zh ? ({ left: "左侧", center: "前方", right: "右侧" } as Record<string, string>)[direction] ?? "位置不确定" : direction === "center" ? "ahead" : direction;
}
function eventLine(event: WarningEvent, zh: boolean): string {
  const label = `${zh ? "视频" : "video"} ${timeLabel(event.videoTimestampMs)} (frame ${event.frameId})`;
  return zh ? `${label}：${directionLabel(event.direction, true)}${typeLabel(event.type, true)}；提示“${event.text}”` :
    `${label}: ${typeLabel(event.type, false)} ${directionLabel(event.direction, false)}; "${event.text}"`;
}
function reasonLine(event: WarningEvent, zh: boolean): string {
  const facts: string[] = [];
  if (event.evidence.includes("bbox_footpoint_in_configured_corridor")) facts.push(zh ? "目标落在配置的行走区域内" : "target inside the configured walking corridor");
  if (event.evidence.some((item) => item.startsWith("relative_image_region_"))) facts.push(zh ? "目标位于画面中的较近区域" : "target in a nearer image region");
  if (event.evidence.some((item) => item.startsWith("consecutive_track_frames_"))) facts.push(zh ? "连续帧跟踪确认" : "confirmed across tracked frames");
  if (event.approaching === "unknown") facts.push(zh ? "是否正在接近无法确认" : "approach could not be confirmed");
  if (event.avoidDirection === "unknown") facts.push(zh ? "没有证据确认可安全绕行的方向" : "no safe avoidance direction was verified");
  return zh ? `依据：${facts.join("；") || "记录中没有更详细的判断依据"}。` :
    `Evidence: ${facts.join("; ") || "no further evidence in the record"}.`;
}

export function answerQuestion(question: string, events: WarningEvent[] | null): string {
  const q = question.trim().toLowerCase();
  const zh = /[\u3400-\u9fff]/u.test(question);
  if (/^(help|帮助|菜单|功能|commands?)$/u.test(q)) return zh ?
    "可问：刚才发生了什么？为什么提醒？本次汇报？也可问行人或汽车提醒。" :
    "Ask: What happened? Why did you warn me? Trip summary? You can also ask about pedestrian or car warnings.";
  if (!events) return zh ? "还没有找到本次运行的事件记录。请先运行 SkyCompanion 视频分析。" :
    "No current session log found. Run SkyCompanion video analysis first.";
  if (!events.length) return zh ? "本次记录中没有触发语音提醒的事件。" :
    "No spoken warning events were recorded in this session.";

  const filter = /行人|pedestrian|person/u.test(q) ? "person" : /自行车|bicycle|bike/u.test(q) ? "bicycle" : /汽车|car/u.test(q) ? "car" : null;
  const matches = filter ? events.filter((event) => event.type === filter) : events;
  if (!matches.length) return zh ? `本次记录中没有${typeLabel(filter ?? "unknown", true)}提醒。` :
    `No ${filter} warning was recorded in this session.`;
  const last = matches.at(-1)!;
  if (/为什么|原因|依据|why|reason|evidence/u.test(q)) return `${eventLine(last, zh)}\n${reasonLine(last, zh)}`;
  if (/汇报|总结|统计|summary|report|how many|多少|几次|count/u.test(q)) {
    const counts = new Map<string, number>();
    for (const event of matches) counts.set(event.type, (counts.get(event.type) ?? 0) + 1);
    const detail = [...counts].map(([kind, count]) => `${typeLabel(kind, zh)} ${count}`).join(zh ? "，" : ", ");
    return zh ? `本次记录有 ${matches.length} 次提醒（${detail}）。最近一次：${eventLine(last, true)}。计数是播报次数，不代表独立目标数。` :
      `${matches.length} warnings recorded (${detail}). Latest: ${eventLine(last, false)}. These count spoken warnings, not distinct objects.`;
  }
  if (/刚才|最近|发生|什么|哪|last|recent|happen|what|when/u.test(q)) return zh ?
    `最近一次提醒：${eventLine(last, true)}。` : `Latest warning: ${eventLine(last, false)}.`;
  return zh ? "我只能根据已记录的提醒回答。可问：刚才发生了什么？为什么提醒？本次汇报？" :
    "I can answer from recorded warnings. Ask: What happened? Why did you warn me? Trip summary?";
}
