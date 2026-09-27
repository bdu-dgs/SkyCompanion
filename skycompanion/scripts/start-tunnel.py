"""Run the authorized temporary Cloudflare tunnel and save its current origin."""
import json
import os
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
runtime = root / 'data/local-runtime'
config_path = runtime / 'config.json'
if not config_path.exists():
    raise SystemExit('Private local-runtime/config.json must exist before starting the tunnel.')
child = subprocess.Popen([
    str(runtime / 'cloudflared'), 'tunnel', '--url', 'http://127.0.0.1:8787', '--no-autoupdate',
], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    with (runtime / 'tunnel.log').open('a') as log:
        for line in child.stdout:
            log.write(line); log.flush()
            match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
            if match:
                configuration = json.loads(config_path.read_text())
                configuration['endpoint'] = match.group(0)
                temporary = runtime / 'config.next.json'
                with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as out:
                    json.dump(configuration, out)
                temporary.replace(config_path)
                print('HTTPS origin saved:', match.group(0), flush=True)
                print('Re-provision the Debug iPhone app after its pending records are synced.', flush=True)
            elif 'Registered tunnel connection' in line:
                print('Tunnel connected.', flush=True)
    raise SystemExit(child.wait())
except KeyboardInterrupt:
    child.terminate()
    child.wait(timeout=15)
