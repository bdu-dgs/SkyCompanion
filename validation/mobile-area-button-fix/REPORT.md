# Applied video area: Form button dispatch correction

The previous persistence correction did not fix the actual button interaction. The phone's saved preferences and nine area-application events contained full-screen coordinates even though the user had resized the box. The recording writer correctly acknowledged those already-wrong coordinates.

## Root cause and change

`Use full image` and `Apply video area` were automatic-style SwiftUI buttons inside the same `VStack` Form row. Row-wide activation invoked both actions: reset to full screen followed by Apply. Even expanding `Precise adjustment` triggered the row actions. Reopening then faithfully restored the incorrect full-screen value.

Both buttons now explicitly use `.borderless`, so only the selected button performs its action. The reset remains an unapplied draft. Editor restore and explicit reset actions have separate diagnostic events. No crop geometry, model, recognition policy, audio, or recording writer code changed in this correction.

## Verification

- Physical iPhone evidence: saved rectangle was `{x:0,y:0,width:1,height:1}`; `phone-area-evidence.json` contains the corresponding repeated Apply/writer confirmations.
- Before fix, the real iOS app UI test failed when tapping `Precise adjustment`: the editor unexpectedly closed, Choose video area became Done, and no sliders remained. This is a reproduced UI failure, not a hypothetical storage issue.
- After fix, the same Xcode UI test changed width and height using the actual controls, applied, reopened three times, changed width again, applied, and relaunched. All comparisons retained the exact applied rectangle. The final observed value was Left 0%, Top 0%, Width 72%, Height 44%.
- The production crop-state persistence regression passed.
- Signed Release device build passed.
- All 42 model/inference files match the retained model lock.

UI regression: `ios/UITests/VideoAreaUITests.swift`, run with `scripts/test_video_area_ui.py`. The script creates a temporary test target using the real app sources and leaves the production Xcode project untouched. Both test cases finished and reported their assertion results, but Xcode stalled while finalizing the result bundles. Those completed runners were interrupted; the UI logs are the evidence, not a claimed successful overall `xcodebuild test` exit. The runner now has a five-minute timeout to prevent indefinite collection hangs.

The UI regression was executed on the iOS simulator. The corrected build is installed separately on the connected iPhone; installation receipts are retained in this folder. A new physical drone recording is not claimed. Previously overwritten crop coordinates cannot be recovered: choose the desired area once after this update.
