# Image Generation

> A chat tool that turns a prompt (and optionally reference images) into one or more
> generated images through a pluggable provider, plus the admin surface that
> configures which provider and model the tool uses.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** tools
**Edition:** CE
**Owns:**
`backend/onyx/image_gen/` (`factory.py`, `generation.py`, `interfaces.py`, `providers/`,
`exceptions.py`), `backend/onyx/tools/tool_implementations/images/`,
`backend/onyx/server/features/image_generation/`,
`backend/onyx/server/manage/image_generation/`, `backend/onyx/db/image_generation.py`,
`web/src/app/admin/image-generation/`, `web/src/views/admin/ImageGenerationPage/`

---

## 1. What the user experiences

In chat, the model can call an image generation tool when the user asks for an
image. The user sees a "generating image" indicator, then the finished image
inline in the assistant's reply. The model can also edit or extend an
existing image (one the user attached, or one it generated earlier in the
conversation) instead of generating from scratch.

An admin configures the capability at `/admin/image-generation`: pick a
provider (OpenAI, Azure, or Vertex AI), supply credentials, and choose it as
default. The model list in the admin form includes the GPT Image 2.5 variants
(`gpt-image-2.5-flare`, `gpt-image-2.5-sunburst`) next to `gpt-image-2`, `gpt-image-1.5`, and
`gpt-image-1` (`web/src/views/admin/ImageGenerationPage/constants.ts`).
Until an admin does this, the tool does not appear at all; the model
never sees an image generation tool it cannot use, and a user is never told
"image generation failed" for a capability that was simply never turned on.

---

## 2. Surfaces

### HTTP endpoints

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/admin/image-generation/test` | `test_image_generation` (`server/manage/image_generation/api.py`) | Validates a candidate provider/credentials pair by generating a test image. |
| POST | `/admin/image-generation/config` | `create_config` | Creates a config; clone mode (reuse an existing LLM provider's credentials) or new-credentials mode. |
| GET | `/admin/image-generation/config` | `get_all_configs` | Lists configs for the admin table. |
| GET | `/admin/image-generation/config/{image_provider_id}/credentials` | `get_config_credentials` | Returns credentials with the API key masked (`models.py:_mask_api_key`). |
| PUT | `/admin/image-generation/config/{image_provider_id}` | `update_config` | |
| DELETE | `/admin/image-generation/config/{image_provider_id}` | `delete_config` | |
| POST/DELETE | `/admin/image-generation/config/{image_provider_id}/default` | `set_config_as_default` / `unset_config_as_default` | Only one config can be default at a time (`db/image_generation.py:set_default_image_generation_config`). |
| POST | `/image-generation/generate` | `generate_image` (`server/features/image_generation/api.py`) | The client-facing generation call used outside the chat tool loop (see §4). |

### Environment / config

| Name | Where | Effect |
|---|---|---|
| `IMAGE_MODEL_NAME`, `IMAGE_MODEL_PROVIDER` (`configs/app_configs.py`) | `ImageGenerationTool.__init__` defaults | Fallback model/provider if a call site does not pass its own; in practice the tool is always constructed from the DB default config (`generation.py:_default_provider_and_model`). |

There is no feature flag gating this component; availability is entirely a
function of whether a default `ImageGenerationConfig` exists with valid
credentials (§4, §5).

---

## 3. Data model

- `ImageGenerationConfig` (`db/models.py`, owned here via `db/image_generation.py`):
  primary key `image_provider_id` (a static string like `openai_gpt_image_1`), a
  foreign key to `ModelConfiguration`, and `is_default`. Only one row can have
  `is_default=True`; `create_image_generation_config__no_commit` and
  `set_default_image_generation_config` both clear every other default in one
  atomic `UPDATE` before setting the new one.
- Credentials are not stored on `ImageGenerationConfig` itself. Each config
  points at a `ModelConfiguration`, which points at an `LLMProvider`
  (`db/models.py`), whose `api_key` is an `EncryptedString`/`SensitiveValue`. This
  reuses the same LLM-provider credential storage as chat models; see
  [[llm-providers]].
- Generated images are not modeled as their own table row. They are files in the
  shared file store, tagged `FileOrigin.CHAT_IMAGE_GEN`; see [[file-store-and-user-files]]
  and §5 below.

---

## 4. How it works

### Provider abstraction

`ImageGenerationProvider` (`image_gen/interfaces.py`) is an ABC with one
required method, `generate_image(prompt, model, size, n, quality,
reference_images, **kwargs)`, plus `validate_credentials` /
`build_from_credentials` classmethods and two capability properties,
`supports_reference_images` and `max_reference_images`. Three providers
implement it, registered in `image_gen/factory.py:PROVIDERS`:

| `ImageGenerationProviderName` | Class | Reference-image support |
|---|---|---|
| `openai` | `providers/openai_img_gen.py:OpenAIImageGenerationProvider` | Yes, up to 16 (`gpt-image-*` and `dall-e-2`, the latter capped at 1) |
| `azure` | `providers/azure_img_gen.py:AzureImageGenerationProvider` | Same as OpenAI, via an Azure deployment name |
| `vertex_ai` | `providers/vertex_img_gen.py:VertexImageGenerationProvider` | Yes, up to 14, via Gemini image editing (`genai.Client`) instead of LiteLLM's `image_edit` |

All three route plain generation through `litellm.image_generation` /
`litellm.image_edit` and wrap each provider call in
`tracing.llm_utils.traced_llm_call` with `LLMFlow.IMAGE_GENERATION` or
`LLMFlow.IMAGE_EDIT` (`onyx/tracing/flows.py`). See [[observability]].

### Admin configuration

`create_config` / `update_config` (`server/manage/image_generation/api.py`)
accept either a "clone" mode (reuse credentials from an existing
`LLMProvider` via `source_llm_provider_id`) or a "new credentials" mode (raw
`api_key`/`api_base`/etc). Either way the backend creates a fresh `LLMProvider`
row and `ModelConfiguration` row, then an `ImageGenerationConfig` pointing at
them (`db/image_generation.py:create_image_generation_config__no_commit`).
`validate_credentials` (`image_gen/factory.py`) is called before persisting,
and `test_image_generation` lets an admin generate a throwaway test image
before saving.

### Resolving the default config

`generation.py:_default_provider_and_model` loads the `ImageGenerationConfig`
where `is_default=True`
(`db/image_generation.py:get_default_image_generation_config`), reads its
`ModelConfiguration.llm_provider` for credentials, and calls
`validate_credentials`. `is_image_generation_configured(db_session)` wraps this
in a boolean; `ensure_image_generation_configured()` wraps it in an exception
for use as a fast pre-check.

### The chat tool

`ImageGenerationTool` (`tools/tool_implementations/images/image_generation_tool.py`):

1. `is_available(db_session)` returns `is_image_generation_configured(db_session)`.
   A tool that is not available is not registered for the turn at all; the
   model never sees it. See [[tools-framework]].
2. `run()` parses `prompt`, optional `shape`, and optional
   `reference_image_file_ids`. Reference file ids are deduplicated, capped at
   `self.img_provider.max_reference_images`, and rejected up front
   (`ToolCallException`) if the active provider does not support reference
   images at all (`_resolve_reference_image_file_ids`).
3. Referenced files are loaded via `file_store/utils.py:load_chat_file_by_id`
   and must be `ChatFileType.IMAGE`; unsupported formats or non-image files
   raise a `ToolCallException` with a distinct `llm_facing_message`.
4. Generation runs on a background thread
   (`ImageGenerationTool.run:generate_all_images`) so the main thread can emit
   `ImageGenerationToolHeartbeat` packets every `HEARTBEAT_INTERVAL` (5s) while
   waiting, preventing the SSE connection from going idle. See
   [[streaming-protocol]].
5. On completion, images are saved via `file_store/utils.py:save_files`
   (base64 path, `FileOrigin.CHAT_IMAGE_GEN`) and an
   `ImageGenerationFinal(images=...)` packet is emitted with each image's
   `file_id`, a frontend URL (`build_frontend_file_url`), and the
   provider-revised prompt.
6. The frontend's `ImageToolRenderer`
   (`web/src/app/app/message/messageComponents/renderers/ImageToolRenderer.tsx`)
   assembles the displayed state from the packet stream: it finds the
   `image_generation_start` packet, collects `image_generation_final` packets
   (the frontend's `PacketType` enum names the finished-image packet
   `IMAGE_GENERATION_TOOL_DELTA`, but its wire value is `"image_generation_final"`,
   matching the backend's `ImageGenerationFinal.type`), and treats a
   `SECTION_END`/`ERROR` packet as the end of generation.

### Turn-level effect: a stopping tool

`ImageGenerationTool.NAME` is listed in `tools/built_in_tools.py:STOPPING_TOOLS_NAMES`.
In `chat/llm_loop.py`, once any tool call in a cycle matches a stopping tool
name, `ran_image_gen` is set `True` for the rest of that turn; the next cycle
forces `tool_choice = ToolChoiceOptions.NONE` and offers no tools
(`llm_loop.py:run_llm_loop`, the `elif out_of_cycles or ran_image_gen` branch), and the reminder text injected before that final answer is
`IMAGE_GEN_REMINDER` instead of the normal citation/file reminder
(`llm_loop.py:select_reminder_text`). In effect, image generation is always the
last tool call of a turn: the model must answer immediately afterward rather
than chaining further tool calls.

### The standalone generation endpoint

`server/features/image_generation/api.py:generate_image` is a separate,
non-tool HTTP path (`POST /image-generation/generate`) used by callers outside
the chat turn loop. It streams whitespace keepalive bytes
(`_KEEPALIVE_INTERVAL_S`) while a bounded thread pool
(`_generation_executor`, capped by `_admission_semaphore` at
`_MAX_PENDING_GENERATIONS`) runs `generate_images_with_default_config`, then
emits one JSON envelope with the base64 images or an error code. It does not
save files or go through `ImageGenerationTool`; the caller owns what happens to
the returned base64 data.

---

## 5. Contracts and invariants

1. **No configured provider means the capability is absent, not an error
   mid-turn.** `ImageGenerationTool.is_available` gates registration before the
   turn starts; `generate_image` (the standalone endpoint) still fails fast
   with a 404-mapped `ImageGenerationNotConfiguredError` via
   `ensure_image_generation_configured()` before it commits to a streaming
   response.
2. **Credentials never reach the client or the LLM.** The admin API only ever
   returns a masked API key (`server/manage/image_generation/models.py:_mask_api_key`,
   first 4 / last 4 characters). The tool receives full credentials
   server-side only, resolved fresh per generation
   (`generation.py:_default_provider_and_model`).
3. **A provider that does not support reference images must reject them
   explicitly, not silently ignore them.**
   `ImageGenerationTool._resolve_reference_image_file_ids` raises a
   `ToolCallException` naming the provider rather than dropping the images and
   generating from text alone.
4. **Generated images are scoped to the chat session that produced them.**
   `ImageGenerationTool` receives `chat_session_id` from `tool_constructor.py` and
   passes it through `save_files` so every image is stamped. The access rule is in
   [[file-store-and-user-files]] §5. Dropping the session id anywhere on that path
   produces an unscoped row.
5. **`response_format` is model-dependent.** `generation.py:response_format_for_model`
   omits the param entirely for `gpt-image-*` models (they reject it) and
   requests `"b64_json"` for every other model, since inline base64 is the only
   format this component's downstream storage step accepts.

---

## 6. Relationships

**Depends on**
- [[tools-framework]]: `ImageGenerationTool` implements `Tool[None]` and is
  registered/gated the same way every other tool is; `is_available` is the
  hook this component uses.
- [[llm-providers]]: image generation credentials are `LLMProvider` rows,
  reusing that encrypted-credential storage and the clone-from-existing-provider
  admin flow.
- [[file-store-and-user-files]]: generated and reference images are saved and
  loaded through the shared file store (`save_files`, `load_chat_file_by_id`).
- [[streaming-protocol]]: `ImageGenerationToolStart`, `ImageGenerationToolHeartbeat`,
  and `ImageGenerationFinal` are `Packet` payloads on the same SSE stream as
  every other tool.
- [[observability]]: every provider call is wrapped in `traced_llm_call` with
  `LLMFlow.IMAGE_GENERATION` / `LLMFlow.IMAGE_EDIT`.

**Depended on by**
- [[core-chat-loop]]: `llm_loop.py` special-cases this tool via
  `STOPPING_TOOLS_NAMES` and `IMAGE_GEN_REMINDER`, so a change to the tool's
  name or registration affects turn control flow, not just tool behavior.
- [[chat-frontend]]: `ImageToolRenderer` and the packet processor consume this
  component's packet types by name.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a fourth image provider | `image_gen/factory.py:PROVIDERS`, `web/src/views/admin/ImageGenerationPage/forms/` (needs a matching form + `getImageGenForm.tsx`), and whether it needs `supports_reference_images`/`max_reference_images` overrides |
| changes the packet schema (`ImageGenerationToolStart`, `Heartbeat`, `Final`, `GeneratedImage`) | `web/src/app/app/services/streamingModels.ts`'s `PacketType` string values (they must match `StreamingType` in `streaming_models.py` exactly) and `ImageToolRenderer.tsx` |
| changes what counts as a "stopping tool" or removes `ImageGenerationTool` from `STOPPING_TOOLS_NAMES` | `llm_loop.py`'s cycle-forcing logic and `IMAGE_GEN_REMINDER` text; a tool leaving this list can now chain further tool calls in the same turn |
| changes how a config becomes "default" | `db/image_generation.py:set_default_image_generation_config`'s atomic clear-then-set; a race here would let two configs claim default simultaneously |
| touches `FileOrigin.CHAT_IMAGE_GEN` access rules | [[file-store-and-user-files]] and [[access-control]]; `access.py:_user_can_access_chat_image_gen_file` grants the session owner, or anyone when the session is public and not deleted, so any change must preserve that scoping |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/unit/onyx/image_gen
cd backend && uv run pytest tests/unit/onyx/tools/test_image_generation_reference_resolution.py
cd backend && uv run pytest tests/unit/onyx/server/manage/image_generation/test_image_generation_api.py
cd backend && uv run pytest tests/unit/onyx/server/features/image_generation/test_image_generation_endpoint.py
cd backend && uv run pytest tests/external_dependency_unit/tools/test_image_generation_tool.py
cd backend && uv run pytest tests/integration/tests/image_generation/test_image_generation_config.py
cd backend && uv run pytest tests/integration/tests/image_generation/test_image_generation_tool_visibility.py
cd backend && uv run pytest tests/integration/tests/tools/test_image_generation_streaming.py
```

```bash
cd web && bun run playwright image-generation-content
```

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. At `http://localhost:3000/admin/image-generation`, add an OpenAI (or Azure /
   Vertex) config with a real API key, and mark it default.
3. Start a new chat and ask for an image. Confirm the "generating" indicator
   appears, then the image renders inline.
4. Remove the default config and confirm the model no longer offers to
   generate images (no tool call, no error message).

### What "working" looks like

- With no default config, `generate_image` is absent from the tools sent to
  the LLM and the standalone endpoint returns a 404-style
  `ImageGenerationNotConfiguredError`.
- With a default config, a chat request for an image produces a heartbeat
  stream followed by one `ImageGenerationFinal` packet, and the model does not
  call another tool in the same cycle.

---

## 9. Footguns

- **Images generated before session stamping are not session-scoped.** They
  keep the old behaviour so they still render; see [[file-store-and-user-files]]
  §9. Only images generated after the stamp was added follow the session's
  sharing.
- **The frontend's finished-image packet type is named
  `ImageGenerationToolDelta` even though it corresponds to the backend's
  `ImageGenerationFinal` and carries the wire value `"image_generation_final"`,
  not a delta.** Matching by name across the backend/frontend boundary will
  mislead; match by the string literal instead.
- **`image_generation_heartbeat` has no corresponding entry in the frontend's
  `PacketType`/`ImageGenerationToolObj` union** (verified by its absence from
  `web/src/app/app/services/streamingModels.ts`). The renderer derives
  "still generating" from the presence of a start packet with no end packet,
  not from the heartbeat itself; a change relying on the frontend reading
  heartbeat content should confirm it is actually wired up.
- **Image generation always ends the turn's tool-calling.** Because
  `ImageGenerationTool` is a stopping tool, a persona or prompt expecting the
  model to generate an image and then immediately call another tool (e.g.
  search to verify something about it) will not get that behavior within one
  cycle.
- **`n` (number of images) is fixed to `1` in the chat tool path**
  (`image_generation_tool.py:_generate_image`, called with `n=1`); the
  standalone `/image-generation/generate` endpoint is the only path that
  accepts `n` up to `_MAX_IMAGES` (4).

---

Cross-links: [[tools-framework]], [[core-chat-loop]], [[streaming-protocol]],
[[file-store-and-user-files]], [[chat-frontend]], [[llm-providers]],
[[observability]], [[access-control]], [[editions-and-gating]]
