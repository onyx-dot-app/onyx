# Local STT/TTS for Onyx on Mac

Run these servers on macOS, not in Docker. MLX-Whisper uses Apple Silicon Metal only from the host. A Linux container on Docker Desktop falls back to CPU.

## Install

```bash
brew install ffmpeg espeak-ng
cd local_tts_stt
uv sync
```

## Run Separate Servers

Simplest:

```bash
./run_local_voice.sh
```

The script installs missing Homebrew packages and preloads the models before it starts the servers.

Optional ports:

```bash
STT_PORT=6601 TTS_PORT=6602 ./run_local_voice.sh
```

Manual mode:

Terminal 1, STT:

```bash
cd local_tts_stt
LOCAL_STT_MODEL=mlx-community/whisper-large-v3-turbo uv run local-voice-server --mode stt --port 6601
```

Terminal 2, TTS:

```bash
cd local_tts_stt
PYTORCH_ENABLE_MPS_FALLBACK=1 uv run local-voice-server --mode tts --port 6602
```

## Onyx Admin Config

In Admin > Voice:

- STT provider: MLX Whisper
- STT API Base URL: `http://host.docker.internal:6601`
- TTS provider: Kokoro
- TTS API Base URL: `http://host.docker.internal:6602`
- API key: leave blank

Use `host.docker.internal` because Onyx runs in Docker and must reach services on the Mac host.

## API Shape

The servers expose the OpenAI-compatible paths used by Onyx:

- `POST /v1/audio/transcriptions`
- `POST /v1/audio/speech`

## Performance

- STT: run on macOS host for MLX/Metal acceleration.
- TTS: Kokoro is small and works on CPU, but host-run keeps setup simple.
- `run_local_voice.sh` downloads/loads models before serving requests. First script start is slower.
