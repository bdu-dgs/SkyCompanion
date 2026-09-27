# SkyCompanion: followed user, icon and clearer controls

Updated 2026-09-26.

## Followed-user selection

In Local video → Analysis → Select followed user (or Session controls → Select followed user):

1. Start analysis until an analyzed snapshot arrives.
2. Select **Use latest analyzed view and pause**.
3. Select the numbered person who is the user, then **Confirm followed user**.
4. **Resume video analysis**, or arm and return to DJI Fly.

A sighted helper is needed for reliable visual selection in this experimental setup. Selecting a path is optional for identity exclusion; walking instructions still require the separate confirmed corridor and rear-following setup.

The selected person is tracked using Vision independently of ground registration. Only a same-frame, unambiguous YOLO person match is excluded from scene descriptions, obstacle risk input and experimental depth samples. Other people remain obstacles. The original detections stay available for diagnostics, with the followed user labeled as excluded. A path-registration failure does not itself make the user an obstacle.

If the person is lost, overlapping, ambiguous or missing from YOLO, identity tracking latches unavailable. It does not automatically select the largest/central person or reacquire another pedestrian. Unknown person identity suppresses confident people counts in scene descriptions and says that people are not counted; risk processing retains people. This can cause a conservative person alert after tracking loss. Select again to resume exclusion. Source/crop changes and video seeks clear selection. Stale frame roles never remove a detection from another frame.

Counts for the same class are combined across image directions: selected user plus two cars on different sides produces two cars, with both directions. Three or more are summarized as “several.” Camera-relative direction and unvalidated metric distance constraints are unchanged.

## Interface

- Home: Connect drone, Test a video, current state, Settings and sound check. Inactive scene actions are hidden until a session exists.
- Connect drone: four expandable steps—Enable voice, Share DJI Fly, Choose video area, Start analysis. Completed steps show a check plus “Done.” Only the current step expands automatically; all steps can still be inspected manually.
- Crop sliders and historical analysis metrics are under disclosures. Portrait and landscape remain supported.
- Current analysis state remains separate from broadcast connection. Arming still waits for a fresh analyzed frame; returning to SkyCompanion pauses external analysis.
- Native semantic colors, dynamic fonts, labeled controls and minimum touch targets remain. Actual full VoiceOver and drone-field acceptance are pending.

## App icon

The final icon is generated realistic artwork of a smaller silver-white drone above the upper half of a Moon in a starry night sky, matching “Fly Me to the Moon”. It is not a photograph of the user's aircraft. See `design/brand/README.md` and `icon-manifest.json`; the 1024 RGB asset is installed through Assets.xcassets/AppIcon.appiconset. The earlier vector drone is superseded. Figma synchronization was blocked by the Starter MCP quota; local assets and Xcode implementation are complete.

## Evidence and limits

- CaptureCore: 83 tests passed, including explicit wearer exclusion, other pedestrian retention, overlapping-person rejection, stale/revision mismatch, identity loss and two-car cross-direction counting.
- Release iOS and Debug simulator builds passed. Actual app bundle verifies AppIcon, compiled models, English resources, signing profile and loopback-only configuration.
- Connected iPhone 15 Plus: install and process launch succeeded. This does not verify spoken delivery, appearance of SpringBoard icon cache, person tracking accuracy or DJI capture.
- Native iOS 27 simulator screenshots: home and drone setup; light mode and maximum auxiliary font in dark mode. These are rendered screens, not Figma mockups. Only the visible layout was checked; simulator UI automation for tapping/scrolling was unavailable through Device Hub, so no full interactive/VoiceOver audit is claimed.
- Still required: real rear-follow drone/person footage, crossings and occlusion, nearby pedestrians, return/resume, new tracker frame-rate/memory impact, sustained 30-minute run, physical sound/vibration and outdoor accuracy checks. Prior performance results must not be treated as measurements of this changed pipeline.
