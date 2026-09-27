# SkyCompanion mobile design handoff

Updated 2026-09-26. Product name: **SkyCompanion**. Local HTML and screenshots use the new name; the old generated concept is explicitly superseded. This document describes the design work and its evidence. It does **not** certify the iPhone runtime, drone connection, inference performance, or accessibility behavior.

## Deliverables and actual status

| Deliverable | Status |
|---|---|
| Creative visual direction | **Superseded old-brand reference only.** `ios/DesignReference/superseded-skycompanion-home-concept.png` still visibly says SkyCompanion; it is not a SkyCompanion brand design. The historical prompt is retained. |
| Creative Production board | Not mounted. The skill requires a direct `creative_production_board` call rather than `functions.exec`; only the deferred function route was exposed. No board receipt is claimed. |
| [Editable Figma file](https://www.figma.com/design/nbbKLI3KZ3GeQlUDFx24tT) | **Online file still uses the old SkyCompanion name and content; SkyCompanion migration is pending quota recovery.** Created: seven core flow frames plus a dark home frame; 18 main components, 52 screen instances, 43 local variables and five text styles. |
| Figma visual QA | **Failed / blocked.** SF Pro appeared in available fonts but returned `hasMissingFont=true`; the screenshot rendered blank text. Loading the complete family, exact font variation and reassigning font did not fix it. |
| Figma prototype connections | **Incomplete.** The API requires NAVIGATE destinations to be top-level frames. The attempted write was rolled back. No working Figma connections are claimed. |
| Figma repair | The Starter MCP call limit was reached before the typography/layout repair could execute. `whoami` confirmed Starter. No upgrade was purchased. |
| Local interactive design reference | Completed in `ios/DesignReference/interactive-preview.html`. Open directly in a browser; no server, network, model or microphone is needed. |
| Local visual evidence | `preview-home-light.png`, `preview-session-dark.png`, `preview-setup-large.png`; inspected for visible text, wrapping, spacing and controls. |
| Local interaction checks | Seven destinations and all eight session states checked with a desktop browser. No JavaScript errors. Larger-text controls measured 44 pt minimum / 59 pt main actions. See `preview-verification.json`. |
| Native VoiceOver / Dynamic Type | Not validated by this design task. Requires actual SwiftUI app and device tests. |

The Figma failure is not silently substituted: the local reference is a separate fallback design artifact. The app's production typography remains SwiftUI's native system font. A planned, explicitly labeled **Inter preview** substitution in Figma remains unexecuted. Helvetica Neue was queried and was not available.

## Design direction and native mapping

A calm, native iOS utility: system grouped surfaces, readable labels, dark teal emphasis and generous vertical spacing. No decorative photography, busy animation, gradients or simulated detection overlays. Use actual `NavigationStack`, `List`, `Form`, system permission dialogs and the ReplayKit broadcast selector.

| Token | Light | Dark | SwiftUI meaning |
|---|---|---|---|
| background/primary | #F2F2F7 | #000000 | systemGroupedBackground |
| background/surface | #FFFFFF | #1C1C1E | secondarySystemGroupedBackground |
| label/primary | #171A1B | #F5F7F7 | primary / label |
| label/secondary | #555C61 | #B8BFC2 | secondary / secondaryLabel |
| accent/primary | #075E63 | #77D5D0 | AccentColor |
| accent/on | #FFFFFF | #073A3C | OnAccent |
| status/caution | #7A4900 | #FFD28A | Caution |
| status/critical | #A82424 | #FFB4AB | Critical |
| border/neutral | #CBD2D5 | #484E52 | separator |

Use semantic system colors in native code where available, rather than freezing the approximate reference hex values. Accent, caution and critical are asset colors with dark counterparts.

Typography: large title 34/Bold/41 line height; title2 22/Bold/28; headline17/Semibold/22; body17/Regular/22; footnote13/Regular/18. Use `.font(.largeTitle)`, `.title2`, `.headline`, `.body`, `.footnote` to retain Dynamic Type. Card radius16; spacing8/12/16/24. iPhone reference canvas430×932 logical points. Scroll content when text grows; never shrink type to retain this canvas height.

Calculated reference contrast ratios: primary text17.50:1 light /15.82:1 dark; secondary text6.80:1 /9.13:1; primary button7.53:1 /7.27:1. These are token calculations, not screenshots or native accessibility certification.

Figma foundations use separate Light and Dark semantic collections because the Starter plan limits modes. Both alias a primitive collection. Geometry tokens have explicit scopes; all tokens have iOS code syntax.

## Seven primary flows

1. **First use:** explain microphone and on-device speech, inspect permission/resource readiness, connect headphones, play a neutral sound check, ask the user to confirm they heard it. No fabricated permission success.
2. **Home:** state summary, Start assistance, Describe ahead, Local video test, Settings. “Ready” means prepared, not safe.
3. **Drone view:** connect in DJI Fly, review the current video region, use system broadcast selector, then switch to DJI Fly. Preview-dependent confirmation remains unavailable without a fresh frame.
4. **Session:** separately report camera, analysis and voice. Show recent observation and its freshness. Describe, mute/resume alerts, pause/resume analysis, stop listening and end assistance remain distinct operations.
5. **Local video test:** system file picker; preview, play/pause, confirmed ROI, fresh observations. This reuses the phone engine but does not prove drone capture.
6. **Settings:** installed voice, speech speed, reminder detail, voice commands, sampling off by default, local data deletion with confirmation, diagnostics.
7. **Diagnostics:** actual manifest version/classes, measured frame rate/frame age/latency, health per subsystem. Unknown values appear as “Not measured” or “No current view”, never invented metrics.

System pickers, permissions, crop manipulation and audio playback in the HTML are **design explanations only**, not functional substitutes for native controls. Appearance toggles and session states are explicitly labeled simulations.

## Session states and language

| State | Meaning and interaction |
|---|---|
| Ready | “Set up your drone view before starting.” |
| Preparing | “Waiting for a current camera frame.” Start only after actual readiness. |
| Running | “Listening for commands. Camera directions only.” |
| Muted | “Alerts are muted. Command listening is still on.” |
| Paused | “Analysis is paused. Confirm the view before resuming.” |
| Stale | “Camera view unavailable. Current surroundings cannot be assessed.” Clear expired output. |
| Interrupted | “Audio interrupted. Check headphones and restart from SkyCompanion.” |
| Recovery failed | “Unable to resume. Check the source and start again.” |

No scene result is “all clear”. No left/right personal navigation or meters without a verified user-relative geometry source. Urgency and sensing availability are separate. Every risk color includes words. The sound check says “This is SkyCompanion. Sound check.” rather than using a real hazard phrase.

## Accessibility contract

- Reading order: navigation, heading, state, grouped evidence, primary action, remaining controls.
- VoiceOver labels match visible English labels. Dynamic values belong in accessibilityValue; hints explain consequential actions. Do not announce frame-rate changes or every detection.
- Treat card title+detail as one sensible reading group. Announce meaningful state transitions once, avoiding collisions with live hazard speech.
- Minimum targets44×44 pt; primary actions at least56 pt high, with expandable height at large text sizes.
- Support Dynamic Type without truncation, light/dark, increased contrast and Reduce Motion. No behavior depends on animation.
- Distinguish “Mute alerts”, “Pause analysis”, “Stop listening” and “End assistance” in accessible labels and confirmation copy.
- Hardware audio interruption, denied permissions and stale frames must not show “Running”.
- True screen-reader usability and largest accessibility fonts remain iPhone acceptance work.

## Figma continuation

Use the existing file; do not duplicate it. Node IDs and success evidence are retained in `figma-state.json` and `figma-followup.json`.

1. Once the tool quota is available, inspect the existing IDs and run/adapt `figma-repair-preview.js`. It includes a SkyCompanion rename of the document, collection/style/component names and visible text on the selected page. Repeat the page-scoped migration for Components and Foundations. Do not claim the online name is already changed. The script is **pending and unverified**, not a completed mutation.
2. Apply the explicitly noted Inter-only preview font fallback, preserve SF Pro/system semantics for SwiftUI and return a missing-font audit.
3. Promote screen frames to top level to satisfy the prototype destination contract. Preserve content and component instances.
4. Create remaining destination sheets from the local reference, then wire pending links and add accessibility annotations.
5. Finish the Foundations & accessibility page; it currently exists as an empty page.
6. Inspect a rendered screenshot with readable text and validate all routes before claiming Figma completion.

Official iOS26 library search succeeded, but importing its components failed with “Not permitted to upsert from library”. SkyCompanion therefore uses self-owned editable components. The original text component properties were disconnected after the Figma SF Pro property mutation failed; native text overrides remain editable in instances. Restore linked TEXT properties after font repair if the service supports them.

## Source and artifact boundaries

The main app implementation is owned by the root task; this design contribution changes only this document and `ios/DesignReference/`. Generated visual assets are references, not bundled app UI. No web service, plugin or Figma dependency is introduced into the phone runtime.


## Creative Production board requirement

The [produce skill](/Users/stanley/.codex/plugins/cache/openai-curated-remote/creative-production/0.1.25/skills/produce/SKILL.md) says: “Do not invoke it through `functions.exec`; the direct MCP result carries the UI resource the host needs.” Only the deferred function route was available, so no board was mounted. This requirement concerns the board receipt; the local design files and native App are preserved independently.
