# More natural offline speech

2026-09-26: the connected iPhone's latest app diagnostics reported **Samantha · en-US · Standard**, rate 0.44. No explicit app voice/rate preference was saved. This is evidence of the voice recently used, not a full OS voice inventory.

Changes:
- Continue selecting Premium before Enhanced before Standard in automatic mode.
- For an explicitly chosen voice, use a downloaded higher-quality version of the same voice/language when available; keep the voice character.
- Refresh the existing settings view when system voices change or the app becomes active. Actual speech and displayed voice share the same selection function.
- Default rate changes to 0.48 only when no rate preference exists; saved user choices remain. Keep natural pitch and no added onset delay.
- Sound check now speaks a short, conversational English sample. The English-only app migrates older non-English preferences to automatic English voice selection.
- Show specific download instructions when the effective voice is Standard. No new settings section or home UI.

For the current iOS 18 phone: Settings → Accessibility → Spoken Content → Voices → English → download an Enhanced or Premium voice. Return to SkyCompanion and use automatic voice selection, then Play sound check. The app cannot install Apple's voice resources on the user's behalf. Downloading a voice is required before it can be selected; no online speech service was introduced.

Apple references:
- https://support.apple.com/en-ie/111798
- https://developer.apple.com/documentation/avfaudio/avspeechsynthesisvoicequality/premium

Limits: build/bundle checks do not prove a more human listening experience. No new voice download or acoustic listening comparison has been confirmed. Rate changes alone do not replace the basic synthesis model.
