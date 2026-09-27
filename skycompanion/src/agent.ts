import type { Alert, TripRecord } from './records.ts';
export const alertsFor = (records: TripRecord[], session: string): Alert[] => records.filter((r): r is Alert => r.session_id === session && r.kind === 'alert');
// Display only English in generated replies; retain original-language evidence in storage.
export function englishExcerpt(value: string, fallback: string): string {
  return /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u.test(value) ? fallback : value;
}
function sourceLabel(records: TripRecord[], session: string): string {
  const start = records.find(r => r.session_id === session && r.kind === 'start');
  return start?.kind === 'start' && start.source === 'video' ? 'Recorded demo' : 'Trip record';
}
export function summary(records: TripRecord[], session: string): string {
  const alerts = alertsFor(records, session);
  const date = records.find(r => r.session_id === session && r.kind === 'start')?.at_ms;
  const interrupted = records.some(r => r.session_id === session && r.kind === 'end' && /interrupt|restart|replac|incomplete/i.test(r.reason));
  const caveat = interrupted ? ': Trip interrupted; obstacle log may be incomplete' : '';
  const prefix = `${sourceLabel(records, session)}${date ? ` (${new Date(date).toISOString()})` : ''}${caveat}`;
  if (!alerts.length) return `${prefix}: No obstacle alerts were recorded; this does not mean there were no obstacles.`;
  const counts = new Map<string, number>();
  for (const alert of alerts) counts.set(alert.category, (counts.get(alert.category) ?? 0) + 1);
  const categories = [...counts].sort((a, b) => b[1] - a[1]);
  const top = categories.slice(0, 4).map(([category, count]) => `${englishExcerpt(category, "obstacle (original category saved)")} ×${count}`).join(', ');
  const corrected = new Set(records.filter(r => r.session_id === session && r.kind === 'feedback').map(r => r.kind === 'feedback' ? r.event_id : '')).size;
  return `${prefix}: ${alerts.length} recorded obstacle alerts (${top}${categories.length > 4 ? ', others' : ''}), not distinct physical obstacles.${corrected ? ` ${corrected} flagged for review.` : ''}`;
}
export function answer(records: TripRecord[], session: string, question: string, name: string): string {
  const q = question.toLowerCase();
  const help = `I'm ${englishExcerpt(name, 'SkyCompanion Assistant')}. Ask "summary", "recent", or "why". Report "wrong latest: what actually happened", or replace latest with an event ID. Personalize alerts with \"say less\", \"say more\", \"mute trees\", \"enable trees\", or \"alert interval 30 seconds\". Ask \"my preferences\" or \"reset preferences\". Feedback is saved for review, not immediate model training.`;
  if (/help/.test(q)) return help;
  if (/summary/.test(q)) return summary(records, session);
  if (/why|recent|last|happen/.test(q)) {
    const last = alertsFor(records, session).at(-1);
    if (!last) return 'No alerts are recorded.';
    const when = new Date(last.observed_at_ms).toISOString();
    const excerpt = (value: string, limit: number) => value.length > limit ? `${value.slice(0, limit)}…` : value;
    const alertText = excerpt(englishExcerpt(last.text, 'The original alert was recorded in another language and is retained in the trip record'), 500);
    const evidence = last.evidence.length ? last.evidence.slice(0, 3).map(value => excerpt(englishExcerpt(value, 'Original-language evidence retained in the trip record'), 160)).join('; ') + (last.evidence.length > 3 ? '; additional evidence omitted' : '') : 'no additional evidence recorded';
    return `Historical alert from ${sourceLabel(records, session).toLowerCase()} (${when}, event ${last.event_id}): ${alertText}. Category: ${englishExcerpt(last.category, 'obstacle (original category saved)')}. Direction ${last.direction} refers to the image frame, not current navigation. Recorded evidence: ${evidence}.`;
  }
  return help;
}
export function parseCorrection(question: string): { target: string; note: string } | null {
  const match = /^(?:wrong|feedback)\s+([^\s:]+)\s*[:]\s*(.+)$/is.exec(question.trim());
  return match?.[1] && match[2] ? { target: match[1], note: match[2] } : null;
}
