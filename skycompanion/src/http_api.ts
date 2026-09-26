import { createServer, type IncomingMessage, type Server } from "node:http";
import { timingSafeEqual } from "node:crypto";
import { answerSynchronizedQuestion } from "./agent.ts";
import { EventStore, parseBatch, type StoredEvent } from "./events.ts";

function authorized(request: IncomingMessage, token: string): boolean {
  const given = request.headers.authorization;
  if (!given?.startsWith("Bearer ")) return false;
  const a = Buffer.from(given.slice(7));
  const b = Buffer.from(token);
  return a.length === b.length && timingSafeEqual(a, b);
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  let bytes = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    bytes += chunk.length;
    if (bytes > 256_000) throw new Error("Request too large");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown;
}

export function createPhoneApi(store: EventStore, token: string,
  onFresh?: (event: StoredEvent) => void): Server {
  if (!token) throw new Error("SKY_INGEST_TOKEN is required");
  return createServer(async (request, response) => {
    const reply = (status: number, value: unknown) => {
      response.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
      response.end(JSON.stringify(value));
    };
    if (request.url === "/health" && request.method === "GET") return reply(200, { ok: true });
    if (!authorized(request, token)) return reply(401, { error: "unauthorized" });
    try {
      if (request.url === "/v1/events" && request.method === "POST") {
        const batch = parseBatch(await readJson(request));
        const accepted = await store.add(batch);
        for (const event of accepted) {
          const age = event.received_at_ms - event.observed_at_ms;
          if (age >= -5_000 && age <= 10_000) onFresh?.(event);
        }
        return reply(200, { accepted: accepted.length, duplicates: batch.length - accepted.length,
          received_at_ms: Date.now() });
      }
      if (request.url === "/v1/query" && request.method === "POST") {
        const body = await readJson(request);
        if (typeof body !== "object" || body === null || !("question" in body) ||
            typeof body.question !== "string" || body.question.length > 500) throw new Error("Invalid question");
        return reply(200, { answer: answerSynchronizedQuestion(body.question, store.latestSessionEvents()) });
      }
      return reply(404, { error: "not_found" });
    } catch (error) {
      if (error instanceof SyntaxError || error instanceof Error &&
          /^(Invalid|Request too large)/.test(error.message)) return reply(400, { error: "invalid_request" });
      console.error("Phone API request failed:", error);
      return reply(500, { error: "internal_error" });
    }
  });
}
