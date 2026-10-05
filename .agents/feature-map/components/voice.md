# Voice

> Speech-to-text (STT) and text-to-speech (TTS) for chat: a pluggable provider
> abstraction, an admin surface that configures and activates one provider per
> direction, and REST/WebSocket endpoints the chat frontend calls to record a
> spoken message or hear a reply read aloud.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** tools
**Edition:** CE
**Owns:**
`backend/onyx/voice/` (`factory.py`, `interface.py`, `providers/`, `audio_utils.py`),
`backend/onyx/server/manage/voice/` (`api.py`, `user_api.py`, `websocket_api.py`,
`text_utils.py`, `models.py`), `backend/onyx/db/voice.py`,
`web/src/app/admin/voice/`, `web/src/views/admin/VoicePage/`,
`web/src/providers/VoiceModeProvider.tsx`, `web/src/hooks/useVoiceRecorder.ts`,
`web/src/sections/input/MicrophoneButton.tsx`

---

## 1. What the user experiences

A user can press a microphone button to speak a chat message instead of
typing it; the recognized text fills the input box (or is auto-sent, if the
user enabled that setting) the way a typed message would. A user can also have
an assistant's reply read aloud, with the visible text advancing in sync with
the audio.

Both directions require an admin to have configured and activated a provider
first. Until then, the microphone button and read-aloud control are hidden
(`GET /voice/status`); nothing errors mid-conversation for a capability that
was never turned on.

---

## 2. Surfaces

### Admin HTTP endpoints (`/admin/voice`, `server/manage/voice/api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/admin/voice/providers` | `list_voice_providers` | |
| POST | `/admin/voice/providers` | `upsert_voice_provider_endpoint` | Create/update; validates credentials live via `voice_provider.validate_credentials()` before commit, rolling back on failure. |
| DELETE | `/admin/voice/providers/{provider_id}` | `delete_voice_provider_endpoint` | |
| POST | `/admin/voice/providers/{provider_id}/activate-stt` \| `/deactivate-stt` | | Sets/clears `is_default_stt`. |
| POST | `/admin/voice/providers/{provider_id}/activate-tts` \| `/deactivate-tts` | | Sets/clears `is_default_tts`; gated by `_validate_tts_activation_supported`. |
| POST | `/admin/voice/providers/test` | `test_voice_provider` | Validates a candidate config without saving it. |
| GET | `/admin/voice/providers/{provider_id}/voices`, `/admin/voice/voices` | `get_provider_voices`, `get_voices_by_type` | Lists selectable voices for the admin UI. |

### Client-facing HTTP/WS endpoints (`/voice`, `server/manage/voice/user_api.py` and `websocket_api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/voice/status` | `get_voice_status` | `{stt_enabled, tts_enabled}`, each true only if a default provider exists *and* has an API key. |
| POST | `/voice/transcribe` | `transcribe_audio` | One-shot upload (multipart), max `MAX_AUDIO_SIZE` (25 MB). |
| WS | `/voice/transcribe/stream` | `websocket_transcribe` | Streaming STT; requires a short-lived token from `/voice/ws-token`. |
| POST | `/voice/synthesize` | `synthesize_speech` | Streams synthesized audio (`audio/mpeg`) back as an HTTP chunked response. |
| WS | `/voice/synthesize/stream` | `websocket_synthesize` | Streaming TTS, used by `VoiceModeProvider` for low-latency read-aloud. |
| PATCH | `/voice/settings` | `update_voice_settings` | Per-user `auto_send`, `auto_playback`, `playback_speed`. |
| POST | `/voice/ws-token` | `get_ws_token` | Issues a 60-second, single-use, rate-limited (10/min/user) token for the two WebSocket routes. |

### Config

No environment variables gate this component; everything is admin-configured
through `VoiceProvider` rows (§3). `interface.py:STREAM_FAILED_ERROR` is the
one sanitized client-facing string every provider must use for a failed
streaming session, so provider-specific error detail never reaches the client.

---

## 3. Data model

- `VoiceProvider` (`db/models.py`, owned via `db/voice.py`): `provider_type`
  (`"openai"`, `"azure"`, `"elevenlabs"`, or `"zoom"`), encrypted `api_key` and
  `api_secret` (`SensitiveValue`/`EncryptedString`), `api_base`,
  `custom_config` (JSONB), `stt_model`, `tts_model`, `default_voice`, and two
  independent booleans `is_default_stt` / `is_default_tts`.
- **STT and TTS defaults are independent of each other and independent per
  row.** One provider row can be the STT default, a different row the TTS
  default; `fetch_default_stt_provider` and `fetch_default_tts_provider`
  (`db/voice.py`) query on the two flags separately. A provider that does not
  support TTS activation is rejected before `is_default_tts` can be set
  (`server/manage/voice/api.py:_validate_tts_activation_supported`).
- Per-user settings (`auto_send`, `auto_playback`, `voice_playback_speed`) live
  on the `User` row, updated by `db/voice.py:update_user_voice_settings` and
  read back in `synthesize_speech` as the fallback speed when a request omits
  one. `MIN_VOICE_PLAYBACK_SPEED` / `MAX_VOICE_PLAYBACK_SPEED` (`db/voice.py`)
  bound the allowed range.
- No table stores audio or transcripts. See §5 for what that implies.

---

## 4. How it works

### Provider abstraction

`VoiceProviderInterface` (`voice/interface.py`) is an ABC with required async
methods `transcribe(audio_data, audio_format) -> str` and
`synthesize_stream(text, voice, speed) -> AsyncIterator[bytes]`, plus
`validate_credentials()`, `get_available_voices()`,
`get_available_stt_models()`, `get_available_tts_models()`. Optional
capabilities default to unsupported: `supports_streaming_stt()`,
`supports_streaming_tts()`, `session_policy()` (returns `None` if
unconstrained), and `create_streaming_transcriber` /
`create_streaming_synthesizer` (raise `NotImplementedError` unless overridden).
`voice/factory.py:get_voice_provider` dispatches on `normalize_provider_type`
to one of four implementations in `voice/providers/`:

| `provider_type` | Class | Notes |
|---|---|---|
| `openai` | `providers/openai.py:OpenAIVoiceProvider` | STT + TTS |
| `azure` | `providers/azure.py:AzureVoiceProvider` | STT + TTS |
| `elevenlabs` | `providers/elevenlabs.py:ElevenLabsVoiceProvider` | STT + TTS |
| `zoom` | `providers/zoom.py:ZoomVoiceProvider` | STT only (constructed with no `tts_model`) |

Every provider's STT and TTS call is wrapped in `traced_llm_call` with
`LLMFlow.STT` or `LLMFlow.TTS` (`onyx/tracing/flows.py`); confirmed in all four
provider files (e.g. `providers/openai.py`,
`providers/zoom.py` for STT only). See [[observability]].

### Audio format handling

`voice/audio_utils.py` provides PCM16 helpers shared across providers:
`Pcm16Resampler` (linear-interpolation resampling that preserves phase and the
last sample across streamed chunks, with a required `flush()` at stream end),
`resample_pcm16` for a one-shot buffer, and `pcm16_to_wav` to wrap raw PCM16 in
a WAV container for providers that need a full audio file rather than a raw
stream. Both `_validate_pcm16` calls reject a buffer with a partial trailing
sample rather than silently truncating or shifting it.

### Speech to text (recording to text)

1. The frontend's `MicrophoneButton`
   (`web/src/sections/input/MicrophoneButton.tsx`) uses
   `useVoiceRecorder` (`web/src/hooks/useVoiceRecorder.ts`), which opens
   `/voice/transcribe/stream` (WebSocket) or falls back to `/voice/transcribe`
   (REST) for one-shot uploads.
2. `websocket_api.py:websocket_transcribe` requires the short-lived token from
   `/voice/ws-token`, then streams audio chunks to the provider's
   `create_streaming_transcriber` session (`StreamingTranscriberProtocol`),
   forwarding `TranscriptResult`s (`voice/interface.py`) back to the client as
   they arrive, including `is_vad_end` for auto-send.
3. `user_api.py:_transcribe_with_provider` applies the provider's
   `session_policy()` (if any) as a per-user, per-tenant concurrency guard via
   `redis_pool.py:acquire_voice_session` / `release_voice_session`, so a REST
   upload is capped the same way a WebSocket session is. A provider with no
   policy (`session_policy() -> None`) skips this admission check entirely.
4. The final transcript is handed to `onTranscription` in `MicrophoneButton`,
   which writes it into the same chat input state a typed message would use
   (`onTranscription: (text: string) => void`). Voice input does not bypass
   the normal turn path: a transcribed message is sent through
   `send-chat-message` exactly like typed text. See [[core-chat-loop]].

### Text to speech (reply to audio)

1. `VoiceModeProvider` (`web/src/providers/VoiceModeProvider.tsx`) drives
   read-aloud. It calls `/voice/synthesize/stream` (WebSocket, dev-direct at
   `/voice/synthesize/stream` or proxied at `/api/voice/synthesize/stream`) as
   assistant text streams in, so audio can start before the full reply is
   generated.
2. Text is sanitized before synthesis: `text_utils.py:strip_markdown_for_tts`
   strips Markdown so the TTS voice does not read out formatting characters.
3. `user_api.py:synthesize_speech` (the REST fallback) resolves the default
   TTS provider and voice/speed (explicit request values, else
   `provider_db.default_voice` / `user.voice_playback_speed`), pulls the first
   audio chunk before returning the `StreamingResponse` (so a provider
   rejection surfaces as a real HTTP error rather than a broken audio stream),
   then streams the remainder.
4. `VoiceModeProvider` paces revealed text to the audio using an estimated
   characters-per-second rate (`BASE_CHARS_PER_SECOND`, `REVEAL_LEAD_SECONDS`)
   when the provider gives no exact duration, so the visible transcript and
   the audio stay roughly in sync.

---

## 5. Contracts and invariants

1. **No configured provider means the capability is absent, not an error
   mid-turn.** `/voice/status` is the single source of truth the frontend uses
   to show or hide voice controls; `transcribe_audio` and `synthesize_speech`
   both return a `VALIDATION_ERROR` naming the missing provider if called
   directly with none configured, rather than a mid-stream failure.
2. **Credentials never reach the client or the LLM.** Voice provider
   `api_key`/`api_secret` are `EncryptedString` columns; the admin API only
   returns view models (`VoiceProviderView`) built by `_provider_to_view`,
   which does not echo the raw key back. `_reject_custom_config_credentials`
   (`server/manage/voice/api.py`) actively strips credential-shaped keys out
   of `custom_config` before it is stored, so a well-meaning admin cannot
   accidentally leak a secondary key into a JSONB blob that later gets
   returned in a listing.
3. **Audio is not persisted, and this is a deliberate privacy property, not an
   oversight.** `transcribe_audio` reads the upload into memory
   (`user_api.py`), passes it to the provider, and returns only the
   resulting text; the audio bytes are never written to the file store or any
   table. `synthesize_speech` streams provider-generated audio straight to the
   client (`audio_stream()` generator) and keeps no copy. The only persisted
   artifact of a voice interaction is the transcript text itself, and only
   because it becomes an ordinary chat message through the normal turn path
   (owned by [[chat-persistence]], not this component).
4. **A provider's session policy is a hard cap, not a soft one.** When
   `session_policy()` is non-`None`, `acquire_voice_session` /
   `release_voice_session` (`redis/redis_pool.py`) enforce a per-tenant and
   per-user concurrency limit for both the REST and WebSocket paths; a
   `VoiceSessionLimitExceeded` becomes a `RATE_LIMITED` `OnyxError`, not a
   silent queue.
5. **TTS activation is conditionally allowed, not universal.** A provider that
   cannot support the platform's TTS streaming contract fails
   `_validate_tts_activation_supported` before `is_default_tts` can be set,
   independent of whether it is a valid STT default.

---

## 6. Relationships

**Depends on**
- [[core-chat-loop]]: a voice-transcribed message enters the turn through the
  same `send-chat-message` path as typed text; this component does not have
  its own turn model.
- [[llm-providers]]: shares the `EncryptedString`/`SensitiveValue` credential
  pattern used for `LLMProvider`, though `VoiceProvider` is its own table, not
  reused rows.
- [[observability]]: every STT/TTS provider call is wrapped in
  `traced_llm_call` with `LLMFlow.STT` / `LLMFlow.TTS`.
- [[chat-frontend]]: `MicrophoneButton` and `VoiceModeProvider` are chat-page
  components that call into this component's endpoints.

**Depended on by**
- Nothing else in the codebase calls into voice; it is a leaf feature
  reachable only from the chat input/output UI.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a fifth voice provider | `voice/factory.py:get_voice_provider`'s dispatch, `web/src/views/admin/VoicePage/` provider forms, and whether it needs `session_policy()`/streaming overrides |
| changes `TranscriptResult` or the WebSocket message shape | `websocket_api.py:_forward_transcripts`/`_receive_transcripts` and the frontend's `useVoiceRecorder` parsing |
| changes audio resampling (`Pcm16Resampler`) | any provider that streams PCM16 at a non-native sample rate; a phase bug here corrupts audio without raising an error |
| changes `is_default_stt`/`is_default_tts` semantics | `db/voice.py:fetch_default_stt_provider`/`fetch_default_tts_provider` and `/voice/status`, since the frontend gates the mic/read-aloud UI on that endpoint |
| adds any audio or transcript persistence | this document's §5 privacy invariant becomes false; update it in the same change, and check whether that needs a retention/consent story |
| changes voice session admission limits | `redis/redis_pool.py:acquire_voice_session`/`release_voice_session` and `VoiceSessionPolicy.handler_seconds`, which the REST and WebSocket paths both depend on |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/unit/onyx/voice
cd backend && uv run pytest tests/unit/onyx/db/test_voice.py
cd backend && uv run pytest tests/unit/onyx/redis/test_voice_session_guard.py
cd backend && uv run pytest tests/unit/onyx/server/manage/voice/test_voice_api_validation.py
cd backend && uv run pytest tests/unit/onyx/server/manage/voice/test_voice_api_secrets.py
cd backend && uv run pytest tests/unit/onyx/server/manage/voice/test_voice_provider_api.py
cd backend && uv run pytest tests/external_dependency_unit/voice/test_openai_streaming.py
```

```bash
cd web && npx playwright test tests/e2e/admin/voice/disconnect-provider.spec.ts
cd web && npx playwright test tests/e2e/admin/voice/stt-only.spec.ts
cd web && npx playwright test tests/e2e/admin/voice/zoom-provider.spec.ts
```

No integration test targets this component specifically.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. At `http://localhost:3000/admin/voice`, add and activate an OpenAI provider
   for both STT and TTS.
3. In chat, press the microphone button, speak, and confirm the recognized
   text appears in the input box.
4. Send a message and confirm the assistant's reply can be read aloud with
   text advancing roughly in sync with audio.
5. Deactivate the provider and confirm `/voice/status` reports both
   capabilities disabled, and the mic/read-aloud controls disappear.

### What "working" looks like

- `/voice/status` accurately reflects whether a default STT/TTS provider with
  a real API key exists.
- A transcribed message reaches the assistant exactly as if typed, with no
  special-cased turn behavior.
- No audio bytes appear in logs, the file store, or any database table after
  a transcribe/synthesize round trip.

---

## 9. Footguns

- **STT and TTS defaults are set independently**, so it is easy to configure
  one direction and forget the other; `/voice/status` is the only place both
  are checked together.
- **A provider with a session policy silently rate-limits before the provider
  is even called.** `VoiceSessionLimitExceeded` looks like a generic failure
  to a caller that does not know the provider has an account-level
  concurrency quota.
- **Reference `zoom.py` supports STT only**; constructing it with a
  `tts_model` expectation (e.g. activating it as a TTS default) is rejected by
  `_validate_tts_activation_supported`, not by the factory.
- **`custom_config` is credential-scrubbed on write, not on read.**
  `_reject_custom_config_credentials` prevents a credential-shaped key from
  being stored in the first place; it is not a runtime filter on existing
  rows, so a config created before this check existed could still carry one.
- **Audio format assumptions are provider-specific.** `audio_utils.py`'s PCM16
  helpers only apply to providers that stream raw PCM16; a provider that
  exchanges compressed formats (e.g. webm/opus) does its own handling and does
  not use `Pcm16Resampler`.

---

Cross-links: [[tools-framework]], [[core-chat-loop]], [[streaming-protocol]],
[[file-store-and-user-files]], [[chat-frontend]], [[llm-providers]],
[[observability]], [[access-control]], [[editions-and-gating]]
