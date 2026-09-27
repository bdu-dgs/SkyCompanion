#!/usr/bin/env python3
"""Download official YOLOE, bake a versioned vocabulary, and record provenance."""
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.obstacle_models import CLASSES, MODEL_DIR, VOCABULARY_VERSION


def main():
    from ultralytics import YOLOE, __version__
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    os.chdir(MODEL_DIR)
    origin = "https://github.com/ultralytics/assets/releases/download/v8.4.0/yoloe-11s-seg.pt"
    original = MODEL_DIR / "yoloe-11s-seg.pt"
    if not original.exists():
        tmp = original.with_suffix(".download")
        urllib.request.urlretrieve(origin, tmp)
        tmp.replace(original)
    model = YOLOE(str(original))
    names = [name for name, _ in CLASSES]
    model.set_classes(names, model.get_text_pe(names))
    output = MODEL_DIR / f"skycompanion-yoloe-11s-v{VOCABULARY_VERSION}.pt"
    model.save(str(output))
    manifest = {"kind": "pretrained_with_text_prompts_not_finetuned", "source": origin,
                "source_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "ultralytics": __version__,
                "vocabulary_version": VOCABULARY_VERSION, "names": names}
    output.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
