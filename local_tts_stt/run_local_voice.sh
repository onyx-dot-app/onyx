#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

STT_PORT="${STT_PORT:-6601}"
TTS_PORT="${TTS_PORT:-6602}"
STT_MODEL="${LOCAL_STT_MODEL:-mlx-community/whisper-large-v3-turbo}"

if ! command -v uv >/dev/null 2>&1; then
  printf 'uv is required. Install it first: https://docs.astral.sh/uv/\n' >&2
  exit 1
fi

ensure_brew_package() {
  local binary="$1"
  local package="$2"

  if command -v "$binary" >/dev/null 2>&1; then
    return
  fi

  if ! command -v brew >/dev/null 2>&1; then
    printf '%s is required. Install Homebrew, then run: brew install %s\n' "$binary" "$package" >&2
    exit 1
  fi

  printf 'Installing %s with Homebrew...\n' "$package"
  yes | HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ENV_HINTS=1 brew install "$package"
}

if ! command -v ffmpeg >/dev/null 2>&1; then
  ensure_brew_package ffmpeg ffmpeg
fi

ensure_brew_package espeak-ng espeak-ng

cleanup() {
  trap - INT TERM EXIT
  if [[ -n "${STT_PID:-}" ]]; then
    kill "$STT_PID" 2>/dev/null || true
  fi
  if [[ -n "${TTS_PID:-}" ]]; then
    kill "$TTS_PID" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

uv sync

printf 'Preloading local voice models. First run can take a while...\n'
LOCAL_STT_MODEL="$STT_MODEL" uv run python -m local_tts_stt.warmup

printf 'Starting STT on http://127.0.0.1:%s\n' "$STT_PORT"
LOCAL_STT_MODEL="$STT_MODEL" uv run local-voice-server --mode stt --port "$STT_PORT" &
STT_PID="$!"

printf 'Starting TTS on http://127.0.0.1:%s\n' "$TTS_PORT"
PYTORCH_ENABLE_MPS_FALLBACK="${PYTORCH_ENABLE_MPS_FALLBACK:-1}" \
  uv run local-voice-server --mode tts --port "$TTS_PORT" &
TTS_PID="$!"

printf '\nConfigure Onyx Voice with:\n'
printf '  STT API Base URL: http://host.docker.internal:%s\n' "$STT_PORT"
printf '  TTS API Base URL: http://host.docker.internal:%s\n' "$TTS_PORT"
printf '  API key: blank\n\n'

wait "$STT_PID" "$TTS_PID"
