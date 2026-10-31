# Voice

> Speech-to-text (STT) and text-to-speech (TTS) for chat, through providers
> that an admin configures and activates for each direction. The Zoom provider
> row also holds the credential for Zoom Decisions.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE

---

## User experience

- **A user** presses the microphone, speaks, and the text appears in the message
  box. With auto-send on, the message sends when they stop talking. A
  transcribed message is an ordinary chat message.
- **A user** can have a reply read aloud while it streams. The text appears in
  step with the audio. They can set auto-playback and playback speed.
- **An admin** adds a provider at Admin > Voice, tests it, and activates it for
  STT, TTS or both. Two different providers can serve the two directions. A
  provider that has no TTS models cannot be activated for TTS.
- **With no active provider**, the microphone and read-aloud controls do not
  appear. Nothing fails in the middle of a chat.
- **When it fails**, the user sees an error for that one action. A provider
  that limits concurrent sessions (Zoom) returns a rate-limit error when the
  user or tenant is at its limit. A failed streaming transcription shows one
  generic message, so provider detail does not reach the client.
- **An admin who uses Zoom** enters one key and secret. It serves both Zoom
  Scribe (STT) on the Voice page and Zoom Decisions on the Decision Models
  page. Either page can create or edit it.
- **An API caller** can send one audio upload to `POST /voice/transcribe` and
  get text back, or send text to `POST /voice/synthesize` and get audio.

---

## Scope

This component owns the voice provider interface and its implementations, the
admin, user and WebSocket voice APIs, provider activation for each direction,
voice session admission, and the chat-side recording and read-aloud code. It
owns the Zoom credential on `VoiceProvider` and the rule that links it to a
decision provider.

Its neighbours own:
- [[llm-providers]]: the decision client, the Decision Models page and the
  provider listing cache.
- [[core-chat-loop]]: what happens to a transcribed message after the user
  sends it.
- [[observability]]: the `LLMFlow.STT` and `LLMFlow.TTS` tags that every
  provider call carries through `traced_llm_call`.
- [[chat-frontend]]: the message box and the chat page that host the voice
  controls.

---

## Architecture

**Provider interface.** `voice/interface.py:VoiceProviderInterface` requires
`transcribe`, `synthesize_stream`, credential validation, and the voice and
model listings. Streaming STT, streaming TTS, a session policy and a target
URI are optional capabilities. `voice/factory.py:get_voice_provider` maps
`provider_type` to a class in `voice/providers/`.

**STT path.**
```
useVoiceRecorder -> POST /voice/ws-token (60 s, single use, 10 per minute)
  -> WS /voice/transcribe/stream?token=...            websocket_api.py:websocket_transcribe
       provider streams?  yes -> create_streaming_transcriber, forward TranscriptResult
                          no  -> ChunkedTranscriber: provider.transcribe per window
       native stream fails -> chunked fallback over the buffered audio, unless
                              VOICE_DISABLE_STREAMING_FALLBACK or not allows_streaming_stt_fallback()
API callers only: POST /voice/transcribe (one upload, size cap)   user_api.py:transcribe_audio
```
`VOICE_DISABLE_STREAMING_STT` forces the chunked path. `is_vad_end` in a
`TranscriptResult` drives auto-send. `ChunkedTranscriber` never sends a silent
PCM window, because STT models invent text for silence instead of returning
nothing.

**TTS path.** For auto-playback, `VoiceModeProvider` streams over
`WS /voice/synthesize/stream` as reply text arrives, so audio starts before the
reply ends. If native streaming fails, the socket falls back to chunked
synthesis. The read-aloud button on a finished message (`hooks/useVoicePlayback.ts`)
uses `POST /voice/synthesize`. Markdown is stripped on the client for the
WebSocket (`lib/voice/utils.ts:stripMarkdownForTTS`) and on the server for REST
(`server/manage/voice/text_utils.py:strip_markdown_for_tts`). Change both
together.

**Session admission.** A provider with a `session_policy()` (Zoom) runs every
transcription, REST or WebSocket, under `redis/redis_pool.py:acquire_voice_session`,
which caps concurrent sessions for each user and tenant. A REST upload opens a
live provider session too, so it takes a slot.

**Shared Zoom connection.** `db/voice.py:upsert_voice_provider` creates or
updates the `VoiceProvider` row. For Zoom, it calls
`ensure_zoom_decision_provider` when the request comes from Decision Models
(`validation_mode == "decision"`) or a linked decision provider exists. That
function keeps a `zoom_ai` `LLMProvider` with hidden DECISION models and no
default. A Voice-page save keeps an existing link in sync but never creates
one. The upsert endpoint validates the credentials live before it commits, and
rolls back everything, including the linked row, on failure.

---

## Contracts and traps

1. `audio-never-stored` **Audio is never stored, on purpose.**
   `server/manage/voice/user_api.py:transcribe_audio` reads the upload into
   memory and returns only text. `synthesize_speech` streams provider audio to
   the client and keeps no copy. The only stored result is the transcript,
   after the user sends it as a chat message. A change that writes audio to the
   file store or a log breaks a privacy property. It needs a retention decision.
2. `rest-synthesize-first-chunk` **The REST synthesize endpoint pulls the first
   chunk before it responds.** `server/manage/voice/user_api.py:synthesize_speech`
   awaits the first audio chunk, so a provider rejection becomes an HTTP error,
   not a broken 200 audio stream. Keep this order. The REST error carries the
   provider's message, extracted by `_extract_provider_error`.
3. `stream-failure-sanitized` **Streaming STT failures use one sanitized
   string.** Providers report a failed streaming transcription with
   `voice/interface.py:STREAM_FAILED_ERROR`, and the WebSocket sends only that
   string. A new provider must do the same, so provider detail stays on the
   server.
4. `custom-config-no-credentials` **`custom_config` must not hold credentials.**
   `server/manage/voice/api.py:_reject_custom_config_credentials` raises
   `VALIDATION_ERROR` when any nested key is `api_key` or `api_secret`.
   `_custom_config_to_view` also removes those keys from every response, so an
   old row cannot leak one. The key and secret live only in encrypted columns.
   Views mask the key and replace the secret with a placeholder.
5. `status-gates-controls` **`/voice/status` decides whether the controls
   appear.** `server/manage/voice/user_api.py:get_voice_status` reports a direction as enabled only when its default provider
   exists and has a key. STT and TTS defaults are separate flags
   (`is_default_stt`, `is_default_tts`), so a check for one says nothing about
   the other.
6. `tts-activation-needs-models` **TTS activation needs TTS models.**
   `server/manage/voice/api.py:_validate_tts_activation_supported` rejects a provider whose
   `get_available_tts_models()` is empty. Zoom is STT only. The factory does not
   stop this. The activation check does.
7. `session-limit-fails-fast` **A session limit fails fast.**
   `redis/redis_pool.py:VoiceSessionLimitExceeded` stops the session before the provider is called.
   REST returns `RATE_LIMITED`. The WebSocket sends an error frame. It is not a
   queue.
8. `zoom-row-locked-to-decision` **A Zoom row cannot change type, and a selected
   decision model blocks its deletion.** `db/voice.py:upsert_voice_provider`
   refuses a type change. `db/voice.py:delete_voice_provider` refuses while a
   linked decision model is selected
   ([[llm-providers#selected-decision-blocks-delete]]), and otherwise deletes
   the linked decision provider with it. The `LLMProvider.zoom_voice_provider_id` foreign
   key is `ON DELETE RESTRICT`.
9. `zoom-credential-single-source` **Zoom Decisions borrow the Voice
   credential.** The `zoom_ai` LLM provider row stores no key.
   `llm/decisions/factory.py:build_decision_client` signs a fresh token from
   the linked `VoiceProvider` for each request. Do not copy the key into the
   LLM row; one rotation must update both products.
   `server/manage/llm/api.py:_validate_zoom_decision_connection` requires the
   link on every `zoom_ai` provider, refuses a key, `api_base` or custom
   config, refuses to move a link to another connection, and lets only full
   admins create or change a link.
10. `llm-key-copy-not-linked` **A save can borrow an LLM provider's key.** When
    the request names `llm_provider_id`,
    `server/manage/voice/api.py:upsert_voice_provider_endpoint` copies that provider's
    API key into the voice row. Later key changes on the LLM provider do not
    follow.
11. `zoom-save-invalidates-listing` **Zoom saves and all deletes invalidate the
    LLM provider listing cache.**
    `server/manage/voice/api.py:upsert_voice_provider_endpoint` and
    `server/manage/voice/api.py:delete_voice_provider_endpoint` call
    `invalidate_provider_listing_cache`. The linked decision provider is part of that
    listing ([[llm-providers]]).

---

## Decisions

- **The Zoom credential lives on `VoiceProvider`.** Zoom Scribe and Zoom
  Decisions use the same Zoom key and secret. One row means one rotation
  updates both.
- **Decision setup is opt-in from Decision Models only.** A Voice-page save must
  not add decision models that an admin did not ask for.

---

## Known issues

- **TTS errors are not sanitized.** The REST synthesize error returns the
  provider's own message. The TTS WebSocket sends the exception text when the
  provider cannot be built, or when native streaming fails and
  `VOICE_DISABLE_STREAMING_FALLBACK` is set. Only the STT stream uses
  [[#stream-failure-sanitized]].

---

## Dependencies

- [[observability]]: `traced_llm_call` with the STT and TTS flows.
- [[llm-providers]]: the linked `zoom_ai` decision provider and the provider listing cache.

---

## Recipes

- `new-voice-provider` **A voice provider.** Copy `voice/providers/elevenlabs.py`; list the
  providers with `ls backend/onyx/voice/providers/`. Implement
  `VoiceProviderInterface`, add the class to `get_voice_provider`, and add its
  admin form under `web/src/views/admin/VoicePage/`. Wrap each call in
  `traced_llm_call`. Override `session_policy()` if the vendor caps concurrent
  sessions, and return `STREAM_FAILED_ERROR` on stream failures.
- `investigate-no-microphone` **Investigate "the microphone does not appear".** Call
  `GET /api/voice/status` as that user. A direction is off when no provider is
  the default for it, or the default has no key ([[#status-gates-controls]]).
- `investigate-zoom-rate-limit` **Investigate a Zoom rate-limit error.** The user or tenant holds its
  maximum number of live sessions ([[#session-limit-fails-fast]]). Before you
  suspect the vendor, count the members of the Redis sorted sets
  `voice_sessions:<scope>:tenant:<tenant_id>` and its `:user:<user_id>` key.
  Each member expires on its own, so a lost release frees its slot later.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/voice/`,
  `backend/tests/unit/onyx/server/manage/voice/`, and the voice tests in
  `backend/tests/unit/onyx/db/` and `backend/tests/unit/onyx/redis/`.
- External dependency tests: `backend/tests/external_dependency_unit/voice/`.
- Playwright: `web/tests/e2e/admin/voice/`.
- By hand: activate an OpenAI provider for both directions. Dictate a message,
  then play a reply. Deactivate it and confirm that both controls disappear.
  Connect Zoom from Decision Models and confirm that Voice shows the same
  connection with no voice default changed.
