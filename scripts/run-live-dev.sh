#!/bin/bash
set -euo pipefail
SKYCOMPANION_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKYCOMPANION_PYTHON="$SKYCOMPANION_ROOT/backend/.venv/bin/python"
if [[ ! -x "$SKYCOMPANION_PYTHON" ]]; then
  echo "Create the backend environment as described in docs/live-testing.md first." >&2
  exit 1
fi
if [[ ! -f "$SKYCOMPANION_ROOT/.skycompanion-live/config.json" || ! -f "$SKYCOMPANION_ROOT/backend/data/models/yolo11n.pt" ]]; then
  echo "Run this first: $SKYCOMPANION_PYTHON $SKYCOMPANION_ROOT/scripts/setup_live.py" >&2
  exit 1
fi
if [[ "${SKYCOMPANION_LIVE_MODEL:-yoloe-11s}" == "yoloe-11s" && ! -f "$SKYCOMPANION_ROOT/backend/data/models/skycompanion-yoloe-11s-v7.pt" ]]; then
  echo "Run this first: $SKYCOMPANION_PYTHON $SKYCOMPANION_ROOT/scripts/prepare_obstacle_models.py" >&2
  exit 1
fi
if [[ ! -f "$SKYCOMPANION_ROOT/frontend/node_modules/vite/bin/vite.js" ]]; then
  echo "Run npm install in the frontend directory first." >&2
  exit 1
fi
"$SKYCOMPANION_PYTHON" - <<'PY'
import errno
import socket
for port in (8000, 5173):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: s.bind(('0.0.0.0', port))
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                raise SystemExit(f'Port {port} is in use; close the existing SkyCompanion service first.')
            raise SystemExit(f'Cannot start the local service (port {port}): {error}')
PY
mkdir -p "$SKYCOMPANION_ROOT/.skycompanion-live"
SKYCOMPANION_BACKEND_PID=""
SKYCOMPANION_FRONTEND_PID=""
cleanup() {
  trap - EXIT INT TERM
  [[ -z "$SKYCOMPANION_BACKEND_PID" ]] || kill "$SKYCOMPANION_BACKEND_PID" 2>/dev/null || true
  [[ -z "$SKYCOMPANION_FRONTEND_PID" ]] || kill "$SKYCOMPANION_FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM
(
  cd "$SKYCOMPANION_ROOT/backend"
  exec "$SKYCOMPANION_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-max-size 1100000
) > "$SKYCOMPANION_ROOT/.skycompanion-live/backend.log" 2>&1 &
SKYCOMPANION_BACKEND_PID=$!
(
  cd "$SKYCOMPANION_ROOT/frontend"
  exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173
) > "$SKYCOMPANION_ROOT/.skycompanion-live/frontend.log" 2>&1 &
SKYCOMPANION_FRONTEND_PID=$!
echo "SkyCompanion live monitor: http://127.0.0.1:5173/live"
echo "Keep this window open. Press Control-C to stop both services."
echo "Diagnostic logs: $SKYCOMPANION_ROOT/.skycompanion-live/"
while kill -0 "$SKYCOMPANION_BACKEND_PID" 2>/dev/null && kill -0 "$SKYCOMPANION_FRONTEND_PID" 2>/dev/null; do
  sleep 1
done
echo "A service stopped unexpectedly. Check the diagnostic logs." >&2
exit 1
