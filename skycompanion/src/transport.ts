import type { Store } from './store.ts';
export type InboundIdentity = { platform: string; direction: string; sender?: {id: string}; spaceType: string };
export function normalizePhone(value: string): string | undefined {
  const phone = value.replace(/[\s()-]/g, '');
  return /^\+[1-9]\d{7,14}$/.test(phone) ? phone : undefined;
}
export function isAuthorizedInbound(message: InboundIdentity, recipient: string): boolean {
  const expected = normalizePhone(recipient);
  return !!expected && message.platform === 'imessage' && message.direction === 'inbound' && message.spaceType === 'dm' && normalizePhone(message.sender?.id ?? '') === expected;
}
export async function flushOne(store: Store, send: (text: string) => Promise<void>): Promise<void> {
  const pending = store.pending();
  if (!pending) return;
  try {
    await send(pending.message.text);
    store.delivery(pending.message.id, true);
  } catch {
    store.delivery(pending.message.id, false);
    console.warn('iMessage send failed; retained in persistent outbox (maximum 5 attempts).');
  }
}
