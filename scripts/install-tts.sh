#!/usr/bin/env bash
set -euo pipefail
MOVE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  printf 'Qwen3-TTS MLX requires an Apple Silicon Mac.\n' >&2
  exit 1
fi
MOVE_MACOS_VERSION="$(sw_vers -productVersion)"
if (( ${MOVE_MACOS_VERSION%%.*} < 14 )); then
  printf 'Qwen3-TTS MLX requires macOS 14 or newer.\n' >&2
  exit 1
fi
command -v uv >/dev/null
command -v ffmpeg >/dev/null
uv sync --directory "$MOVE_ROOT/workers/tts" --frozen
printf '\nTTS environment installed. Open Models & Services and prepare the local model.\n'
