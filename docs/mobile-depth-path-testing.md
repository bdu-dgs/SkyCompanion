# SkyCompanion depth and path deviation experiments (2026-09-26)

This implementation supports controlled phone-video and drone-view tests. It is not a validated navigation system for blind pedestrians. The existing YOLOE-11s v7, 960-input, 115-class obstacle pipeline remains the baseline.

## Phone workflow

Open **Settings → Depth and path testing**, also accessible from the local video's Analysis section.

### Depth and frame rate

1. Import a video at least 60 seconds long. Keep path monitoring off. Play about one minute with **Low-frequency depth estimation** off.
2. Enable depth, seek to the beginning and replay the same minute. Keep video, orientation and voice settings unchanged; record temperature, battery and microphone-listening state.
3. The experiment page shows YOLO FPS, depth processing time and depth status. Depth submits at most once every two seconds, with one task in flight and no pending queue. Serious thermal pressure releases the depth model while YOLO continues.
4. Raw optical-axis depth is diagnostic only. Object-region quantiles are not measurement confidence intervals and are not spoken as distance ranges. Normal guidance continues to report distance as unknown.

Numeric logs are stored in `Documents/SkyCompanionDiagnostics`. `performance-<session>.jsonl` records depth state, video SHA256, YOLO FPS, processing time, memory and thermal state. `depth-<session>.jsonl` records model/preprocessing versions, same-frame detection indices and raw depth. Video and images are not automatically saved.

After exporting logs:

```sh
python3 scripts/compare_mobile_depth_performance.py performance-session.jsonl performance-session.jsonl
```

One file may contain both phases. The tool compares only the same video and YOLO model, requires at least 30 samples per phase and successful depth output, and excludes path-monitoring samples. Short runs do not replace broadcast-extension or 30-minute stability acceptance.

### Sidewalk / crosswalk region monitoring

This version uses a **manually confirmed traversable region**. Crosswalk is not one of the current 115 classes; this is not automatic crosswalk detection.

1. Keep the user and the ground around their feet visible in the drone view. Confirm the DJI Fly crop and start analysis.
2. Return to SkyCompanion, which pauses external analysis, and open **Select person and confirm path**.
3. Choose **Use latest analyzed view and pause**. A sighted helper should select the numbered person corresponding to the user.
4. Choose Sidewalk or Crosswalk. Adjust four clockwise corners around the entire corridor. Include gaps between crosswalk stripes and exclude adjacent traffic lanes.
5. Confirm the person and path, then arm analysis and return to DJI Fly. For a local video, resume video analysis.
6. Say **SkyCompanion path** or **SkyCompanion path status** to query the current observation.

States include confirming, inside, near boundary, outside and position unknown. A transition requires at least three reliable observations spanning 700 ms. Unchanged states are not announced each frame. Path feedback respects the vibration setting and does not interrupt command replies or obstacle alerts. Being inside a region does not establish a clear route or permission to cross.

The pipeline combines explicit person selection, Vision tracking, matching YOLO person boxes, registration of the reference region and the box's bottom-center point. That point approximates the ground contact location; lifted feet, occlusion and box error need field review.

Person loss, overlap, ambiguous identity, out-of-frame feet or failed registration stop tracking until reselection; the app never automatically switches to another person. Source, crop, seek and replay-loop changes invalidate the relevant selection. Large motion after resuming may require reselection. Rear-following instructions are described in `mobile-short-guidance.md`. Heading comes from the confirmed rear-following setup, not automatic pose estimation. Reconfirm after turns or viewpoint changes. No traffic-light crossing permission is inferred.

## Collecting measured distances

No measured-distance footage has been provided; **distance accuracy acceptance has not been performed**.

- Fix camera, lens/zoom, crop and resolution; record `camera_id`. Keep phone and drone datasets separate.
- Begin with stationary central targets. Measure forward distance from the camera optical center and record measurement method/error. A slant tape measurement for a tilted camera or off-axis target is not optical-axis depth. Three-dimensional straight-line distance additionally needs camera intrinsics and geometry.
- Vary targets, light and distance. Record clip ID, time, target, measured value and matching depth-log frame ID. Predictions must never be entered as ground truth.
- Film calibration and test sets independently; neighboring frames of the same clip cannot be split across them. At least three clips and 30 measured targets per split is only an initial engineering screening minimum, not sufficient validation by itself.
- CSV: `split,clip_id,camera_id,model_id,preprocessing_id,reference,predicted_m,measured_m`. Split is `calibration` or `test`; reference is `camera_optical_axis`.
- Run `python3 scripts/evaluate_mobile_depth.py measurements.csv --output report.json`. It reports absolute/relative error and held-out interval coverage, rejecting missing, mixed, nonfinite or duplicate-clip inputs.
- Initial screening: P95 absolute error ≤1 m, calibration interval half-width ≤1 m and test coverage ≥90%. Refine these for the task and measured distribution; they are not walking-safety standards. Reports do not automatically unlock spoken distances.

## Model and evidence

Selected model: Depth Anything V2 Metric VKITTI Small, Apache-2.0; fixed source/weight hashes in `ios/Models/selectedDepthModel.json`. Preprocessing is 392-square letterbox, RGB/255 and ImageNet normalization. Output is optical-axis depth. VirtualKITTI training does not validate drone viewpoints. The model ships in both app and extension, requiring no runtime model download, Python, computer or cloud inference.

FP16 and a mixed-precision candidate retaining normalization/softmax in FP32 each failed one rotated case against the conversion P99 relative-difference threshold of <3%. Failure reports remain. The final FP32 candidate passed four cases. This establishes same-input conversion fidelity, **not real distance accuracy or phone FPS**.

- `validation/mobile-2026-09-26/depth-conversion-parity.json`: PyTorch/Core ML parity.
- `depth-fp16-rejected.json`, `depth-mixed-rejected.json`: rejected candidates.
- `path-registration.json`: actual Apple Vision registration on Mac, known translations and changed-scene rejection; not drone/person field evidence.
- Swift tests cover continuous confirmation, expiry, occlusion-to-unknown, deduplication, region validity, whole crosswalk corridors and invalid depth rejection.

Pending: phone depth-on/off FPS/resources; extension resources and sustained operation; identity/occlusion/camera-motion/boundary accuracy in drone footage; automatic sidewalk/crosswalk regions; measured-distance validation and camera-bound range release. These are required before claiming a complete road-assistance loop.
