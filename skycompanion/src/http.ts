import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { InputError } from './records.ts';
import { Store } from './store.ts';
function authorized(value: string | undefined, token: string): boolean {
  const expected = Buffer.from(`Bearer ${token}`), actual = Buffer.from(value ?? '');
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}
async function body(req: IncomingMessage): Promise<unknown> {
  if (!req.headers['content-type']?.startsWith('application/json')) throw new InputError('Content-Type must be application/json', 415);
  let total = 0; const chunks: Buffer[] = [];
  for await (const chunk of req) {
    total += chunk.length;
    if (total > 256000) throw new InputError('Request too large', 413);
    chunks.push(chunk);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw new InputError('Invalid JSON'); }
}
export function createAPI(store: Store, token: string) {
  if (token.length < 24) throw new Error('SKY_INGEST_TOKEN must contain at least 24 characters');
  const respond = (res: ServerResponse, status: number, value: unknown) => {
    res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
    res.end(JSON.stringify(value));
  };
  const server = createServer(async (req, res) => {
    if (!authorized(req.headers.authorization, token)) { respond(res, 401, { error: 'Unauthorized' }); return; }
    try {
      const url = new URL(req.url ?? '/', 'http://localhost');
      if (req.method === 'POST' && url.pathname === '/v1/sync') {
        const value = await body(req);
        if (!value || typeof value !== 'object' || Array.isArray(value)) throw new InputError('Invalid sync request');
        respond(res, 200, store.sync((value as {records?: unknown}).records));
      } else if (req.method === 'GET' && url.pathname === '/v1/messages') {
        const raw = url.searchParams.get('after') ?? '0';
        if (!/^\d{1,15}$/.test(raw) || !Number.isSafeInteger(Number(raw))) throw new InputError('Invalid cursor');
        respond(res, 200, store.messages(Number(raw)));
      } else if (req.method === 'GET' && url.pathname === '/v1/preferences') {
        respond(res, 200, store.preferences());
      } else if (req.method === 'POST' && url.pathname === '/v1/preferences/applied') {
        respond(res, 200, store.preferencesApplied(await body(req)));
      } else if (req.method === 'GET' && url.pathname === '/v1/delivery') {
        respond(res, 200, store.deliveryStatus());
      } else if (req.method === 'GET' && url.pathname === '/v1/feedback') {
        respond(res, 200, { feedback: store.feedbackExport() });
      } else respond(res, 404, { error: 'Not found' });
    } catch (error) {
      respond(res, error instanceof InputError ? error.status : 500, { error: error instanceof InputError ? error.message : 'Internal storage error' });
    }
  });
  server.requestTimeout = 15000;
  server.headersTimeout = 10000;
  return server;
}
