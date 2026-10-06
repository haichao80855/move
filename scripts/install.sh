#!/usr/bin/env bash
set -euo pipefail
MOVE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$MOVE_ROOT"
for tool in uv node npm ffmpeg ffprobe; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Missing %s. On Mac: brew install uv node ffmpeg\n' "$tool" >&2
    exit 1
  fi
done
uv sync --directory "$MOVE_ROOT/apps/api" --frozen --group dev
npm --prefix "$MOVE_ROOT/apps/web" ci --no-audit --no-fund
npm --prefix "$MOVE_ROOT/apps/web" run build
printf '\nMove installed. Run ./scripts/start.sh\n'
