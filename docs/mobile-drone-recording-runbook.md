# Drone recording and voice checks on iPhone

This workflow uses the phone, DJI Fly and SkyCompanion. No computer or cloud inference is needed after installation. It verifies the result rather than treating a recording indicator as proof of successful video and audio capture.

## 1. Prepare the camera and audio

1. Connect the drone in DJI Fly and open its live camera view. Keep the phone in the orientation you will use during recording.
2. Open SkyCompanion → Settings → Play sound check. Confirm that the selected speaker or headphones actually produces sound, with media volume audible.
3. Open Connect drone → Enable voice assistance. Allow microphone, speech recognition and Add Photos if requested. Confirm Voice commands on / Listening on this iPhone.
4. Keep this voice-assistance session enabled throughout recording. The App microphone supplies both commands and recorded microphone audio. The broadcast sheet's microphone switch is not a substitute for this step.

## 2. Confirm the applied video area

1. Expand Choose video area. The box reopens at the last applied position and size. Edits are a draft until Apply video area is pressed.
2. If a DJI preview is available, adjust directly on that image. Otherwise use the labeled screen guide to prepare an approximate area, or start a short calibration broadcast to obtain a real view.
3. Tap Apply video area. Before broadcasting, expect Saved on iPhone. Start the broadcast to use this area.
4. In Share DJI Fly, tap the system broadcast control and choose SkyCompanion. Wait for the system countdown, then open DJI Fly for a few seconds and return to SkyCompanion.
5. Reopen Choose video area. It retains the last applied rectangle on the last external preview. Drag the box or its corner if necessary and tap Apply video area again.
6. With the broadcast connected, expect **Applied — recording crop confirmed.** This requires acknowledgment from the recording writer, not just a button tap. Waiting for broadcast confirmation is not confirmation.
7. Reopen the area once and compare its Left / Top / Width / Height percentages. They should be unchanged. Use full image only becomes the applied choice after Apply video area.

Changing the area updates future frames in the same recording; it does not recrop earlier frames or restart recording. To have the entire clip use one final area, finish the short calibration recording, then start a new recording with that saved area. The first encoded frame waits for crop configuration. App-switching/setup screens can still appear within the selected rectangle: this records the shared phone screen, not an independent raw drone video stream.

## 3. Identify the followed user and start assistance

1. Tap Ready — open DJI Fly next and switch to DJI Fly. Let several fresh frames be analyzed.
2. Return to SkyCompanion → Select followed user → Use latest analyzed view and pause.
3. Select the numbered person who is the followed user (the central black-shirted walker in the supplied reference video), then Confirm followed user. An optional path corridor is not required just to exclude the user.
4. Tap Arm and switch to DJI Fly and open the drone view again. Look for User tracked · excluded from alerts when checking session state, or use the status query below.

Drone people alerts and walking instructions wait until user identity is confirmed. The selected user and weaker duplicate body detections are excluded; other people then remain eligible. Before selection or during tracking loss, fresh non-person obstacles can still trigger camera-relative warnings such as Caution. Camera left. All people alerts and walking instructions are paused during identity uncertainty. These camera directions do not instruct the user to move. Cropping changes invalidate the old user/path coordinates, so select the user again after applying a different area. Reapplying the identical area keeps the selection. If tracking recovery fails, confirm/reselect the user; the App does not automatically replace the user with another central person.

## 4. Make a short voice test first

1. Keep DJI Fly visible and the phone unlocked.
2. Wait until any spoken warning finishes, then allow about one second of silence. Say **Sky Companion, status.** Both SkyCompanion and Sky Companion spellings are supported by the local command parser. English is required.
3. Expect an answer about the real session state. Analyzing. Obstacle alerts are on. describes service operation, not a safe path. Your position is unconfirmed. Camera alerts remain on; people alerts and walking guidance are paused. means fresh camera evidence remains available but the user needs to be selected or tracked. A stopped feed, paused analysis or failed voice session must not report active camera alerts.
4. Say **Sky Companion, describe.** in one clear utterance and pause. Expect a current scene description or an explicit fresh-view-unavailable answer. Avoid speaking over the App's response: command recognition pauses during App speech, although microphone recording continues.
5. Include a clearly spoken phrase such as Recording test one, and record any ordinary Caution that occurs naturally. Do not create an obstacle solely to force an alert.

If describe remains silent, try status after the App finishes speaking. The new local diagnostics distinguish wake detection, accepted command, description expiry and actual software speech start. Do not assume Listening by itself proves that a command was understood.

## 5. Stop, save and verify the actual file

1. Return to SkyCompanion and tap **Stop recording and save**. Returning pauses analysis but should leave recording active until this stop action.
2. Wait for **Video saved to Photos.** Do not close the App while it is saving.
3. Open the newly saved video in Photos, unmute playback and turn up media volume.
4. Check all of the following in a 20–30-second test clip:
   - The saved picture shows only the applied rectangle, including its first encoded frame when the area was set before recording.
   - Your recorded test phrase is audible and continuous.
   - SkyCompanion's describe/status response and any Caution are audible and intelligible.
   - Source audio is preserved when the source actually has audio. A silent source cannot validate this; use Test a video with a known audible soundtrack for that check.
   - The clip plays through the intended end rather than merely appearing in Photos.

Keep the same audio route and orientation for the full test. A call, phone lock, output-device loss, storage failure or OS termination can still interrupt operation; software tests cannot guarantee every recording. The short saved-file check is the device-specific acceptance step.

## Local soundtrack check

Open Test a video, import a video with audible original sound, enable voice commands/test recording, start the SkyCompanion broadcast and play the video. Say Sky Companion describe, then Stop recording and save. Check source sound, your voice and the App answer in Photos. Local video testing records its full test UI; returning to drone mode restores the previously applied drone crop.
