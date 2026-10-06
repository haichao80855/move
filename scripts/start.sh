#!/usr/bin/env bash
set -euo pipefail
MOVE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$MOVE_ROOT"
if [[ ! -x "$MOVE_ROOT/apps/api/.venv/bin/python" || ! -f "$MOVE_ROOT/apps/web/dist/index.html" ]]; then
  printf 'Run ./scripts/install.sh first.\n' >&2
  exit 1
fi
"$MOVE_ROOT/apps/api/.venv/bin/python" "$MOVE_ROOT/scripts/doctor.py"
if [[ "$(uname -s)" == Darwin && "${MOVE_NO_OPEN:-0}" != 1 ]]; then
  ("$MOVE_ROOT/apps/api/.venv/bin/python" "$MOVE_ROOT/scripts/open_when_ready.py") &
fi
cd "$MOVE_ROOT/apps/api"
exec "$MOVE_ROOT/apps/api/.venv/bin/python" -m uvicorn move_app.main:app --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 5
