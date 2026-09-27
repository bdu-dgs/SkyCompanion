# Walking navigation and personal alert preferences

2026-09-27. Adds in-app Apple MapKit walking navigation and a persistent iMessage preference agent. No Maps app switch is needed. The UI and on-device speech stay in English; the messaging preference parser accepts common English requests.

## Use on the phone

Open **Walking navigation** on the home screen. Enable voice destination once, then say **“SkyCompanion, navigate to [place or full address]”**. The existing microphone and offline speech permissions apply; the first route also requests location permission. Allow precise location. A unique nearby match starts a walking route; ambiguous matches show and speak up to three candidates. Say **“SkyCompanion, choose one/two/three”**. Cancel with **“SkyCompanion, stop navigation”**. A typed destination is also available.

Only short maneuvers are spoken: Turn left/right, About to turn left/right, Keep/Bear left/right, Crossing ahead, Cross street, Turn around. Startup, destination selection, route failure and arrival have short status messages. Apple route data supplies maneuver meaning; the app does not infer traffic safety. Nonstandard/non-English instructions are marked **Limited voice guidance** and remain visible as original route text. Map search and route calculation require internet. A received route is tracked locally; rerouting requires internet again.

The app owns both guidance and warning speech. Priority is obstacle/health > navigation > assistant replies. Navigation cannot interrupt a warning. Invalid/old/inaccurate location, cancellation and rerouting cancel current navigation speech. GPS-derived turn prompts require horizontal accuracy ≤12 m and fresh fixes; off-route evidence triggers a throttled reroute. Continuous background location is enabled only during an active route. Existing camera assistance still has its own source/foreground/lock limits; adding navigation does not remove those limits.

## Personalize in iMessage

Use the existing assistant conversation. Examples:

- “Say less” / “Say more” / “Normal detail”
- “Don't mention trees” / “Enable trees”
- “Say less, mute trees and poles, alert interval 30 seconds”
- “Say less, mute trees and poles, repeat every 30 seconds”
- “Show my preferences” / “Reset preferences”

Supported categories: tree, pole, person, vehicle, bicycle, stairs, curb, obstacle. These are grouped detector labels, not verified object identity. Ordinary attention reminders can be filtered. Confirmed immediate-action/urgent alerts, tracking loss, boundary checks and forward avoidance remain enabled. In the rear-following mode, only confirmed near-side straight reminders may be filtered, and only if every relevant category is muted. Minimal speech retains necessary avoidance actions.

The interval (8–120 seconds) limits ordinary **new** alerts; unchanged obstacles do not repeat on a timer. This is a bounded conversational rule agent, not an unrestricted LLM. Unrecognized/conditional requests ask for clarification without partially modifying preferences. The parser does not train the visual model.

Preferences have a revision. The service distinguishes saved preferences from the last revision acknowledged by the phone. The phone stores validated preferences before applying and acknowledging them; saved policy works offline. **Assistant → Personal alert preferences** shows the local policy and sync state. The existing global mute remains separate.

## Service and transport

The service remains in `Hackathon/SkyCompanion/skycompanion`. Authenticated GET `/v1/preferences` returns schema 1; POST `/v1/preferences/applied` acknowledges `{revision}`. No token is embedded in the app. The phone polls when active or participating in a supported active session.

The user authorized a temporary Cloudflare HTTPS tunnel on this Mac. Keep the Mac, Node service and tunnel running for new iMessage changes to reach the phone. This is not permanent cloud hosting. The Debug provisioning script can reconnect a renewed tunnel only with the exact token already saved on the phone, preserving queued record IDs, inbox cursor and preferences; it does not discard unsynced trips or change accounts with pending records.

## Validation and limits

- CaptureCore: 133 tests passed after integration, including destination parsing, route progress/accuracy/expiry/rerouting/arrival, priority, preference decoding/cadence/filtering, and rear-following policy.
- Messaging: 25 tests and TypeScript checking passed. Tests use mocked transport/temporary data; they do not send iMessage.
- Signed iOS device build and app/extension model/resource checks passed. Simulator build and launch succeeded; native UI automation timed out, so a full navigation-screen walkthrough is not claimed.
- The HTTPS preference endpoint was reached successfully with authentication.
- Final signed app installed and launched on the connected iPhone 15 Plus. Phone acknowledged preference revision 0; all 31 previously pending trip records synchronized without discarding IDs (pending 0, inbox cursor 23). Evidence: `validation/navigation-personalization/device-validation.json`.
- Actual walking accuracy, spoken timing at intersections, background/lock behavior, concurrent drone/video capture and new live iMessage preference dialogue still require field/device testing. A successful build is not evidence of walking safety.
