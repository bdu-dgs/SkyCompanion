// Launch with: node --env-file=.env --import tsx scripts/start-local.mjs
// Existing Photon credentials are loaded by Node, never read or printed here.
import { readFileSync } from 'node:fs';
const configuration = JSON.parse(readFileSync(new URL('../data/local-runtime/config.json', import.meta.url), 'utf8'));
process.env.SKY_INGEST_TOKEN = configuration.token;
process.env.SKY_REPORT_TO_PHONE = configuration.recipient;
process.env.SKY_PORT = '8787';
process.env.SKY_STATE_PATH = 'data/live-agent-state.json';
await import('../src/index.ts');
