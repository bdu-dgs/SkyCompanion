import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Store } from './store.ts';
import { createAPI } from './http.ts';
import { flushOne, isAuthorizedInbound } from './transport.ts';
const now = Date.UTC(2026, 8, 26, 12);
const token = 'test-token-not-a-secret-123456789';
const start = { id: 's1', kind: 'start', session_id: 'trip1', at_ms: now - 10000, source: 'video', locale: 'en' };
const alert = { id: 'a1', kind: 'alert', session_id: 'trip1', at_ms: now - 8000, observed_at_ms: now - 9000, frame_id: 10, event_id: 'event1', category: 'pole', direction: 'left', text: 'Pole on the left', evidence: ['detector: pole'], speech_status: 'started' };
const end = { id: 'e1', kind: 'end', session_id: 'trip1', at_ms: now, reason: 'user_stop' };
function setup(t: { after: (callback: () => void) => void }) {
  const dir = mkdtempSync(join(tmpdir(), 'sky-agent-test-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const path = join(dir, 'state.json');
  return { store: new Store(path, 'Test Assistant', () => now), path };
}
test('trip batches are idempotent, atomically persistent, and create one logical summary', t => {
  const { store, path } = setup(t);
  assert.deepEqual(store.sync([start, alert, end]), { accepted: 3, duplicates: 0 });
  assert.deepEqual(store.sync([start, alert, end]), { accepted: 0, duplicates: 3 });
  store.sync([{ ...end, id: 'another-end-id' }]);
  const restarted = new Store(path, 'Test Assistant', () => now);
  assert.equal(restarted.messages().messages.length, 1);
  assert.match(restarted.messages().messages[0]!.text, /Recorded demo.*1 recorded obstacle alerts/);
  assert.match(restarted.messages().messages[0]!.text, /not distinct physical obstacles/);
  assert.equal(restarted.pending()?.message.kind, 'summary');
});
test('invalid batch commits no prefix; conflicts and post-end alerts fail', t => {
  const { store } = setup(t);
  assert.throws(() => store.sync([start, { ...alert, direction: 'north' }]), /Invalid alert/);
  assert.deepEqual(store.sync([start, alert]), { accepted: 2, duplicates: 0 });
  assert.throws(() => store.sync([{ ...alert, text: 'changed' }]), /reused/);
  assert.throws(() => store.sync([{ ...alert, id: 'same-event' }]), /Duplicate event/);
  store.sync([end]);
  assert.throws(() => store.sync([{ ...alert, id: 'late', event_id: 'late' }]), /ended/);
});
test('zero-alert summary never claims a clear or safe route', t => {
  const { store } = setup(t);
  store.sync([start, end]);
  assert.match(store.messages().messages[0]!.text, /No obstacle alerts were recorded; this does not mean/);
});
test('feedback must reference an actual event in its own trip; exports preserve evidence and unreviewed status', t => {
  const { store } = setup(t);
  store.sync([start, alert, { ...start, id: 's2', session_id: 'trip2' }]);
  const feedback = { id: 'f1', kind: 'feedback', session_id: 'trip2', at_ms: now, event_id: 'event1', note: 'Actually a tree' };
  assert.throws(() => store.sync([feedback]), /same trip/);
  assert.throws(() => store.sync([{ ...feedback, session_id: 'trip1', event_id: 'fake' }]), /same trip/);
  store.sync([{ ...feedback, session_id: 'trip1' }]);
  const exported = store.feedbackExport() as { status: string; alert: { frame_id: number }; note: string }[];
  assert.equal(exported[0]!.status, 'unreviewed');
  assert.equal(exported[0]!.alert.frame_id, 10);
  assert.equal(exported[0]!.note, 'Actually a tree');
  assert.match(store.messages().messages[0]!.text, /model has not been updated/);
});
test('queries use historical timestamps and camera directions rather than live navigation', t => {
  const { store } = setup(t);
  store.sync([start, alert, { id: 'q1', kind: 'query', session_id: 'trip1', at_ms: now, question: 'why?' }]);
  const answer = store.messages().messages[0]!.text;
  assert.match(answer, /Historical alert from recorded demo/);
  assert.match(answer, /2026-09-26T11:59:51.000Z/);
  assert.match(answer, /image frame, not current navigation/);
});
test('latest correction resolves to a concrete event and repeated inbound delivery does not duplicate it', t => {
  const { store, path } = setup(t);
  store.sync([start, alert]);
  store.inbound('photon-msg-1', 'wrong latest: Actually a tree');
  new Store(path, 'Test Assistant', () => now).inbound('photon-msg-1', 'wrong latest: Actually a tree');
  const reloaded = new Store(path);
  assert.equal(reloaded.feedbackExport().length, 1);
  assert.match(reloaded.messages().messages[0]!.text, /event event1/);
  store.inbound('photon-msg-2', 'wrong missing-event: mistake');
  assert.match(store.messages().messages.at(-1)!.text, /Correction not saved/);
});
test('inbound allowlist rejects unknown senders, missing identities, group chats, and echo messages', () => {
  const valid = { platform: 'imessage', direction: 'inbound', sender: { id: '+15551234567' }, spaceType: 'dm' };
  assert.equal(isAuthorizedInbound(valid, '+15551234567'), true);
  assert.equal(isAuthorizedInbound({ ...valid, sender: { id: '+15557654321' } }, '+15551234567'), false);
  assert.equal(isAuthorizedInbound({ ...valid, sender: undefined }, '+15551234567'), false);
  assert.equal(isAuthorizedInbound({ ...valid, spaceType: 'group' }, '+15551234567'), false);
  assert.equal(isAuthorizedInbound({ ...valid, direction: 'outbound' }, '+15551234567'), false);
  assert.equal(isAuthorizedInbound(valid, ''), false);
});
test('outbox retry state survives restart without losing the app inbox', async t => {
  const { store, path } = setup(t);
  store.sync([start, end]);
  await flushOne(store, async () => { throw new Error('simulated network failure'); });
  assert.equal(store.pending(), undefined);
  const later = new Store(path, 'Test Assistant', () => now + 6000);
  assert.equal(later.pending()?.item.attempts, 1);
  await flushOne(later, async () => {});
  assert.equal(new Store(path, 'Test Assistant', () => now + 999999).pending(), undefined);
  assert.equal(later.messages().messages.length, 1);
});
test('future and malformed timestamps and oversized records are rejected', t => {
  const { store } = setup(t);
  assert.throws(() => store.sync([{ ...start, at_ms: now + 999999 }]), /timestamp/);
  assert.throws(() => store.sync([{ ...start, at_ms: '2026-09-26' }]), /timestamp/);
  assert.throws(() => store.sync(Array(51).fill(start)), /1–50/);
});
test('HTTP requires authentication, validates pagination, and rejects invalid batch atomically', async t => {
  const { store } = setup(t);
  const server = createAPI(store, token);
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  const base = `http://127.0.0.1:${address.port}`;
  const headers = { authorization: `Bearer ${token}`, 'content-type': 'application/json' };
  assert.equal((await fetch(`${base}/v1/messages`)).status, 401);
  assert.equal((await fetch(`${base}/v1/feedback`)).status, 401);
  assert.equal((await fetch(`${base}/v1/sync`, { method: 'POST', body: '{}' })).status, 401);
  assert.equal((await fetch(`${base}/v1/messages?after=-1`, { headers })).status, 400);
  assert.equal((await fetch(`${base}/v1/sync`, { method: 'POST', headers, body: JSON.stringify({ records: [start, { ...alert, event_id: ' ' }] }) })).status, 400);
  const synced = await fetch(`${base}/v1/sync`, { method: 'POST', headers, body: JSON.stringify({ records: [start, alert, end] }) });
  assert.deepEqual(await synced.json(), { accepted: 3, duplicates: 0 });
  const inbox = await (await fetch(`${base}/v1/messages?after=0`, { headers })).json() as { messages: unknown[]; cursor: number; agent_name: string };
  assert.equal(inbox.messages.length, 1);
  assert.equal(inbox.cursor, 1);
  assert.equal(inbox.agent_name, 'Test Assistant');
  const next = await (await fetch(`${base}/v1/messages?after=1`, { headers })).json() as { messages: unknown[] };
  assert.equal(next.messages.length, 0);
});
test('persisted history cannot be rebound to another recipient', t => {
  const { path } = setup(t);
  const bound = new Store(path, 'Test Assistant', () => now, '+15551234567');
  bound.sync([start, end]);
  assert.throws(() => new Store(path, 'Test Assistant', () => now, '+15557654321'), /different or unbound account/);
  assert.equal(new Store(path, 'Test Assistant', () => now, '+15551234567').messages().messages.length, 1);
});
test('failed outbox attempts are bounded and retain inbox and failure status', t => {
  const { path } = setup(t);
  let time = now;
  let store = new Store(path, 'Test Assistant', () => time);
  store.sync([start, end]);
  for (let attempt = 0; attempt < 5; attempt++) {
    const pending = store.pending();
    assert.ok(pending);
    store.delivery(pending.message.id, false);
    time += 300001;
    store = new Store(path, 'Test Assistant', () => time);
  }
  assert.equal(store.pending(), undefined);
  assert.deepEqual(store.deliveryStatus(), { pending: 0, sent: 0, failed: 1 });
  assert.equal(store.messages().messages.length, 1);
});
test('inbox pagination returns stable cursor and does not skip later pages', t => {
  const { store } = setup(t);
  store.sync([start]);
  for (let i = 0; i < 105; i++) store.inbound(`question-${i}`, 'help');
  const first = store.messages(0);
  assert.equal(first.messages.length, 100);
  assert.equal(first.cursor, 100);
  const second = store.messages(first.cursor);
  assert.equal(second.messages.length, 5);
  assert.equal(second.cursor, 105);
  assert.equal(store.messages(second.cursor).messages.length, 0);
});
test('interrupted and replaced trips explicitly identify incomplete records without echoing reason as guidance', t => {
  const { store } = setup(t);
  store.sync([start, alert, { ...end, reason: 'App restarted before the trip closed. This trip was interrupted; its obstacle log may be incomplete.' }]);
  assert.match(store.messages().messages[0]!.text, /Trip interrupted; obstacle log may be incomplete/);
  store.sync([{ ...start, id: 's2', session_id: 'trip2', locale: 'en' }, { ...end, id: 'e2', session_id: 'trip2', reason: 'A new trip replaced the previous trip; its log may be incomplete. Turn left now.' }]);
  const second = store.messages().messages[1]!.text;
  assert.match(second, /Trip interrupted; obstacle log may be incomplete/);
  assert.match(second, /No obstacle alerts were recorded/);
  assert.doesNotMatch(second, /Turn left/);
});
test('why replies remain concise with maximum-size input while retaining time and navigation caveat', t => {
  const { store } = setup(t);
  store.sync([start, { ...alert, text: 'A'.repeat(1000), evidence: Array.from({ length: 16 }, (_, i) => `${i}:` + 'B'.repeat(290)), event_id: 'e'.repeat(160) }, { id: 'q1', kind: 'query', session_id: 'trip1', at_ms: now, question: 'why' }]);
  const text = store.messages().messages[0]!.text;
  assert.ok(text.length < 2000);
  assert.match(text, /additional evidence omitted/);
  assert.match(text, /not current navigation/);
  assert.match(text, /2026-09-26T11:59:51.000Z/);
});
test('English commands preserve original evidence and produce English replies', t => {
  const { store } = setup(t);
  store.sync([{ ...start, locale: 'en' }, { ...alert, text: 'A utility pole is on the left', category: 'utility pole', evidence: ['left side of the image'] }, end]);
  store.inbound('why-en', 'why');
  store.inbound('help-en', 'help');
  store.inbound('feedback-en', 'wrong latest: it was a tree');
  for (const message of store.messages().messages) assert.doesNotMatch(message.text, /\p{Script=Han}/u);
  assert.match(store.messages().messages[0]!.text, /Recorded demo/);
  assert.match(store.messages().messages[1]!.text, /Historical alert/);
  assert.match(store.messages().messages[3]!.text, /saved as unreviewed/);
  const feedback = store.feedbackExport() as { note: string; alert: { text: string } }[];
  assert.equal(feedback[0]!.note, 'it was a tree');
  assert.equal(feedback[0]!.alert.text, 'A utility pole is on the left');
});
