#!/usr/bin/env python3
"""Make a local, silent 1080p30 H.264 screen-capture test clip with timecode.

Requires ffmpeg, ffprobe and Pillow. No network access is performed. FFmpeg does
the scaling, frame-rate conversion and H.264 encoding; Pillow burns the timecode
because some FFmpeg builds (including Homebrew's) omit the drawtext filter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT, FPS = 1920, 1080, 30


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def font_for_timecode(explicit: Path | None) -> ImageFont.FreeTypeFont:
    candidates = [explicit] if explicit else [
        Path("/System/Library/Fonts/Monaco.ttf"),
        Path("/System/Library/Fonts/Menlo.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
        Path("C:/Windows/Fonts/consola.ttf"),
    ]
    for path in candidates:
        if path is not None and path.is_file():
            return ImageFont.truetype(str(path), 36)
    raise ValueError("No monospace font found. Provide --font /path/to/font.ttf")


def read_frame(stream, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        block = stream.read(size - len(data))
        if not block:
            break
        data.extend(block)
    if data and len(data) != size:
        raise RuntimeError("FFmpeg returned a truncated raw-video frame")
    return bytes(data)


def render(source: Path, destination: Path, font: ImageFont.FreeTypeFont) -> tuple[int, list[str], list[str]]:
    decode_command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(source), "-map", "0:v:0", "-an", "-sn", "-dn",
        "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ]
    encode_command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264",
        "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-metadata", "title=SkyCompanion screen-video test, not live drone footage",
        "-y", str(destination),
    ]
    decoder = subprocess.Popen(decode_command, stdout=subprocess.PIPE)
    encoder = None
    completed = False
    frame_count = 0
    try:
        encoder = subprocess.Popen(encode_command, stdin=subprocess.PIPE)
        assert decoder.stdout is not None and encoder.stdin is not None
        while True:
            raw = read_frame(decoder.stdout, WIDTH * HEIGHT * 3)
            if not raw:
                break
            frame = Image.frombytes("RGB", (WIDTH, HEIGHT), raw)
            draw = ImageDraw.Draw(frame)
            milliseconds = frame_count * 1000 // FPS
            seconds, millis = divmod(milliseconds, 1000)
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            label = f"TEST  {hours:02}:{minutes:02}:{seconds:02}.{millis:03}  F{frame_count:05}"
            bounds = draw.textbbox((0, 0), label, font=font)
            draw.rectangle((20, 20, 52 + bounds[2], 84), fill="black")
            draw.text((36, 28), label, font=font, fill="white")
            encoder.stdin.write(frame.tobytes())
            frame_count += 1
        encoder.stdin.close()
        decoder.stdout.close()
        decode_status = decoder.wait()
        encode_status = encoder.wait()
        if decode_status != 0 or encode_status != 0 or frame_count == 0:
            raise RuntimeError(
                f"FFmpeg failed: decoder={decode_status}, encoder={encode_status}, frames={frame_count}"
            )
        completed = True
    finally:
        if not completed:
            for process in (decoder, encoder):
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait()
    return frame_count, decode_command, encode_command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Downloaded local video; never a URL")
    parser.add_argument("output", type=Path, help="Destination MP4")
    parser.add_argument("--font", type=Path, help="Optional monospace TTF/TTC font")
    parser.add_argument("--source-url", help="Optional public source page for provenance")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    source, output = args.input.resolve(), args.output.resolve()
    manifest_path = output.with_suffix(".json")
    if not source.is_file():
        parser.error(f"Input is not a local file: {source}")
    if source == output:
        parser.error("Input and output must differ")
    if output.suffix.lower() != ".mp4":
        parser.error("Output must end in .mp4")
    if (output.exists() or manifest_path.exists()) and not args.overwrite:
        parser.error("Output or manifest already exists; use --overwrite to replace")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            parser.error(f"Required executable not found: {tool}")
    font = font_for_timecode(args.font)
    source_info = probe(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="skycompanion-video-", dir=output.parent) as temporary:
        temporary_output = Path(temporary) / "prepared.mp4"
        count, decode_command, encode_command = render(source, temporary_output, font)
        result = probe(temporary_output)
        videos = [stream for stream in result["streams"] if stream["codec_type"] == "video"]
        if (
            len(videos) != 1 or videos[0]["codec_name"] != "h264"
            or videos[0]["width"] != WIDTH or videos[0]["height"] != HEIGHT
            or videos[0]["avg_frame_rate"] != "30/1"
            or any(stream["codec_type"] == "audio" for stream in result["streams"])
        ):
            raise RuntimeError("Prepared file does not satisfy silent 1080p30 H.264 requirements")
        temporary_output.replace(output)
    encode_command[-1] = str(output)
    result["format"]["filename"] = str(output)
    manifest = {
        "source_url": args.source_url,
        "input": {"path": str(source), "sha256": sha256(source), "probe": source_info},
        "output": {"path": str(output), "sha256": sha256(output), "probe": result},
        "frame_count": count,
        "timecode": "Burned into pixels; elapsed output time HH:MM:SS.mmm and zero-based frame index",
        "commands": {"decode": decode_command, "encode": encode_command},
        "purpose": "Screen-video test material, not a live drone feed or latency measurement",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {count} frames: {output}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
