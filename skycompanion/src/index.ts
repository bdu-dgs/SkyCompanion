import { Spectrum } from 'spectrum-ts';
import { imessage } from '@spectrum-ts/imessage';
import { resolve } from 'node:path';
import { Store } from './store.ts';
import { createAPI } from './http.ts';
import { flushOne, isAuthorizedInbound, normalizePhone } from './transport.ts';

const required = ['PROJECT_ID', 'PROJECT_SECRET', 'SKY_INGEST_TOKEN', 'SKY_REPORT_TO_PHONE'] as const;
const missing = required.filter(key => !process.env[key]?.trim());
if (missing.length) throw new Error(`Missing configuration: ${missing.join(', ')}. Set these in .env; never share secrets in chat.`);
const recipient = normalizePhone(process.env.SKY_REPORT_TO_PHONE!);
if (!recipient) throw new Error('SKY_REPORT_TO_PHONE must be one authorized recipient in international +countrycode format');
const name = process.env.SKY_AGENT_NAME?.trim() || 'SkyCompanion Assistant';
if (name.length > 80) throw new Error('SKY_AGENT_NAME must be at most 80 characters');
const port = Number(process.env.SKY_PORT || '8787');
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid SKY_PORT');
const store = new Store(resolve(process.env.SKY_STATE_PATH || 'data/agent-state.json'), name, () => Date.now(), recipient);
const server = createAPI(store, process.env.SKY_INGEST_TOKEN!);
// Start the local inbox independently of Photon availability. A temporary cloud failure
// must not prevent the app from storing a trip, receiving its summary, or continuing alerts.
await new Promise<void>((ready, reject) => {
  server.once('error', reject);
  server.listen(port, '127.0.0.1', ready);
});
console.info(`${name}: local API listening on 127.0.0.1:${port}. iMessage delivery is separate from inbox storage.`);

let stopped = false;
let activeApp: Awaited<ReturnType<typeof Spectrum>> | undefined;
let timer: ReturnType<typeof setInterval> | undefined;
function shutdown(): void {
  stopped = true;
  if (timer) clearInterval(timer);
  server.close();
  void activeApp?.stop();
}
process.once('SIGINT', shutdown);
process.once('SIGTERM', shutdown);

// Cloud startup retries are bounded; restart after correcting credentials or connectivity.
for (let attempt = 0; attempt < 5 && !stopped; attempt++) {
  try {
    const app = await Spectrum({ projectId: process.env.PROJECT_ID!, projectSecret: process.env.PROJECT_SECRET!, providers: [imessage.config()] });
    activeApp = app;
    const im = imessage(app);
    let sending = false;
    timer = setInterval(() => {
      if (sending || stopped) return;
      sending = true;
      void flushOne(store, async text => {
        const dm = await im.space.create(await im.user(recipient));
        const result = await dm.send(text);
        if (!result || (Array.isArray(result) && result.length === 0)) throw new Error('Provider did not confirm a send');
      }).catch(() => console.error('Could not persist outbox status; inspect local storage.')).finally(() => { sending = false; });
    }, 1000);
    for await (const [space, message] of app.messages) {
      if (message.platform !== 'imessage') continue;
      const direct = imessage(space);
      if (!isAuthorizedInbound({ platform: message.platform, direction: message.direction, sender: message.sender, spaceType: direct.type }, recipient)) continue;
      if (message.content.type !== 'text') continue;
      try { store.inbound(message.id, message.content.text); }
      catch { console.error('Unable to save inbound request; no reply was sent.'); }
    }
    if (timer) clearInterval(timer);
    await app.stop();
    if (!stopped) throw new Error('Photon stream ended');
  } catch {
    if (timer) clearInterval(timer);
    await activeApp?.stop().catch(() => {});
    activeApp = undefined;
    console.error(`Photon connection unavailable (attempt ${attempt + 1}/5). Local API remains available. Verify credentials/network in your environment.`);
    if (attempt < 4 && !stopped) await new Promise(resolveDelay => setTimeout(resolveDelay, Math.min(30000, 2000 * 2 ** attempt)));
  }
}
