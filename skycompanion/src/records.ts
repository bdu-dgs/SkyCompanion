export type Common = { id: string; session_id: string; at_ms: number };
export type TripRecord = Common & (
  | { kind: 'start'; source: 'drone' | 'video'; locale: 'en' | 'zh' }
  | { kind: 'alert'; frame_id: number; event_id: string; category: string; direction: 'left' | 'center' | 'right' | 'unknown'; text: string; evidence: string[]; observed_at_ms: number; speech_status: 'started' }
  | { kind: 'end'; reason: string }
  | { kind: 'feedback'; event_id: string; note: string }
  | { kind: 'query'; question: string }
);
export type Alert = Extract<TripRecord, { kind: 'alert' }>;
export class InputError extends Error { constructor(message: string, public status = 400) { super(message); } }
const string = (x: unknown, max: number, label: string): string => {
  if (typeof x !== 'string' || !x.trim() || x.length > max || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(x)) throw new InputError(`Invalid ${label}`);
  return x.trim();
};
const id = (x: unknown, label: string): string => {
  const result = string(x, 160, label);
  if (!/^[A-Za-z0-9_.:-]+$/.test(result)) throw new InputError(`Invalid ${label}`);
  return result;
};
const timestamp = (x: unknown, now: number): number => {
  if (typeof x !== 'number' || !Number.isSafeInteger(x) || x < 946684800000 || x > now + 300000) throw new InputError('Invalid UTC millisecond timestamp');
  return x;
};
export function parseRecord(value: unknown, now = Date.now()): TripRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new InputError('Invalid record');
  const v = value as Record<string, unknown>;
  const common = { id: id(v.id, 'id'), session_id: id(v.session_id, 'session_id'), at_ms: timestamp(v.at_ms, now) };
  switch (v.kind) {
    case 'start':
      if (!['drone', 'video'].includes(String(v.source)) || !['en', 'zh'].includes(String(v.locale))) throw new InputError('Invalid source or locale');
      return { ...common, kind: 'start', source: v.source as 'drone' | 'video', locale: v.locale as 'en' | 'zh' };
    case 'alert':
      if (typeof v.frame_id !== 'number' || !Number.isSafeInteger(v.frame_id) || v.frame_id < 0 || !['left', 'center', 'right', 'unknown'].includes(String(v.direction)) || v.speech_status !== 'started') throw new InputError('Invalid alert metadata');
      if (!Array.isArray(v.evidence) || v.evidence.length > 16) throw new InputError('Invalid evidence');
      return { ...common, kind: 'alert', frame_id: v.frame_id, event_id: id(v.event_id, 'event_id'), category: string(v.category, 100, 'category'), direction: v.direction as Alert['direction'], text: string(v.text, 1000, 'text'), evidence: v.evidence.map(x => string(x, 300, 'evidence')), observed_at_ms: timestamp(v.observed_at_ms, now), speech_status: 'started' };
    case 'end': return { ...common, kind: 'end', reason: string(v.reason, 500, 'reason') };
    case 'feedback': return { ...common, kind: 'feedback', event_id: id(v.event_id, 'event_id'), note: string(v.note, 1000, 'note') };
    case 'query': return { ...common, kind: 'query', question: string(v.question, 1000, 'question') };
    default: throw new InputError('Unknown record kind');
  }
}
