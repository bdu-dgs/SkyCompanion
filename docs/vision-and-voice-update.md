# SkyCompanion Nearby Obstacles and Voice on Both Devices

## 2026-09-26 Subsequent Implementation and On-Site Evidence

This section updates the previous foreground-only phone voice limitation; earlier dated records below are retained as history. The live weights remain `skycompanion-yoloe-11s-v7.pt`; experimental fine-tuned weights were not deployed directly.

- The phone now has a user-initiated, genuinely continuous local STT audio session, background audio declaration, and permission/interruption handling. Microphone audio is not uploaded or saved by default. The user actually said `SkyCompanion describe` with Bilibili in landscape and heard a response; the server also received a phone speech-completion acknowledgment. This is preliminary cross-app verification, not verification of DJI Fly, long sessions, or all headphone/call recovery cases.
- Fixed a discovered issue where scene descriptions incorrectly reused risk results. `SceneDescription` independently derives up to three object categories, counts, and camera-relative directions from stable objects across consecutive frames. An unconfigured risk corridor no longer turns descriptions of pedestrians/traffic lights into “no confirmed obstacle.” Raw detection, risk inference, and scene descriptions are separate. Unaccepted categories remain generic `obstacle`, and `train` is excluded from speech.
- The phone now includes English voice / Speech speed controls. Alerts and scene descriptions use system `AVSpeechSynthesizer`, automatically preferring installed Enhanced/Premium voices. Provenance for old SkyCompanion WAV files is retained, but they are no longer the phone's default voice. The latest signed build installed and launched successfully; new scene speech and voice quality await user retesting.
- Supports explicit commands `SkyCompanion repeat/mute/unmute/describe/stop listening` and bounded questions such as `SkyCompanion, what is ahead?`, not unrestricted visual chat. Only the current camera view is described.
- The phone can select audio routing, test speech, pause, or prepare a landscape full-frame view and central test corridor. This experimental mode pauses in portrait and must be prepared again after the next disconnection/reconnection. Phone-managed sessions do not depend on a continuously connected computer webpage. Inference still runs on the Mac and is not deployed to the cloud.
- Events and scene responses carry original phone capture uptime and are checked for expiration before synthesis starts. Expired speech is not replayed; risk has priority. Repeat commands recheck stable occupancy that still exists rather than reviving an old voice queue. Network commands record only normalized commands, not raw speech transcripts.
- The risk module now uses multi-object tracking and target-selection hysteresis, confirmation across at least three observations/0.4 seconds, and global eight-second throttling. Low objects, surface changes, and overhead candidates have different evidence rules. Objects missed by the model still cannot trigger alerts. Image position is not distance in meters, and camera direction is not the direction of the drone carrier.
- Saved 328 original frames across three segments of the current video, with approximately eight seconds of surrounding context. Fixed regression snapshots, draft annotations, and public targeted training are in [dataset and training records](dataset-training-20260926.md). Added two CC BY videos and 20 frames, retaining author, license, and timestamps. Historical Pexels material is no longer used for new ML training/formal testing after license review.
- Completed 10 epochs of actual supervised fine-tuning on public pole/tower data. After calibration using only the validation split, pole recall on the fixed 503-image test split improved from v7's 11.7% to the candidate's 30.0%, and precision from 8.9% to 33.3%. The candidate still missed 191/273 poles and produced 164 false positives, so direct replacement of the 115-class live model was rejected. The failed default same-threshold report is retained; see the training record.
- Two assistants independently visually reviewed 39 visible instances in 10 newly added Japanese riverside frames; see `samples/local/external-streets-20260926/riverside-labels-reviewed-v2.json`. This is not human review. Ambiguous distant trunks remain ignore regions and cannot be exported as all-class negatives. All frames remain grouped as one video/location.
- Same-frame truncated-trunk tests: v7 conf .25/.1/.05 and separate `tree` / `tree trunk` prompts all failed to recover the trunk. A simple threshold fix cannot be claimed successful. See [trunk diagnostic](truncated-tree-diagnostic.md).

Checks for this round: 64 backend tests and 22 Swift core tests passed; signed device build, installation, and launch succeeded. Frontend build succeeded, the browser displayed the new instructions, keyboard control toggling worked, and there were no current console errors. The first browser-automation attempt to click the checkbox did not change its state; keyboard verification was then used and the original setting restored. The initial failure was not reported as a pass.

Measurements still required: updated natural voice and object descriptions, continuous background operation, mute/unmute, recovery from audio interruptions/headphone removal, and actual first-risk discovery time. Independent all-class model acceptance, phone Core ML, and formal cloud deployment remain incomplete. The cloud container recipe has not been built/run because the local Docker daemon is unavailable; see [phone and cloud paths](phone-cloud-deployment.md).


2026-09-25. This record describes the implementation at that time; earlier model experiments are in `obstacle-test-report.md`.

## Detection Configuration

The user interface contains only **SkyCompanion Vision · Experimental**. The service actually loads `skycompanion-yoloe-11s-v7.pt`, with 115 classes, input size 960, and confidence threshold 0.25. It uses MPS when available on Apple Silicon and falls back to CPU elsewhere. `/api/live/report` returns the actual device, file, SHA256, vocabulary version, and class count. The interface brand name must not be used to infer the model version.

Weight SHA256: `b089b9d0d5793814e9690ebfec83e1c02a75712cd213139db676581b5ce69bb8`.
The source is official Ultralytics YOLOE-11s pretrained segmentation weights, saved with fixed text features.
**No SkyCompanion-specific supervised training was performed for these weights**; expanded vocabulary and input size do not constitute trained-model accuracy acceptance.

The previous 28-class prompt configuration omitted original COCO categories such as chair, dining table, dog, and parking meter, narrowing the output range. This update restores COCO80 vocabulary coverage and adds street-obstacle categories including construction barrels/cones, trash cans, poles, fences, warning tape, tree trunks, rocks/stone barriers, columns, kiosks, and sculptures/monuments. A vocabulary entry means a class can be predicted, not that it is reliably recognized.

Same-image diagnostics:

| User report | Actual observation | Unresolved |
| --- | --- | --- |
| Chairs and rocks | 960 input recovered a chair and 3 concrete blocks in a plaza; a stone barrier in a clean original frame was also detected | Tables still missed at low scores; a few successful boxes cannot establish per-class recall |
| Sculpture | One image gained a monument detection at 32% | Still missed in another image; broad base and steps not fully covered |
| Fences, construction barriers, poles/columns | Some fences boxed; original failure samples retained | Incomplete coverage on both sides, with thin poles and thick columns still missed |
| Newsstands, information kiosks, parking payment posts | Corresponding vocabulary restored or added | Still not detected consistently in this image batch |
| Original categories | COCO80 vocabulary restored | Jewelry display rack falsely detected as dog; false-positive evidence retained |

Experiment index:

- `backend/data/obstacle_experiments/furniture/README.md`: tables/chairs, rocks, kiosks, and COCO vocabulary restoration.
- `backend/data/obstacle_experiments/park/README.md`: same-image comparisons for sculptures and left/right fences.
- `backend/data/obstacle_experiments/pole-stage-audit.json`: class mapping, text features, and NMS/mask-stage diagnosis.
- `backend/data/obstacle_experiments/grounding-nearby/README.md`: alternative Grounding DINO weights; recovered some objects but produced false positives and took about 271 ms/image (384), so did not directly replace the live model.
- `backend/data/obstacle_experiments/segformer/README.md`: Cityscapes semantic model; still missed thin poles, and old boxes in screenshots induced false poles, so it was not directly integrated.

These user screenshots contain existing prediction boxes and player controls. They are diagnostic only, not clean training ground truth. Original broadcast evidence is separately stored in `backend/data/obstacle_cases/`, including source JPEGs, actual cropped PNGs, predictions, configuration, and frame correspondence. Twelve new screenshots were separately archived with `training_eligible=false`. Training still requires complete review and separation by video/location; model predictions were not automatically treated as true labels.

## Nearby-Object Priority

The backend adds `attention` to every actual prediction, ranking by bottom-edge position, width, height, and area. It does not alter confidence or coordinates or delete raw detections. Both wide low rocks and thin tall poles are assessed; large objects with partially occluded bottoms are not automatically hidden solely by an area rule.

The webpage prioritizes these nearby candidates by default; `Show distant objects` restores every prediction. The canvas and list use the same decoded frame, and toggling does not move old boxes onto a new image. Saved samples still contain every box. These are only first-person image-geometry cues, **not metric ranging**, and are affected by camera tilt, occlusion, and actual object dimensions. Image-corridor occupancy requires separate confirmation. Neither no boxes nor no nearby candidates means safe passage.

## SkyCompanion Voice

At the user's request, [SkyCompanion](https://github.com/bdu-dgs/SkyCompanion) was cloned at fixed commit `e8c763f7de8f8b46ee749e3f66a704edbb141187`. Its short-voice caching, single pending event, expiration discard, and priority separation were used as references. Windows installation scripts were not executed, and the SkyCompanion detection pipeline was not replaced.

Three local WAV files of approximately 1.47 seconds are actually used:

- `Stop. Obstacle ahead.`
- `Stop. Obstacle left.`
- `Stop. Obstacle right.`

The Mac uses local audio; on failure it displays the reason and falls back to browser speech. The iPhone bundles the same files and plays them with AVAudioPlayer. This path requires no cloud TTS or API key and did not yet include STT at this stage. Unverified object names are not spoken. Left/right describe the obstacle's image position, not avoidance instructions.

On the webpage, choose Mac / iPhone / Both under `Playback on`, then use `Enable voice` and `Test voice`. On the phone, enable `Enable phone voice receiver` in SkyCompanionCapture. Simultaneous playback on both devices is allowed only with Both selected. Authenticated `/api/live/voice` uses existing pairing credentials; reconnection does not replay historical messages.

Frame-processing time is deducted from the 1500 ms speech-start deadline first. The sending queue and client then recheck remaining time. Expired, duplicate, paused, disconnected, switched-output, or old-image-context events are not queued for later replay. Actual obstacle alerts take priority over voice tests. The native client also handles audio interruptions and headphone removal. Playback callbacks establish only API acceptance/completion, not actual sound-to-ear latency.

**At this historical stage, iPhone reception was explicitly foreground-only.** Returning to Bilibili or DJI Fly, or locking the phone, paused phone voice; returning to SkyCompanionCapture reconnected automatically. Silent loops or hidden recording were not used to keep the process alive in the background. Consequently, when the same phone played first-person video, available output was the Mac or headphones connected to the Mac. “DJI Fly foreground + continuous iPhone background voice” was not yet implemented or accepted at this stage.

Detailed interfaces/provenance: `skycompanion-tts.md`; native playback boundaries: `ios-voice.md`. Phone Core ML migration, layered STT/TTS design, and references to other navigation-assistance projects: `mobile-voice-architecture.md`.

## Verification Boundaries

The new weights were actually loaded on MPS with 115 classes, with a file digest matching the prepared artifact. Offline CPU/MPS comparisons at 960 input produced identical rock outputs; median single-image duration was about 46 ms on MPS and 138 ms on CPU. These are offline pipeline timings, not live phone frame rates.

An actual phone broadcast was separately measured for 30 seconds with 16 state samples, using the same v7 weights, MPS, and 960 input, with analysis enabled throughout. Inference frame rate was **13.1–15.0 fps, median 14.8 fps**; median single-frame inference was **46.16 ms**; display-acknowledgment P95 in sampled reports was **170.87–188.5 ms**, with 9 additional dropped frames. Display acknowledgment includes capture, processing, webpage drawing, and return transport; it is not full drone-photon-to-screen or sound-to-ear latency. The user selected a full-frame ROI, and the 960×443 frame includes side letterboxing. These results do not generalize to other video sizes or devices. Raw measurement: `backend/data/obstacle_experiments/v7-live-30s.json`.

Saved 109 complete original evidence frames for this version. Each frame's model digest matches v7; all predictions and `attention` are included, and actual input files are complete. The annotation queue was updated to the same vocabulary; new frames remain unreviewed.

41 backend behavior tests passed, including original-frame consistency, class coverage, nearby-object ranking, fixed audio resources, authenticated voice routing, deadlines, queue priority, and stopping. Fourteen Swift tests passed, the signed device build succeeded, and the updated app installed and launched. Eighteen frontend tests and the production build passed. An actual WebKit browser revealed a timer binding error, which was fixed. After reload, local audio preparation, Both routing, and Test voice completed; the interface reported playback completion and no new console errors occurred after the fix. This does not establish human confirmation of audible sound. A central test region was then briefly enabled on the current video; the page showed an in-corridor obstacle alert and completed one automatic playback flow. Clearing the region canceled audio and restored the no-region state. This verifies the event-to-player link, not detection classes, corridor geometry, or actual walking safety.

The iPhone video connection was healthy, but as of this historical check, the separate phone voice receiver had not connected and `last_phone_ack=null`. Further diagnosis was waiting for status text after the user stayed in SkyCompanionCapture and enabled the Phone voice receiver, before checking actual reception/playback acknowledgments. Compilation success, simulated sockets, decodable files, or an online phone screen broadcast were not reported as a phone voice pass. Another `devicectl` attempt to activate the installed app in the foreground timed out after 15 seconds. That attempt did not confirm the app returned to the foreground; actual phone status text was needed to continue diagnosis.
