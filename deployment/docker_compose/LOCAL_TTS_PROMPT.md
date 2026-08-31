# LOCAL TTS/STT IMPLEMENTATION PROMPT

## Goal

Add local Mac voice support to Onyx for STT with MLX-Whisper and TTS with Kokoro. Use OpenAI-compatible HTTP APIs. Run Onyx in Docker Compose. Run voice models on the macOS host so MLX-Whisper can use Apple Metal.

Do not run MLX-Whisper in a normal Linux Docker container on Mac. It falls back to CPU and becomes much slower.

## Backend Task

Find voice backend code in these areas:

- `backend/onyx/server/manage/voice/models.py`
- `backend/onyx/server/manage/voice/api.py`
- `backend/onyx/server/manage/voice/user_api.py`
- `backend/onyx/server/manage/voice/websocket_api.py`
- `backend/onyx/voice/factory.py`
- `backend/onyx/voice/providers/openai.py`
- `backend/onyx/db/voice.py`
- `backend/onyx/db/models.py`

Add provider type `local_openai`.

Required backend behavior:

- Reuse OpenAI-compatible STT/TTS request paths.
- Allow blank API keys for `local_openai`.
- Use a dummy bearer token internally if the OpenAI client requires a token.
- Store split URLs in `custom_config.stt_api_base` and `custom_config.tts_api_base`.
- Keep shared `api_base` as a fallback when present.
- Allow private-network URLs for `local_openai`, including `host.docker.internal`.
- Still block link-local metadata targets during URL validation.
- Validate local STT activation has an STT URL.
- Validate local TTS activation has a TTS URL.
- Check `/health` on configured local base URLs during provider save/test.
- Report `/voice/status` enabled without API key when local URLs exist.
- Let WebSocket STT/TTS auth checks accept blank-key local providers.
- Do not use OpenAI realtime WebSocket for local STT. Use existing chunked REST fallback.

OpenAI provider changes:

- Support separate STT and TTS base URLs.
- Keep official OpenAI behavior unchanged.
- Add local defaults: `mlx-whisper`, `kokoro`, `af_heart`.
- Add a small static Kokoro voice list.

Add unit tests for local defaults, split URLs, dummy key, and non-streaming STT.

## Frontend Task

Find frontend voice code in these areas:

- `web/src/app/admin/voice/page.tsx`
- `web/src/views/admin/VoicePage/index.tsx`
- `web/src/views/admin/VoicePage/shared.tsx`
- `web/src/lib/voice/types.ts`
- `web/src/lib/voice/svc.ts`
- `web/src/lib/voice/utils.ts`
- `web/src/i18n/messages/*.json`

Add admin UI:

- STT card: `MLX Whisper`
- TTS card: `Kokoro`
- Provider type: `local_openai`
- STT API Base URL field.
- TTS API Base URL field.
- Optional API key field.

Save local URLs in `custom_config`.

Important UI behavior:

- One local provider row can hold both STT and TTS config.
- Editing STT preserves TTS config.
- Editing TTS preserves STT config.
- A local provider is connected for a mode only when that mode has its URL.
- Local provider does not need an API key to show as connected.

Add i18n keys to all locale JSON files. English fallback is acceptable when no localized text is available.

## Local Host Voice Server Task

Create folder `local_tts_stt/`.

Add:

- `pyproject.toml`
- `local_tts_stt/local_tts_stt/__init__.py`
- FastAPI server module
- Warmup module
- `README.md`
- executable `run_local_voice.sh`

Use dependencies:

- `fastapi`
- `uvicorn[standard]`
- `python-multipart`
- `mlx-whisper`
- `kokoro`
- `soundfile`
- `numpy`

Server requirements:

- Run on macOS host.
- `GET /health` returns status and mode.
- Support modes `stt`, `tts`, and `all`.
- STT routes: `POST /v1/audio/transcriptions` and `POST /audio/transcriptions`.
- TTS routes: `POST /v1/audio/speech` and `POST /audio/speech`.
- STT accepts OpenAI-compatible multipart fields: `file`, `model`, `language`, `prompt`, `response_format`.
- STT returns JSON with `text` or plain text when requested.
- TTS accepts OpenAI-compatible JSON fields: `model`, `input`, `voice`, `response_format`, `speed`.
- TTS returns audio bytes with correct media type.

STT details:

- Use `mlx_whisper.transcribe`.
- Default real model: `mlx-community/whisper-large-v3-turbo`.
- Map aliases `mlx-whisper` and `whisper-1` to the configured real model.
- Allow `LOCAL_STT_MODEL` override.
- Store uploaded audio in a temp file.

TTS details:

- Use Kokoro `KPipeline`.
- Default voice: `af_heart`.
- Infer language code from voice prefix.
- Cache pipelines by language code.
- Return MP3 by default.
- Use `ffmpeg` for MP3 conversion.
- Support WAV for warmup/testing.

Warmup requirements:

- Preload STT by transcribing a short silent WAV.
- Preload TTS by synthesizing a short sentence.
- `run_local_voice.sh` must run warmup before starting servers.

Shell runner requirements:

- Use Bash strict mode.
- Auto-install missing Homebrew packages without prompts: `ffmpeg`, `espeak-ng`.
- Run `uv sync`.
- Start STT on `${STT_PORT:-6601}`.
- Start TTS on `${TTS_PORT:-6602}`.
- Print Onyx admin URLs using `host.docker.internal`.
- Stop both child servers on Ctrl-C.

## Docker Build Reliability

If Docker build cannot fetch npm packages behind a corporate registry:

- Do not commit npm tokens.
- Use BuildKit secrets for host `.npmrc`.
- Let `web/Dockerfile` accept `BUN_CONFIG_REGISTRY`.
- Mount the `.npmrc` secret only during `bun install`.
- Default registry should remain public npm unless a local override supplies another value.

If `next build` cannot fetch Google Fonts:

- Remove build-time `next/font/google` dependency.
- Use CSS font-family fallback stacks in root layout.
- Preserve existing CJK font variable composition.

If backend Docker build fails while pre-downloading `tiktoken`:

- Make that pre-download non-fatal.
- Emit a warning instead of failing the image build.

## Verification

Run backend tests:

```bash
uv run pytest -q backend/tests/unit/onyx/voice/providers/test_openai_provider.py
```

Run Python checks:

```bash
uv run ruff check backend/onyx/server/manage/voice backend/onyx/voice/providers/openai.py local_tts_stt/local_tts_stt
uv run ruff format --check backend/onyx/server/manage/voice backend/onyx/voice/providers/openai.py local_tts_stt/local_tts_stt
python3 -m py_compile local_tts_stt/local_tts_stt/server.py local_tts_stt/local_tts_stt/warmup.py
bash -n local_tts_stt/run_local_voice.sh
```

Run Docker build check:

```bash
cd deployment/docker_compose
docker compose up --build --no-start
```

Run Docker-to-host reachability checks after local servers start:

```bash
docker exec onyx-api_server-1 python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:6601/health', timeout=3).read().decode())"
docker exec onyx-api_server-1 python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:6602/health', timeout=3).read().decode())"
```

Expected health responses show `status: ok`.

Functional checks:

- Configure Admin > Voice with local STT/TTS URLs.
- Confirm provider test/save succeeds.
- Use mic in chat. Local STT logs must show 200.
- Use read-aloud on an assistant response. Local TTS logs must show 200.

## Troubleshooting

Onyx logs:

```bash
docker logs -f onyx-api_server-1
```

Local server logs are in the terminal running `run_local_voice.sh`.

If local logs show `POST /audio/transcriptions 404`, add no-`/v1` route aliases.

If Onyx logs show `Connection error`, confirm `run_local_voice.sh` is running and Docker health checks pass.

If first voice use is slow, confirm warmup ran before server startup. First script run can still be slow due model downloads.
