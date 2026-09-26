import "dotenv/config";
import { Spectrum } from "spectrum-ts";
import { imessage } from "@spectrum-ts/imessage";
import { fileURLToPath } from "node:url";
import { answerSynchronizedQuestion } from "./agent.ts";
import { EventStore, type StoredEvent } from "./events.ts";
import { createPhoneApi } from "./http_api.ts";
// Spectrum bridges a single agent loop to many messaging interfaces.
// Each provider in `providers` adds an interface (terminal TUI, iMessage, …).
// Docs: https://photon.codes/docs/spectrum-ts
const token = process.env.SKY_INGEST_TOKEN;
if (!token) throw new Error("Set SKY_INGEST_TOKEN before starting the phone event API");
const store = new EventStore(process.env.SKY_EVENTS_PATH ||
  fileURLToPath(new URL("../data/events.jsonl", import.meta.url)));
await store.load();
const app = await Spectrum({
  projectId: process.env.PROJECT_ID!,
  projectSecret: process.env.PROJECT_SECRET!,
  providers: [
    // imessage
    imessage.config(),
  ],
});

const recipient = process.env.SKY_REPORT_TO_PHONE;
const im = recipient ? imessage(app) : null;
let reportSpace: Awaited<ReturnType<NonNullable<typeof im>["space"]["create"]>> | null = null;
async function report(event: StoredEvent): Promise<void> {
  if (!im || !recipient) return;
  try {
    reportSpace ??= await im.space.create(await im.user(recipient));
    await reportSpace.send(`SkyCompanion: ${event.warning_text}`);
  } catch (error) { console.error("Could not send iMessage report:", error); }
}
const api = createPhoneApi(store, token, event => { void report(event); });
api.listen(Number(process.env.SKY_API_PORT || 8787), process.env.SKY_API_HOST || "127.0.0.1",
  () => console.log("Phone event API listening"));

// `app.messages` is an async iterable. Each tick yields a `space` (the
// conversation) and an inbound `message`. Reply by awaiting `space.send(...)`.
for await (const [space, message] of app.messages) {
  if (message.content.type === "text") {
    try {
      await space.send(answerSynchronizedQuestion(message.content.text, store.latestSessionEvents()));
    } catch (error) {
      console.error("Could not answer from SkyCompanion events:", error);
      await space.send("Event log is temporarily unavailable. Please try again.");
    }
  }
}
