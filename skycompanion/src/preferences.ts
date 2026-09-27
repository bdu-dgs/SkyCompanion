import { InputError } from './records.ts';

export const preferenceCategories = ['tree', 'pole', 'person', 'vehicle', 'bicycle', 'stairs', 'curb', 'obstacle'] as const;
export type PreferenceCategory = typeof preferenceCategories[number];
export type Preferences = {
  schema_version: 1;
  revision: number;
  verbosity: 'minimal' | 'standard' | 'detailed';
  muted_categories: PreferenceCategory[];
  repeat_interval_seconds: number;
  urgent_alerts_enabled: true;
  updated_at_ms: number;
  applied_revision: number | null;
  applied_at_ms: number | null;
};
export const defaultPreferences = (): Preferences => ({ schema_version: 1, revision: 0, verbosity: 'standard', muted_categories: [], repeat_interval_seconds: 8, urgent_alerts_enabled: true, updated_at_ms: 0, applied_revision: null, applied_at_ms: null });
export function validatePreferences(value: unknown): Preferences {
  if (!value || typeof value !== 'object') throw new Error('Invalid saved preferences');
  const p = value as Preferences;
  if (p.schema_version !== 1 || !Number.isSafeInteger(p.revision) || p.revision < 0 || !['minimal', 'standard', 'detailed'].includes(p.verbosity) || !Array.isArray(p.muted_categories) || p.muted_categories.some(c => !preferenceCategories.includes(c)) || new Set(p.muted_categories).size !== p.muted_categories.length || !Number.isInteger(p.repeat_interval_seconds) || p.repeat_interval_seconds < 8 || p.repeat_interval_seconds > 120 || p.urgent_alerts_enabled !== true || !Number.isSafeInteger(p.updated_at_ms) || p.updated_at_ms < 0 || (p.applied_revision !== null && (!Number.isSafeInteger(p.applied_revision) || p.applied_revision < 0 || p.applied_revision > p.revision)) || (p.applied_at_ms !== null && (!Number.isSafeInteger(p.applied_at_ms) || p.applied_at_ms < 0)) || (p.applied_revision === null) !== (p.applied_at_ms === null)) throw new Error('Invalid saved preferences');
  return structuredClone(p);
}
const safety = 'Immediate action and urgent collision alerts stay enabled; category filters apply only to ordinary attention reminders.';
export const preferenceHelp = 'Personalize alerts with "say less", "say more", "normal detail", "mute trees", "enable trees", or "alert interval 30 seconds" (8–120 seconds). Combine requests with commas. Ask "my preferences" or "reset preferences". Supported categories: tree, pole, person, vehicle, bicycle, stairs, curb, obstacle.';
export function describePreferences(p: Preferences): string {
  const status = p.applied_revision === p.revision ? `The phone confirmed revision ${p.revision} applied${p.applied_at_ms ? ` at ${new Date(p.applied_at_ms).toISOString()}` : ''}.` : `Saved revision ${p.revision}; waiting for the phone to sync and confirm application.`;
  return `Alert detail: ${p.verbosity}. Muted ordinary categories: ${p.muted_categories.join(', ') || 'none'}. Minimum interval between ordinary new alerts: ${p.repeat_interval_seconds} seconds. Unchanged obstacles are not repeated on a timer. ${safety} ${status}`;
}
const aliases: [PreferenceCategory, RegExp][] = [
  ['tree', /\btrees?\b/g], ['pole', /\bpoles?\b/g],
  ['person', /\b(?:people|persons?|pedestrians?)\b/g], ['vehicle', /\b(?:vehicles?|cars?|traffic)\b/g],
  ['bicycle', /\b(?:bicycles?|bikes?)\b/g], ['stairs', /\b(?:stairs?|steps?)\b/g],
  ['curb', /\bcurbs?\b/g], ['obstacle', /\bobstacles?\b/g],
];
type Parsed = { kind: 'unrelated' } | { kind: 'reply'; text: string } | { kind: 'change'; preferences: Preferences; text: string };
/** Deliberately bounded English commands: an unknown clause rejects the whole update. */
export function personalize(question: string, current: Preferences, now: number): Parsed {
  const q = question.toLowerCase().trim().replace(/[.!?]+$/g, '').replace(/[’‘]/g, "'");
  if (/^(?:(?:show|what are|tell me) )?(?:my |alert )?(?:preferences|settings)$/.test(q)) return { kind: 'reply', text: describePreferences(current) };
  if (/^(?:preferences?|personaliz(?:e|ation))(?: help)?$/.test(q)) return { kind: 'reply', text: preferenceHelp };
  if (/^reset (?:my |alert )?(?:preferences|settings)$/.test(q)) {
    const preferences = { ...defaultPreferences(), revision: current.revision + 1, updated_at_ms: now, applied_revision: current.applied_revision, applied_at_ms: current.applied_at_ms };
    return { kind: 'change', preferences, text: `Defaults restored. ${describePreferences(preferences)}` };
  }
  const related = /\b(?:say|speak|talk|verbosity|detail|more|less|mute|unmute|enable|disable|ignore|repeat|preferences|personalize|remind|mention|mentioning|fewer|detailed|interval)\b/.test(q);
  if (!related) return { kind: 'unrelated' };
  if (/(?:urgent|collision|emergenc|danger|all (?:alerts|warnings)|everything)/.test(q)) return { kind: 'reply', text: `No preferences changed. ${safety} ${preferenceHelp}` };
  const next = structuredClone(current);
  // Split only at clear new commands; category lists such as "trees and poles" stay together.
  const clauses = q.split(/[,;]|\s+(?:and|but|then)\s+(?=(?:please\s+)?(?:say|speak|talk|mute|unmute|enable|disable|ignore|don't|do not|stop|repeat|alert|minimum|normal|standard|more|less|be|i want)\b)/).map(s => s.trim()).filter(Boolean);
  let recognized = 0;
  for (let clause of clauses) {
    clause = clause.replace(/^(?:(?:please|from now on|i want|i would like|could you|can you)\s+)+/g, '').trim();
    if (/^(?:(?:(?:say|speak|talk) (?:a (?:little|bit) )?less|less)|(?:be |keep it )?(?:brief|concise)|(?:minimal|less) (?:detail|verbose)|fewer (?:warnings|alerts|reminders))$/.test(clause)) { next.verbosity = 'minimal'; recognized++; continue; }
    if (/^(?:(?:(?:say|speak|talk) (?:a (?:little|bit) )?more|more)|(?:more|detailed) (?:detail|alerts?)|(?:be )?more detailed)$/.test(clause)) { next.verbosity = 'detailed'; recognized++; continue; }
    if (/^(?:normal detail|standard detail|normal verbosity)$/.test(clause)) { next.verbosity = 'standard'; recognized++; continue; }
    const repeat = /^(?:repeat(?: alerts)? every |(?:set )?(?:(?:minimum )?alert|repeat)(?: interval)?(?: to|:)? )([0-9]+)\s*(?:seconds?|s)$/.exec(clause);
    if (repeat) {
      const seconds = Number(repeat[1]);
      if (seconds < 8 || seconds > 120) return { kind: 'reply', text: 'No preferences changed. Choose a minimum interval between ordinary new alerts of 8–120 seconds. Unchanged obstacles are not repeated on a timer. Immediate action and urgent alerts bypass this preference.' };
      next.repeat_interval_seconds = seconds; recognized++; continue;
    }
    const disable = /\b(?:mute|disable|ignore|stop)\b|don't|do not/.test(clause);
    const enable = /\b(?:unmute|enable|restore)\b/.test(clause);
    if (disable === enable) return { kind: 'reply', text: `No preferences changed. I could not understand the complete request. ${preferenceHelp}` };
    const categories: PreferenceCategory[] = [];
    let remainder = clause;
    // Consume complete category aliases before checking for unrecognized words.
    for (const [category, pattern] of aliases) {
      pattern.lastIndex = 0;
      if (pattern.test(remainder)) { categories.push(category); pattern.lastIndex = 0; remainder = remainder.replace(pattern, ' '); }
    }
    remainder = remainder.replace(/\b(?:mute|unmute|disable|enable|ignore|restore|stop|please|ordinary|normal|attention|alerts?|warnings?|reminders?|reminding|mention|mentioning|telling|me|about|for|and|or|the|of|on|off)\b|don't|do not|\s/g, '');
    if (!categories.length || remainder) return { kind: 'reply', text: `No preferences changed. I could not understand the complete category request. ${preferenceHelp}` };
    for (const category of categories) next.muted_categories = disable ? [...new Set([...next.muted_categories, category])] : next.muted_categories.filter(c => c !== category);
    recognized++;
  }
  if (!recognized) return { kind: 'reply', text: preferenceHelp };
  next.muted_categories.sort();
  const same = next.verbosity === current.verbosity && next.repeat_interval_seconds === current.repeat_interval_seconds && JSON.stringify(next.muted_categories) === JSON.stringify([...current.muted_categories].sort());
  if (same) return { kind: 'reply', text: `Those preferences are already saved. ${describePreferences(current)}` };
  next.revision++; next.updated_at_ms = now;
  return { kind: 'change', preferences: next, text: describePreferences(next) };
}
export function acknowledgePreferences(current: Preferences, value: unknown, now: number): Preferences {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new InputError('Expected { revision: integer }');
  const revision = (value as {revision?: unknown}).revision;
  if (typeof revision !== 'number' || !Number.isSafeInteger(revision) || revision < 0) throw new InputError('Invalid preference revision');
  if (revision > current.revision) throw new InputError('Cannot acknowledge an unknown preference revision', 409);
  if (current.applied_revision !== null && revision <= current.applied_revision) return structuredClone(current);
  return { ...structuredClone(current), applied_revision: revision, applied_at_ms: now };
}
