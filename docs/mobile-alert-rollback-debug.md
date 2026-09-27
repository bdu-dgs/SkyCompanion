# Baseline rollback and speech-change investigation

## Delivered scope

Restore the recognition-result processing and alert scheduling used before the direction-debug changes. The reference is the command-list response at 2026-09-27 03:14:52 UTC. All listed SkyCompanion voice commands remain supported. Keep walking navigation (explicitly requested), screen-video saving, microphone/system/source-audio recording, editable recording crop, and the Apply-area crash fix. Keep the current concise scene wording. No new detection overlay is introduced.

The epoch-15, 72-class model is unchanged. SHA-256 checks cover all 42 model/inference files, including VisionEngine.swift. Fourteen recording, audio, crop UI, and navigation source files match the pre-rollback backup byte for byte. The mixed session controller changes only in risk dispatch and read-only logging.

## Confirmed causes and limits

1. **Application-policy changes altered which observation could speak.** The recent direction-debug work added lateral-person eligibility, separate person tracks, fresh candidate retries, category-based deduplication, short cooldowns, and passing-person prioritization. Those changes can alter spoken directions without changing detector outputs. They are now reverted.
2. **Detection, risk selection, admission, and audio start are different stages.** The previous baseline chooses an event separately from its dominant displayed assessment. In a frame with several targets, those can have different directions. A spoken right warning does not establish that the left person's box was mirrored. This can be a target-selection or presentation ambiguity.
3. **The baseline itself can suppress detections.** It uses a fixed image corridor, repeated-observation confirmation, eight-second alert cadence, content deduplication, freshness checks, and speech priority. The earlier 5 fps replay generated left-person events around 19 s that the cadence gate rejected. This establishes an offline scheduling explanation, not the exact cause of every phone utterance.
4. **Describe protection is intended.** The user's reference recording omits an obstacle warning during an explicit describe interaction. Treat this as a protected command response, not a missed-alert defect. Ordinary warnings do not interrupt that reply or return later as queued stale utterances. Haptic behavior during recording remains available.
5. **There is no evidence of a changed model or a global left/right inversion.** Package checksums match the epoch-15 source and manifest; the source video has an identity transform; native left/front/right checks pass. In the earlier 126-frame comparison, inference outputs were exactly identical before and after policy edits.
6. **Exact older-phone timing remains unverified.** The supplied 90-second, 220×480 screen recording is useful as a historical visual reference, but it is not an inference/utterance trace. Its speech was not independently transcribed here. Sampling cadence, first-model-load delay, missed frames, and audio occupancy can affect which fresh candidate wins; these remain hypotheses for differences predating the policy edits.

## Reproduction and diagnostic evidence

- 137 CaptureCore tests pass, including voice grammar, freshness, priority, and protected command behavior.
- The restored logic produces exactly the same 124 event/admission decisions on the same 126 cached native-inference frames as the pre-direction-debug baseline. This validates the rollback; it does not claim the baseline's detection or warning accuracy is perfect.
- Six native SwiftUI crop-slider layouts pass. Synthetic recording tests retain system/microphone/source-audio mixing and direct-audio fallback while changing crop mid-recording. Local authenticated transport/reconnection checks pass.
- Release iPhone build passes. See validation/mobile-command-baseline-rollback/report.json for installation and physical retest status.
- New diagnostics record video time, event direction, displayed assessment direction, target label, gate result, command protection, mute state, and active speech priority. Audio-start callbacks are logged separately. Logs do not alter selection/admission and add no UI. Decision diagnostics are throttled to once per second; they are not a complete per-frame trace, and a software audio callback does not measure acoustic onset.

The prior source is recoverable from .skycompanion-live/rollback-20260927-command-baseline/source-before-rollback.tar.gz. Earlier direction-debug reports are historical and have been marked rolled back.
