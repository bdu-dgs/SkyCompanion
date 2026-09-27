#!/usr/bin/env python3
"""Prepare real YOLO weights and paired development config; no cloud credentials."""
import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS_URL = "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11n.pt"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true", help="Install requirements in this Python environment")
    parser.add_argument("--server-url")
    args = parser.parse_args()
    if args.install:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "backend/requirements.txt"),
                        "-r", str(ROOT / "backend/requirements-live.txt")], check=True)
    missing = [name for name in ("fastapi", "uvicorn", "cv2", "PIL", "ultralytics", "websockets")
               if importlib.util.find_spec(name) is None]
    if missing:
        parser.error("Missing dependencies: " + ", ".join(missing) + "; run in the backend virtual environment with --install")
    weights = ROOT / "backend/data/models/yolo11n.pt"
    weights.parent.mkdir(parents=True, exist_ok=True)
    if not weights.exists():
        temporary = weights.with_suffix(".download")
        print("Downloading YOLO11n from the official Ultralytics release...", flush=True)
        try:
            with urllib.request.urlopen(WEIGHTS_URL, timeout=30) as response, temporary.open("wb") as output:
                while data := response.read(1024 * 1024):
                    output.write(data)
            if temporary.stat().st_size < 1_000_000:
                raise RuntimeError("Unexpected download size; weights were not installed")
            temporary.replace(weights)
        finally:
            temporary.unlink(missing_ok=True)
    manifest = {"model": "yolo11n", "source": WEIGHTS_URL, "bytes": weights.stat().st_size,
                "sha256": hashlib.sha256(weights.read_bytes()).hexdigest()}
    weights.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
    command = [sys.executable, str(ROOT / "scripts/prepare_live_config.py")]
    if args.server_url:
        command += ["--server-url", args.server_url]
    subprocess.run(command, check=True)
    print("YOLO11n weights and local pairing configuration are ready.")


if __name__ == "__main__":
    main()
