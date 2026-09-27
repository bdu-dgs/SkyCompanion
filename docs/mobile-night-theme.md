# SkyCompanion night-sky interface — 2026-09-26

Implemented in the native iPhone app, using the supplied DJI screenshot for dark surfaces / photographic hierarchy, and the existing approved moon-and-drone illustration for identity. No DJI branding or community/store functions were copied.

## Opening

- Once per process, about 1.6 seconds followed by a 0.3-second fade. Tap anywhere to skip.
- Existing LocalContentView / LocalSessionModel remains mounted underneath; the opening never starts assistance or claims readiness.
- First-run setup appears only after the opening ends.
- Returning from DJI Fly does not replay it. Backgrounding during the opening dismisses it.
- VoiceOver bypasses the opening; Reduce Motion uses 0.7 seconds with no animated transition.
- The OS launch background is the matching navy `LaunchNight` asset. The illustrated opening is an in-app SwiftUI view, not a simulated system loading indicator.

## Interface

- Default Night sky appearance; Settings → Appearance → Theme offers Night sky / Light / Follow iPhone.
- Photographic Connect drone card; native Test a video action; actual session state; Setup and sound check; Settings in the header with an accessible label.
- Non-idle session status and controls move above the photographic card.
- Native setup, session, video, settings, diagnostics and experimental forms share the background and accent colors.
- Accessibility text sizes hide the decorative hero photo and redundant source subtitle. Functional text scales and wraps in a scroll view. Only the brand wordmark and decorative icons have a size cap.
- No model, risk thresholds, speech content or camera capture changes.

## Assets and reproducibility

`design/brand/SkyCompanion-drone-moon-half-master.png` is the preserved approved source. `ios/SkyCompanionCapture/Assets.xcassets/MoonFlight.imageset/MoonFlight.jpg` is a 298 KB opaque JPEG export (quality 93), bundled locally. This iteration reused the existing generated illustration; it did not generate a new image or require a runtime image service.

`SkyAppearance.swift` owns the opening, semantic colors and reusable cards. `LocalContentView.swift` owns live navigation. `prepare_mobile_app.py` includes the new Swift source and preserves the root entry on regeneration.

Figma was not updated: the previously observed Starter MCP quota remains a limitation. The implementation and local screenshots are the deliverables for this iteration; no Picsart upload or new plugin-generated asset was needed.

## Verification

- Simulator Debug build passed on iPhone 18 Pro / iOS 27.
- iPhone Release signing build passed with deployment minimum iOS 18.
- Built-bundle verification passed, including 115-class model and matching extension contracts; see `validation/mobile-2026-09-26/night-ui/bundle.json`.
- Final version installed on the connected iPhone; installation receipt `/tmp/sky-night-final-install.json`. Remote launch timed out after 20 seconds (`/tmp/sky-night-launch.json`); installation is confirmed, foreground launch is not. Open it manually on the phone.
- Actual simulator screenshots: opening (DEBUG hold flag), automatically entered home (without hold flag), light home, maximum accessibility size home, connection steps, settings and first-run setup.
- Largest-font inspection initially found oversized branding and excessive decorative space; fixed and recaptured.
- Preview routes are compiled only into DEBUG simulator builds. They display real screens, not mocked running states.
- Visual checks do not establish full VoiceOver interaction, physical tap-to-skip, audio delivery, DJI return behavior or drone field performance. Those remain phone checks.

Build logs: `/tmp/sky-night-simulator-build.log`, `/tmp/sky-night-device-build.log`.
