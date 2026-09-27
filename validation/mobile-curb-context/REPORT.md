# Curb context instead of automatic obstacle cautions

## Finding

The previously preserved 261-frame native detection cache contains curb predictions in all 261 frames: 17,261 curb box observations across time, including 7,902 with confidence at least 0.55. These are repeated, often overlapping hypotheses, not counts of separate physical curbs. The unchanged reference input and model are documented in `../mobile-caution-consistency/manifest.json` and `model-integrity.json`.

The earlier risk rule treated curb as a low obstacle and could upgrade it because of a large foreground rectangle or intersection with the image neighborhood. This establishes neither the walker's proximity to the actual edge nor a need to cross it. The independent visual review identified the side road boundary as context, rather than the principal conflict for the central walker.

## Change

- Raw YOLO predictions, model files, preprocessing, thresholds and decoder remain unchanged. Curb detections can still appear in inspection results and scene descriptions.
- A curb detection rectangle alone no longer becomes a general obstacle risk event or an automatic Caution. This applies both with and without explicit followed-user selection.
- Walking guidance does not start obstacle speech from curb rectangles alone. It keeps those rectangles as uncertain route blockers, so suppressing their speech cannot authorize a turn across them.
- Near/outside warnings from an independently confirmed walking-path boundary remain enabled. Those require the user and path to be configured; the generic curb detector does not substitute for that configuration.
- Person, step, pothole and drop-off rules remain enabled. This change does not establish that a real curb is harmless, that every curb crossing is detected, or that a route is safe.

## Validation

- 153 Swift core tests passed. New cases cover large repeated side-curb boxes, unchanged input detections, preserved person and ground-change hazards, preserved path-boundary warnings, and a quiet curb still blocking an unverified turn.
- The reference video was replayed with the same cached native detections, existing explicit wearer tracking, three repeated 5 fps runs and two 2.5 fps phases, under simulated 2.5- and 3.5-second speech durations.
- No curb cautions occur in these revised schedules. Previous 5 fps focused schedules already had none; each previous 2.5 fps phase had one, now removed. Raw detection counts are unchanged.
- All five independently reviewed event windows remain covered: blue pedestrian left, stone column right, green pedestrian left, planter before the passage and cone before passing. See `event-coverage.json` and `long-speech-coverage.json`.
- Removing curb candidates changes competition for some secondary speech slots; this is expected and is not a model change. It does not establish every remaining spoken object as dangerous.
- Xcode Release build passed for the App and broadcast extension. All 42 model-related file hashes remain unchanged.
- Installation and launch results are preserved separately. Physical iPhone audio replay and unseen scenes are not verified by the offline scheduling simulation.
