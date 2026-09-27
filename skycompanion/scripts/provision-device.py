"""Provision the installed Debug app without exposing its upload token in argv/logs."""
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
configuration = json.loads((root / 'data/local-runtime/config.json').read_text())
if not configuration.get('endpoint', '').startswith('https://'):
    raise SystemExit('Save the current HTTPS tunnel origin in private config.json first.')
if len(sys.argv) != 2:
    raise SystemExit('Usage: python3 scripts/provision-device.py <connected-device-UDID>')
environment = os.environ.copy()
environment['DEVICECTL_CHILD_SKY_PHOTON_BOOTSTRAP_URL'] = configuration['endpoint']
environment['DEVICECTL_CHILD_SKY_PHOTON_BOOTSTRAP_TOKEN'] = configuration['token']
# Reconnect only if this exact token already belongs to the installed app.
# The app preserves its pending queue/cursor and refuses account changes with pending records.
environment['DEVICECTL_CHILD_SKY_PHOTON_RECONNECT'] = '1'
result = subprocess.run([
    'xcrun', 'devicectl', 'device', 'process', 'launch', '--device', sys.argv[1],
    '--terminate-existing', '--console', 'com.stanley.skycompanion.capture',
], env=environment)
raise SystemExit(result.returncode)
