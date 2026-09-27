# Phone Screen Capture Test Media

Play this media in VLC and capture it through the iPhone SkyCompanion screen broadcast. It is a prerecorded test video, **not a live drone input**. The timecode helps identify updates, pauses, repeats, and corresponding frames; it does not independently establish capture latency.

## Prepared Local Files

Large files and generated outputs are in `samples/local/` and are not committed to Git.

| File | Purpose |
| --- | --- |
| `local/skycompanion-pov-3874684-1080p30-timecode.mp4` | Test version to transfer to iPhone/VLC |
| `local/pexels-3874684-original.mp4` | Original video obtained from the official Pexels download URL |
| `local/skycompanion-pov-3874684-1080p30-timecode.json` | Input/output hashes, FFprobe data, and processing command |
| `local/pexels-3874684-contact.jpg` | Visual inspection sheet for three moments in the original video |
| `local/skycompanion-pov-timecode-contact.jpg` | Output frames 0, 390, and 750 for checking the visible timecode |

Output: **1920 × 1080, 30 fps, H.264, yuv420p, no audio track, 26.266667 seconds, 788 frames, 49,630,362 bytes**. Relative playback time `HH:MM:SS.mmm` and a zero-based frame number are burned into the upper-left corner. The timecode also restarts at zero when playback loops.

Original: 3840 × 2160, actual video frame rate 30000/1001, H.264, AAC audio track, container duration 26.281667 seconds, 80,305,329 bytes. Local FFprobe results are authoritative; the webpage summary's 59.94 FPS is not the actual frame rate of the downloaded version.

On 2026-09-25, several moments in the original and output frames 0, 390, and 750 were visually inspected. The camera moves forward along a sidewalk, showing streets, buildings, moving vehicles, and parked cars; it is not footage pointing downward at feet. Cars are a COCO detection category, but visually present objects are not guaranteed to be detected in every frame. Do not use this media to establish pothole detection, precise ranging, or obstacle-avoidance safety.

## Source and License Record

- Title: POV Shot of a Person Walking Down a Street.
- Author: Joe Valdes.
- Source page: <https://www.pexels.com/video/pov-shot-of-a-person-walking-down-a-street-3874684/>.
- Official `Free download` entry: <https://www.pexels.com/download/video/3874684/>.
- Public video URL linked by that entry: <https://videos.pexels.com/video-files/3874684/3874684-uhd_3840_2160_30fps.mp4>.
- Download and page verification date: 2026-09-25.
- License: Pexels License, <https://www.pexels.com/license/>. The page permits free download, use, and modification. Attribution is optional, but the source is retained here. The license also restricts uses such as unmodified resale, implied endorsement, and resale/distribution to other stock platforms; comply with the complete license.
- The download used a public official link, without an account, access token, or bypass of website restrictions.

SHA-256:

```text
1264959758f982960dba2de9d5e4eb245c69d8d3846cd43ff183d8792715f82d  pexels-3874684-original.mp4
db2f3b02288d64827e6406e3800122f80eb76e80943921157c6a53fe2d5ba822  skycompanion-pov-3874684-1080p30-timecode.mp4
```

## Reproduce Processing

Download the original from the official page above and place it at `samples/local/pexels-3874684-original.mp4`. Run from the project root:

```bash
backend/.venv/bin/python scripts/prepare_test_video.py \
  samples/local/pexels-3874684-original.mp4 \
  samples/local/skycompanion-pov-3874684-1080p30-timecode.mp4 \
  --source-url 'https://www.pexels.com/video/pov-shot-of-a-person-walking-down-a-street-3874684/'
```

If the output already exists, explicitly add `--overwrite`. The script also accepts other local inputs and does not access the network itself. It scales proportionally with letterboxing, converts to 30 fps, burns in the timecode, removes audio, and produces an H.264 MP4 and a JSON processing record.

`ffmpeg` and `ffprobe` must be on PATH, and the Python environment running the script must have Pillow. Use `--font /path/to/font.ttf` to specify a font; by default, the script searches for a platform monospace font. This machine's FFmpeg 8.1.1 lacks the `drawtext` filter, so FFmpeg handles decoding, size/frame-rate conversion, and encoding, while Pillow burns text into each intermediate frame. A separate FFmpeg installation is unnecessary. Different encoders, fonts, or software versions may produce different hashes.

Transfer the output MP4 to the phone through VLC Wi-Fi sharing or another local transfer method. Start the capture test with VLC in landscape fullscreen and playback controls hidden. Loop this video for the ten-minute continuity test.
