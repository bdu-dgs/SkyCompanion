import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Store } from './store.ts';
import { createAPI } from './http.ts';
const now = Date.UTC(2026, 8, 27, 12);
function setup(t: { after: (callback: () => void) => void }) {
  const dir = mkdtempSync(join(tmpdir(), 'sky-preferences-test-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const path = join(dir, 'state.json');
  return { path, store: new Store(path, 'Test Assistant', () => now) };
}
test('combined iMessage preferences work before any trip and persist with delivery deduplication', t => {
  const { path, store } = setup(t);
  store.inbound('1', 'Please say less, mute trees and poles, repeat every 30 seconds');
  const p = store.preferences();
  assert.equal(p.verbosity, 'minimal'); assert.deepEqual(p.muted_categories, ['pole', 'tree']);
  assert.equal(p.repeat_interval_seconds, 30); assert.equal(p.revision, 1); assert.equal(p.applied_revision, null);
  assert.match(store.messages().messages.at(-1)!.text, /waiting for the phone/);
  const reloaded = new Store(path, 'Test Assistant', () => now);
  reloaded.inbound('1', 'Please say less, mute trees and poles, repeat every 30 seconds');
  assert.deepEqual(reloaded.preferences(), p); assert.equal(reloaded.messages().messages.length, 1);
  reloaded.inbound('2', 'enable trees and say more');
  assert.deepEqual(reloaded.preferences().muted_categories, ['pole']); assert.equal(reloaded.preferences().verbosity, 'detailed');
  assert.equal(reloaded.preferences().revision, 2);
});
test('English aliases combine, retain English replies, and reset is versioned', t => {
  const { store } = setup(t);
  store.inbound('1', 'Please say less, mute trees and poles, repeat every 30 seconds');
  assert.equal(store.preferences().verbosity, 'minimal'); assert.deepEqual(store.preferences().muted_categories, ['pole', 'tree']);
  assert.equal(store.preferences().repeat_interval_seconds, 30);
  store.inbound('2', 'enable trees, say more');
  assert.equal(store.preferences().verbosity, 'detailed'); assert.deepEqual(store.preferences().muted_categories, ['pole']);
  store.inbound('3', 'my preferences');
  assert.match(store.messages().messages.at(-1)!.text, /Alert detail: detailed/);
  store.inbound('4', 'reset preferences');
  assert.equal(store.preferences().revision, 3); assert.deepEqual(store.preferences().muted_categories, []);
  assert.equal(store.preferences().repeat_interval_seconds, 8);
  for (const message of store.messages().messages) assert.doesNotMatch(message.text, /\p{Script=Han}/u);
});
test('partial, ambiguous, conditional, and dangerous commands make no changes', t => {
  const { store } = setup(t);
  for (const [i, question] of ['say less, mute dogs', 'say more, repeat every 2 seconds', 'mute trees only on Tuesdays', 'mute and enable trees', 'mute urgent collision alerts', 'disable all alerts', 'say less, unexpected text'].entries()) {
    store.inbound(String(i), question);
    assert.equal(store.preferences().revision, 0, question);
    assert.match(store.messages().messages.at(-1)!.text, /No preferences changed/);
  }
});
test('changed preferences await a new phone acknowledgement; stale and duplicate acknowledgements cannot roll back', t => {
  const { path, store } = setup(t);
  store.inbound('1', 'say less');
  assert.throws(() => store.preferencesApplied({ revision: 2 }), /unknown preference revision/);
  assert.throws(() => store.preferencesApplied({ revision: '1' }), /Invalid preference revision/);
  store.preferencesApplied({ revision: 1 });
  store.inbound('2', 'my preferences');
  assert.match(store.messages().messages.at(-1)!.text, /phone confirmed revision 1 applied/);
  store.inbound('3', 'say more');
  store.preferencesApplied({ revision: 0 });
  assert.equal(store.preferences().applied_revision, 1);
  store.inbound('4', 'my preferences');
  assert.match(store.messages().messages.at(-1)!.text, /waiting for the phone/);
  assert.equal(new Store(path).preferences().applied_revision, 1);
});
test('legacy state receives defaults and malformed saved preferences are rejected', t => {
  const { path } = setup(t);
  const old = { version: 1, records: [], messages: [], outbox: [], inbound_ids: [] };
  writeFileSync(path, JSON.stringify(old));
  const store = new Store(path);
  assert.equal(store.preferences().repeat_interval_seconds, 8);
  writeFileSync(path, JSON.stringify({ ...old, preferences: { ...store.preferences(), urgent_alerts_enabled: false } }));
  assert.throws(() => new Store(path), /Invalid saved preferences/);
});
test('preference updates in an invalid record batch are rolled back atomically', t => {
  const { store } = setup(t);
  const start = { id: 's', session_id: 'trip', at_ms: now, kind: 'start', source: 'video', locale: 'en' };
  store.sync([start]);
  assert.throws(() => store.sync([
    { id: 'q', session_id: 'trip', at_ms: now, kind: 'query', question: 'say less' },
    { ...start, id: 'second-start' },
  ]), /already started/);
  assert.equal(store.preferences().revision, 0); assert.equal(store.messages().messages.length, 0);
});
test('preference read and apply endpoints require bearer auth and validate revision', async t => {
  const { store } = setup(t);
  const token = 'test-only-preferences-token-12345';
  const server = createAPI(store, token);
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const base = `http://127.0.0.1:${address.port}`;
  const headers = { authorization: `Bearer ${token}`, 'content-type': 'application/json' };
  assert.equal((await fetch(`${base}/v1/preferences`)).status, 401);
  assert.equal((await fetch(`${base}/v1/preferences/applied`, { method: 'POST', body: '{}' })).status, 401);
  store.inbound('1', 'mute trees');
  const response = await fetch(`${base}/v1/preferences`, { headers });
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal((await response.json() as {revision: number}).revision, 1);
  assert.equal((await fetch(`${base}/v1/preferences/applied`, { method: 'POST', headers, body: '{"revision":2}' })).status, 409);
  const applied = await fetch(`${base}/v1/preferences/applied`, { method: 'POST', headers, body: '{"revision":1}' });
  assert.equal(applied.status, 200);
  assert.equal((await applied.json() as {applied_revision: number}).applied_revision, 1);
});
test('common conversational examples personalize detail and category filters without interpreting unknown tails', t => {
  const { store } = setup(t);
  for (const [i, question] of ["Don't mention trees", 'stop mentioning poles', 'I want fewer warnings', 'be more detailed', 'say a little less', 'say a little more', 'from now on say less'].entries()) {
    store.inbound(`natural-${i}`, question);
    assert.doesNotMatch(store.messages().messages.at(-1)!.text, /could not understand|No preferences changed/, question);
  }
  assert.deepEqual(store.preferences().muted_categories, ['pole', 'tree']);
  assert.equal(store.preferences().verbosity, 'minimal');
  store.inbound('combo', 'Please be more detailed and mute bicycles');
  assert.equal(store.preferences().verbosity, 'detailed');
  assert.deepEqual(store.preferences().muted_categories, ['bicycle', 'pole', 'tree']);
  const revision = store.preferences().revision;
  store.inbound('conditional', "Don't mention trees if the weather is good");
  assert.equal(store.preferences().revision, revision);
  assert.match(store.messages().messages.at(-1)!.text, /No preferences changed/);
  store.inbound('query', 'show my preferences');
  assert.match(store.messages().messages.at(-1)!.text, /Alert detail: detailed/);
});
test('interval replies describe minimum new-alert spacing rather than periodic obstacle playback', t => {
  const { store } = setup(t);
  store.inbound('interval', 'alert interval 30 seconds');
  assert.equal(store.preferences().repeat_interval_seconds, 30);
  assert.match(store.messages().messages.at(-1)!.text, /Minimum interval between ordinary new alerts: 30 seconds/);
  assert.match(store.messages().messages.at(-1)!.text, /Unchanged obstacles are not repeated on a timer/);
  store.inbound('alias', 'repeat every 40 seconds');
  assert.equal(store.preferences().repeat_interval_seconds, 40);
  assert.match(store.messages().messages.at(-1)!.text, /Minimum interval between ordinary new alerts: 40 seconds/);
});
