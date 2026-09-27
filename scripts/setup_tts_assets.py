#!/usr/bin/env python3
"""Install three verified offline clips from the user's SkyCompanion checkout.

This script does not clone repositories, install packages, synthesize text, play
audio, or upload anything. The source has no confirmed project-level license;
the local evaluation authorization must not be mistaken for redistribution rights.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.tts import ASSET_DIR, CLIPS, SOURCE_COMMIT, SOURCE_URL, validate_clip


def main() -> None:
    repository = ROOT
    # Each bundled clip is verified against its pinned SHA-256 below.
    commit = SOURCE_COMMIT
    verified = []
    for direction, spec in CLIPS.items():
        source = repository / "assets" / "tts" / "en_short" / spec["source_file"]
        data = source.read_bytes()
        metadata = validate_clip(data, spec["sha256"])
        verified.append((direction, spec, data, metadata))
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    provenance = {
        "repository": SOURCE_URL,
        "commit": SOURCE_COMMIT,
        "license_status": "No project-level license found at this revision; local evaluation only.",
        "clips": [],
    }
    for direction, spec, data, metadata in verified:
        target = ASSET_DIR / f"{spec['id']}.wav"
        temporary = target.with_suffix(".wav.tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
        provenance["clips"].append({
            "id": spec["id"], "direction": direction, "text": spec["text"],
            "source_path": f"assets/tts/en_short/{spec['source_file']}",
            "sha256": spec["sha256"], **metadata,
        })
    (ASSET_DIR / "provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({"installed": len(verified), "directory": str(ASSET_DIR), "commit": commit}))


if __name__ == "__main__":
    main()
