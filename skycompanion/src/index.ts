import "dotenv/config";
import { Spectrum } from "spectrum-ts";
import { imessage } from "@spectrum-ts/imessage";
import { answerQuestion, defaultFramesPath, loadEvents } from "./agent.ts";
// Spectrum bridges a single agent loop to many messaging interfaces.
// Each provider in `providers` adds an interface (terminal TUI, iMessage, …).
// Docs: https://photon.codes/docs/spectrum-ts
const app = await Spectrum({
  projectId: process.env.PROJECT_ID!,
  projectSecret: process.env.PROJECT_SECRET!,
  providers: [
    // imessage
    imessage.config(),
  ],
});

// `app.messages` is an async iterable. Each tick yields a `space` (the
// conversation) and an inbound `message`. Reply by awaiting `space.send(...)`.
for await (const [space, message] of app.messages) {
  if (message.content.type === "text") {
    try {
      const events = await loadEvents(process.env.SKYCOMPANION_FRAMES_PATH || defaultFramesPath);
      await space.send(answerQuestion(message.content.text, events));
    } catch (error) {
      console.error("Could not read SkyCompanion events:", error);
      await space.send("Event log is temporarily unavailable. Please try again.");
    }
  }
}
