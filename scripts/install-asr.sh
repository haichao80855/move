#!/usr/bin/env bash
set -euo pipefail
MOVE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  printf 'MLX recognition requires an Apple Silicon Mac. You can still import SRT files.\n' >&2
  exit 1
fi
command -v uv >/dev/null
command -v ffmpeg >/dev/null
uv sync --directory "$MOVE_ROOT/workers/asr" --frozen
printf '\nASR environment installed. Models download on the first transcription.\n'
