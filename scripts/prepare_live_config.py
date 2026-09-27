#!/usr/bin/env python3
"""Generate matching, untracked Mac/iPhone configuration without exposing secrets."""
import argparse
import hashlib
import json
import secrets
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-url", help="Default: http://<Mac LocalHostName>.local:8000")
    parser.add_argument("--rotate-token", action="store_true")
    parser.add_argument("--fallback-server-url", action="append",
                        help="Additional known receiver URL; repeat for multiple fallbacks")
    args = parser.parse_args()
    target = ROOT / ".skycompanion-live/config.json"
    previous = json.loads(target.read_text()) if target.exists() else {}
    try:
        hostname = subprocess.check_output(["scutil", "--get", "LocalHostName"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        hostname = socket.gethostname().split(".")[0]
    url = args.server_url or previous.get("server_url") or f"http://{hostname}.local:8000"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        parser.error("server-url must be an HTTP(S) address without credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        parser.error("server-url must not contain a path, query or fragment")
    token = previous.get("token") if not args.rotate_token else None
    token = token or secrets.token_urlsafe(32)
    fallback_urls = args.fallback_server_url if args.fallback_server_url is not None else previous.get("fallback_server_urls", [])
    validated_fallbacks = []
    for fallback in fallback_urls:
        value = urlparse(fallback)
        if (value.scheme not in ("http", "https") or not value.hostname or value.username or value.password
                or value.path not in ("", "/") or value.query or value.fragment):
            parser.error("fallback-server-url must be a root HTTP(S) address without credentials")
        normalized = fallback.rstrip("/")
        if normalized != url.rstrip("/") and normalized not in validated_fallbacks:
            validated_fallbacks.append(normalized)
    config = {"server_url": url.rstrip("/"), "fallback_server_urls": validated_fallbacks,
              "receiver_id": hashlib.sha256(token.encode()).hexdigest()[:16], "token": token}
    for path in (target, ROOT / "ios/Shared/LocalCaptureConfig.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2) + "\n")
        path.chmod(0o600)
    print(f"Receiver URL: {config['server_url']}")
    print("Mac and iPhone pairing configuration created; credentials are not shown. Reinstall the phone app after changing the address or credentials.")


if __name__ == "__main__":
    main()
