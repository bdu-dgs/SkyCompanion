import { mkdirSync, readFileSync, writeFileSync, renameSync, existsSync } from 'node:fs';
import { dirname } from 'node:path';
import { randomUUID } from 'node:crypto';
import { alertsFor, answer, englishExcerpt, parseCorrection, summary } from './agent.ts';
import { InputError, parseRecord, type TripRecord } from './records.ts';
import { acknowledgePreferences, defaultPreferences, personalize, validatePreferences, type Preferences } from './preferences.ts';
export type InboxMessage = { id: string; sequence: number; session_id: string; kind: 'summary' | 'answer' | 'feedback'; text: string; created_at_ms: number };
export type OutboxItem = { message_id: string; status: 'pending' | 'sent' | 'failed'; attempts: number; next_attempt_ms: number };
type State = { version: 1; owner?: string; records: TripRecord[]; messages: InboxMessage[]; outbox: OutboxItem[]; inbound_ids: string[]; preferences?: Preferences };
const blank = (): State => ({ version: 1, records: [], messages: [], outbox: [], inbound_ids: [] });
export class Store {
  private state: State;
  constructor(private path: string, public agentName = 'SkyCompanion Assistant', private now = () => Date.now(), owner?: string) {
    this.state = existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) as State : blank();
    if (this.state.version !== 1 || !Array.isArray(this.state.records) || !Array.isArray(this.state.messages) || !Array.isArray(this.state.outbox) || !Array.isArray(this.state.inbound_ids)) throw new Error('Invalid agent state; restore a verified backup');
    this.state.preferences = this.state.preferences ? validatePreferences(this.state.preferences) : defaultPreferences();
    if (owner) {
      if ((this.state.owner && this.state.owner !== owner) || (!this.state.owner && (this.state.records.length || this.state.preferences.revision > 0))) throw new Error('Agent state belongs to a different or unbound account; use a new state path for a different user');
      this.state.owner = owner;
    }
  }
  private save(next: State): void {
    mkdirSync(dirname(this.path), { recursive: true, mode: 0o700 });
    const tmp = `${this.path}.${randomUUID()}.tmp`;
    writeFileSync(tmp, JSON.stringify(next), { mode: 0o600 });
    renameSync(tmp, this.path);
    this.state = next;
  }
  private message(state: State, session: string, kind: InboxMessage['kind'], text: string): void {
    const message = { id: randomUUID(), sequence: (state.messages.at(-1)?.sequence ?? 0) + 1, session_id: session, kind, text, created_at_ms: this.now() };
    state.messages.push(message);
    state.outbox.push({ message_id: message.id, status: 'pending', attempts: 0, next_attempt_ms: this.now() });
  }
  private feedback(state: State, record: Extract<TripRecord, {kind: 'feedback'}>): void {
    const event = alertsFor(state.records, record.session_id).find(r => r.event_id === record.event_id);
    if (!event) throw new InputError('Feedback must reference an alert in the same trip', 422);
    state.records.push(record);
    this.message(state, record.session_id, 'feedback', `Correction for event ${record.event_id} (${englishExcerpt(event.text, 'original alert retained in the trip record')}) saved as unreviewed: ${englishExcerpt(record.note, 'Your original-language correction has been saved for review')}. The model has not been updated.`);
  }
  private query(state: State, record: Extract<TripRecord, {kind: 'query'}>): void {
    const correction = parseCorrection(record.question);
    const preference = correction ? { kind: 'unrelated' as const } : personalize(record.question, state.preferences ?? defaultPreferences(), this.now());
    if (preference.kind !== 'unrelated') {
      if (preference.kind === 'change') state.preferences = preference.preferences;
      this.message(state, record.session_id, 'answer', preference.text);
      state.records.push(record);
      return;
    }
    if (correction) {
      const eventID = /^(latest|last)$/i.test(correction.target) ? alertsFor(state.records, record.session_id).at(-1)?.event_id : correction.target;
      if (!eventID) throw new InputError('No recorded alert to correct', 422);
      const feedback = parseRecord({ ...record, id: randomUUID(), kind: 'feedback', event_id: eventID, note: correction.note }, this.now());
      if (feedback.kind === 'feedback') this.feedback(state, feedback);
    } else this.message(state, record.session_id, 'answer', answer(state.records, record.session_id, record.question, this.agentName));
    state.records.push(record);
  }
  sync(values: unknown): { accepted: number; duplicates: number } {
    if (!Array.isArray(values) || values.length < 1 || values.length > 50) throw new InputError('Expected 1–50 records');
    const records = values.map(value => parseRecord(value, this.now()));
    const next = structuredClone(this.state);
    let accepted = 0, duplicates = 0;
    for (const record of records) {
      const previous = next.records.find(r => r.id === record.id);
      if (previous) {
        if (JSON.stringify(previous) !== JSON.stringify(record)) throw new InputError('Record ID reused with different content', 409);
        duplicates++; continue;
      }
      if (next.records.length >= 100000) throw new InputError('Record storage limit reached; archive state before resuming', 507);
      const session = next.records.filter(r => r.session_id === record.session_id);
      const start = session.find(r => r.kind === 'start');
      if (record.kind === 'start') {
        if (start) throw new InputError('Trip already started with another record ID', 409);
        next.records.push(record);
      } else {
        if (!start) throw new InputError('Trip start must precede its records', 422);
        if (record.at_ms < start.at_ms) throw new InputError('Record predates trip start', 422);
        if (record.kind === 'alert') {
          if (session.some(r => r.kind === 'end')) throw new InputError('Trip has ended; upload alerts before end', 409);
          if (alertsFor(next.records, record.session_id).some(r => r.event_id === record.event_id)) throw new InputError('Duplicate event ID with different record ID', 409);
          next.records.push(record);
        } else if (record.kind === 'end') {
          const ended = session.some(r => r.kind === 'end');
          next.records.push(record);
          if (!ended) this.message(next, record.session_id, 'summary', summary(next.records, record.session_id));
        } else if (record.kind === 'feedback') this.feedback(next, record);
        else this.query(next, record);
      }
      accepted++;
    }
    if (accepted) this.save(next);
    return { accepted, duplicates };
  }
  messages(after = 0): { messages: InboxMessage[]; cursor: number; agent_name: string } {
    const messages = this.state.messages.filter(m => m.sequence > after).slice(0, 100);
    return { messages, cursor: messages.at(-1)?.sequence ?? after, agent_name: this.agentName };
  }
  preferences(): Preferences { return structuredClone(this.state.preferences ?? defaultPreferences()); }
  preferencesApplied(value: unknown): Preferences {
    const next = structuredClone(this.state);
    next.preferences = acknowledgePreferences(this.preferences(), value, this.now());
    this.save(next);
    return this.preferences();
  }
  feedbackExport(): unknown[] {
    return this.state.records.filter(r => r.kind === 'feedback').map(r => ({ ...r, status: 'unreviewed', alert: alertsFor(this.state.records, r.session_id).find(a => r.kind === 'feedback' && a.event_id === r.event_id), source: this.state.records.find(s => s.session_id === r.session_id && s.kind === 'start') }));
  }
  inbound(id: string, question: string): void {
    if (this.state.inbound_ids.includes(id)) return;
    if (!id || id.length > 500 || question.length > 1000) return;
    if (this.state.records.length >= 100000 || this.state.inbound_ids.length >= 100000) throw new Error('Local storage limit reached');
    const next = structuredClone(this.state);
    const session = next.records.filter(r => r.kind === 'start').at(-1)?.session_id ?? 'inbox';
    try {
      this.query(next, { id: randomUUID(), session_id: session, at_ms: this.now(), kind: 'query', question });
    } catch (error) {
      if (!(error instanceof InputError)) throw error;
      this.message(next, session, 'answer', `Correction not saved: ${error.message}. Use "wrong <event_id>: description" or "wrong latest: description".`);
    }
    next.inbound_ids.push(id);
    this.save(next);
  }
  deliveryStatus(): { pending: number; sent: number; failed: number } {
    return { pending: this.state.outbox.filter(o => o.status === 'pending').length, sent: this.state.outbox.filter(o => o.status === 'sent').length, failed: this.state.outbox.filter(o => o.status === 'failed').length };
  }
  pending(): { item: OutboxItem; message: InboxMessage } | undefined {
    const item = this.state.outbox.find(o => o.status === 'pending' && o.next_attempt_ms <= this.now());
    const message = item && this.state.messages.find(m => m.id === item.message_id);
    return item && message ? { item: structuredClone(item), message } : undefined;
  }
  delivery(id: string, success: boolean): void {
    const next = structuredClone(this.state);
    const item = next.outbox.find(o => o.message_id === id);
    if (!item || item.status !== 'pending') return;
    item.attempts++;
    item.status = success ? 'sent' : item.attempts >= 5 ? 'failed' : 'pending';
    item.next_attempt_ms = this.now() + Math.min(300000, 5000 * 2 ** (item.attempts - 1));
    this.save(next);
  }
}
