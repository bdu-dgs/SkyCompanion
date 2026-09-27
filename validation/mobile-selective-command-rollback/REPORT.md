# Selective command-era rollback

## Requested result

Restore recognition-result processing and alert behavior associated with the command-list response dated 2026-09-27 03:14:52 UTC. Retain recording/save, external microphone and system/source audio, current Apply area controls and crash fix, walking navigation, and the latest curb-context suppression. Remove the later feature that inserts detected obstacle names into Caution speech. Do not change YOLO.

The active behavior is documented in [mobile-current-alert-policy.md](../../docs/mobile-current-alert-policy.md). `describe` remains a scene-description command and may name objects; automatic cautions and repeats use the restored generic wording.

## Restore provenance

- Original reference and first rollback evidence: `../mobile-command-baseline-rollback/report.json`.
- Pre-naming source: `.skycompanion-live/named-caution-backup/`.
- Risk, data contract, scene/gate, role assignment and tracking before the latest consistency changes: `.skycompanion-live/caution-consistency-before/`.
- This rollback's full prior source backup and manifests: `.skycompanion-live/selective-command-rollback-20260927/`.

The initial rollback had nine exact implementation matches, recorded in `baseline-source-comparison.json`. The subsequent explicit request to exclude the followed walker retains two identity/tracking fixes and their pipeline/delivery integration; `wearer-source-comparison.json` records the final five exact reference matches. `LocalRiskEngine.swift` differs only by rejecting standalone curb caution candidates. `MobileWalkingPlanner.swift` differs only by retaining curb rectangles as quiet route blockers rather than independently spoken obstacle triggers.

The later fresh-candidate retry scheduling, speech-start commit scheduling, class-aware risk-track changes, followed-user neighborhood priority, paired-passage cautions and four-second default have been reverted. Optical tracking adjustments and duplicate-body role exclusion are retained for the user's additional requirement. This is a selective rollback; the previous consistency experiment's complete alert policy is historical evidence, not the behavior of this build. The baseline does not promise identical historical phone utterance timing or ideal danger ranking.

## Retained functionality checks

- All 42 locked model/inference files match: `model-integrity.json`.
- All 31 retained support files match their pre-rollback hashes, including recording, audio, area UI, voice listening, command parsing, navigation and related support: `retained-files.json`.
- The mixed session controller's recording, saving, source switching, crop confirmation, navigation and session-control methods match the prior version. Only observation reset, alert receipt, command-response wording within `handle`, and alert snapshot code changed: `session-methods.json`.
- No appearance reset, model conversion, weight replacement, training or remote preference mutation was performed.

## Executed validation

- 144 CaptureCore tests passed after the wearer addition (`wearer-core-tests.log`): baseline voice commands, availability/freshness, priorities, eight-second cadence, generic caution speech, path/navigation behavior, four retained curb regression cases, and duplicate-body exclusion across risk, scene descriptions and walking instructions. The initial 141-test result is preserved in `core-tests.log`.
- Six native SwiftUI crop-slider cases passed, including zero-width and very narrow ranges.
- Both synthetic recording modes passed: system mix with original soundtrack, speech and microphone; direct-audio fallback with duplicate-source suppression. Both exercised orientation changes, changing crop during the same movie, invalid-crop rejection, repeated finish and file failure handling. These are macOS writer tests, not new physical ReplayKit/Photos listening results.
- Five scheduling replays on the preserved 261-frame native-detection cache produced only `Caution left/right/front. Check your path.` speech and no curb cautions. This uses cached inference, baseline camera-only risk processing and simulated speech occupancy. It is not an acoustic or safety test.
- Xcode Release build passed for the App and broadcast extension, including the wearer addition (`wearer-xcodebuild.log`).
- The final wearer-aware update installed and launched successfully on the connected iPhone (`wearer-install.json`, `wearer-launch.json`). No SkyCompanion broadcast process was active before installation. The earlier pre-addition installation succeeded but launch was blocked by device lock; those historical outcomes remain in `install.json` and `launch.json`. Successful launch does not establish physical tracking or speech accuracy.

Retaining curb suppression intentionally changes candidate competition compared with the original reference. Reverting later prioritization also means the earlier five-event coverage results cannot be asserted for this build. Physical iPhone playback, recording listen-back and drone operation still require a new user retest.

## Followed-user addition

The central black-shirted walker is the user in the reference video. Explicit first selection is still required; a central or nearby person is never automatically assigned this role. The saved user selection and independent optical tracker authorize same-frame exclusion. Weaker near-coincident duplicate body boxes are also removed from obstacle and scene inputs. Raw model output, other pedestrians and the model itself are retained.

The same filtered environment is now supplied to walking-obstacle checks. If a configured user is not reliably matched, the pipeline resets risk history and returns limited availability, preventing uncertain own-body observations from surviving as repeatable cautions. Directional haptics and speech are both withheld during this state. The original eight-second reminder cadence is unchanged.

Native macOS Vision tracking replay on the actual 52.08-second video, with its preserved 261-frame model detection cache at 5 fps, tracked the selected user in 258 frames. Frames at 20.0, 20.2 and 42.0 seconds were uncertain and recovered. Output exactly matches the previously visually reviewed tracking run. This is not an iPhone live-tracking or safety measurement. See `wearer-exclusion.json` and `wearer-tracking.json`.

After the addition, all 42 model/inference files and all 31 retained recording/audio/crop/navigation support files still match their locked hashes (`wearer-model-integrity.json`, `wearer-retained-integrity.json`).
