# LLM Providers

> How Onyx reaches a language model: provider and model configuration, per-flow
> default resolution, the per-turn factory, the LiteLLM wrapper and its streaming
> contract, retries, and cost and trace instrumentation.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** core-loop (platform surface, consumed by every LLM caller)
**Edition:** CE, with EE gating on visibility (`is_public`) and groups
**Owns:**
`backend/onyx/llm/factory.py`, `interfaces.py`, `multi_llm.py`, `model_response.py`,
`tool_parsing.py`, `cost.py`, and the rest of `backend/onyx/llm/`,
`backend/onyx/db/llm.py`, `db/llm_usage.py`,
`backend/onyx/server/manage/llm/api.py`,
`backend/onyx/tracing/flows.py`, `llm_utils.py`, `setup.py`, `provider_config.py`,
`dynamic_processor.py`, `backend/onyx/server/manage/tracing/api.py`

---

## 1. What the user experiences

An admin adds an LLM provider (OpenAI, Anthropic, Bedrock, Ollama, a custom
OpenAI-compatible endpoint, and more) under **Admin > LLM**, enters credentials,
and picks which of the provider's models are visible to end users. The admin
then marks one model as the default for chat, and optionally separate defaults
for vision, contextual RAG, chat-naming, and Craft.

A user picks a model per chat session, or leaves it on the assistant's default,
or leaves that on the workspace default. Whichever call actually reaches the
model, the user experience is the same: streamed tokens, and (if the provider
supports it) streamed reasoning. If a request to the provider times out or the
connection drops before the provider yields any chunk, Onyx retries retryable
errors for up to `1 + LLM_FIRST_CHUNK_MAX_RETRIES` attempts. The user sees a
short delay. If all attempts fail, the error propagates. Once any chunk has
been yielded, the error propagates with no retry, and a drop mid-answer shows
as a stream cut off.

An admin with usage tracking enabled can see LLM cost and per-user usage in the
observability surfaces. An admin can connect Braintrust or Langfuse to see full
traces of every model call, tagged by what the call was for.

---

## 2. Surfaces

### HTTP endpoints (`server/manage/llm/api.py`)

Admin router, prefix `/admin/llm`:

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/admin/llm/provider` | `list_llm_providers` | All configured providers. |
| GET | `/admin/llm/provider/{id}` | `get_llm_provider` | |
| PUT | `/admin/llm/provider` | `put_llm_provider` | Create or update. Restores masked credential fields via `_restore_masked_custom_config_values`. |
| DELETE | `/admin/llm/provider/{id}` | `delete_llm_provider` | |
| POST | `/admin/llm/test` | `test_llm_configuration` | Fires one real call against the given config before it is saved. |
| POST | `/admin/llm/test/default` | `test_default_provider` | Tests the currently configured default. |
| POST | `/admin/llm/default` | `set_provider_as_default` | Sets the CHAT default. |
| POST | `/admin/llm/default-vision` | `set_provider_as_default_vision` | Rejects a model that fails `model_supports_image_input`. |
| POST/DELETE | `/admin/llm/default-chat-naming` | `set_provider_as_default_chat_naming` / `clear_default_chat_naming` | |
| POST/DELETE | `/admin/llm/default-craft` | `set_provider_as_default_craft` / `clear_default_craft` | Craft has no capability check; see §9. |
| GET | `/admin/llm/built-in/options`, `/built-in/options/{provider_name}` | `fetch_llm_options`, `fetch_llm_provider_options` | The well-known-provider catalogue. |
| GET | `/admin/llm/custom-provider-names` | `fetch_custom_provider_names` | Names for the custom provider option. |
| GET | `/admin/llm/auto-config` | `get_auto_config` | |
| GET | `/admin/llm/vision-providers` | `get_vision_capable_providers` | |
| GET | `/admin/llm/provider-contextual-cost` | `get_provider_contextual_cost` | |
| POST | `/admin/llm/{bedrock,ollama,openrouter,lm-studio,litellm,bifrost,nebius-tokenfactory,openai-compatible,vercel-ai-gateway,portkey}/available-models` | per-vendor model discovery | Each calls the vendor's model-list API live. Several also sync the discovered models into the DB when the request carries a `provider_id` (`sync_model_configurations`). |

Non-admin router, prefix `/llm`:

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/llm/provider` | `list_llm_provider_basics` | Providers visible to the caller, credentials stripped. |
| GET | `/llm/provider/{provider_id}/models` | `list_llm_provider_models` | One page of a provider's models (`offset`, `query`, optional `persona_id`). |
| GET | `/llm/persona/{persona_id}/providers` | `list_llm_providers_for_persona` | The providers/models a given assistant may use, group- and persona-filtered. |

Every provider view returned by any of the above masks `api_key` and sensitive
`custom_config` entries via `_mask_provider_credentials` (`server/manage/llm/api.py`).
The raw key never appears in a response body.

### Tracing admin endpoints (`server/manage/tracing/api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/admin/tracing/providers` | `list_tracing_providers` | Braintrust / Langfuse config, env or DB. |
| POST | `/admin/tracing/providers` | `upsert_tracing_provider_endpoint` | Upsert, not PUT. |
| DELETE | `/admin/tracing/providers/{provider_type}` | `disconnect_tracing_provider` | |
| POST | `/admin/tracing/providers/test` | `test_tracing_provider` | Not per provider type; the type is in the body. |
| POST | `/admin/tracing/providers/{provider_type}/adopt-env` | `adopt_env_tracing_provider` | Copies an env-configured provider into the DB. |

`_reject_if_multi_tenant` (`tracing/api.py`) blocks all of these under cloud;
see §9.

### Environment configuration

| Variable | Default | Effect |
|---|---|---|
| `GEN_AI_TEMPERATURE` | 0 (`configs/model_configs.py`) | Last-resort temperature when nothing else sets one. |
| `LLM_FIRST_CHUNK_MAX_RETRIES` | 2 | (`configs/chat_configs.py`) Retries allowed before the first streamed chunk. |
| `LLM_SOCKET_READ_TIMEOUT` | 60 | (`configs/chat_configs.py`) Socket read timeout. It is also the default stall timeout between streamed chunks and, as `LLM_INVOKE_TIMEOUT_S`, the default total timeout of `invoke`. |
| `BRAINTRUST_API_KEY`, `BRAINTRUST_PROJECT`, `BRAINTRUST_API_URL` | | Env fallback for Braintrust tracing. |
| `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST` | | Env fallback for Langfuse tracing. |
| `USER_USAGE_TRACKING_ENABLED` | true | Gates the per-user usage recorder, independent of Braintrust/Langfuse. |
| `TRACING_CONFIG_CACHE_TTL_SECONDS` | 30 | How often `DynamicTracingProcessor` re-reads the effective config. |
| `MULTI_TENANT` | | Forces tracing config to env-only; blocks the tracing admin API. |

### Admin UI

`web/src/app/admin/language-models/page.tsx` is the provider list and
edit surface. It is a thin client over the endpoints above.

---

## 3. Data model

- **`LLMProvider`** (`db/models.py`): one row per configured connection.
  `provider`, encrypted `api_key` (`EncryptedString`), `api_base`, `api_version`,
  `custom_config` (JSONB, for provider-specific fields like Bedrock's access
  keys), `deployment_name`, `is_public`, `is_auto_mode`. Four columns are
  **deprecated in favour of `LLMModelFlow`** and kept only for back-compat
  reads: `default_model_name`, `is_default_provider`, `is_default_vision_provider`,
  `default_vision_model`. Do not write to them for new behavior; see §9.
- **`ModelConfiguration`** (`db/models.py`): one row per model under a provider.
  `is_visible` gates end-user selectability, `max_input_tokens` is an optional
  override, `display_name` / `custom_display_name` control the UI label, and
  `reasoning_effort_default` / `reasoning_effort_max` bound reasoning requests.
  `supports_image_input` is **deprecated in favour of `LLMModelFlow` with the
  `VISION` flow type**; see §9.
- **`LLMModelFlow`** (`db/models.py`): joins a `model_configuration_id` to an
  `llm_model_flow_type`, with `is_default`. Two constraints matter:
  - `uq_model_config_per_llm_model_flow_type`: one row per (model, flow type).
  - `ix_one_default_per_llm_model_flow`: a **partial unique index** on
    `llm_model_flow_type` where `is_default = true`. This guarantees at most
    one default per flow across the whole table, not per provider. It does not
    guarantee that a default exists. Seed a default separately.
- **`LLMModelFlowType`** (`db/enums.py`): `CHAT`, `VISION`, `CONTEXTUAL_RAG`,
  `REASONING`, `CHAT_NAMING`, `CRAFT`. Stored on `llm_model_flow` as
  `Enum(LLMModelFlowType, native_enum=False)`, which SQLAlchemy renders as a
  plain `VARCHAR` column with **no `CHECK` constraint**
  (`alembic/versions/f220515df7b4_add_flow_mapping_table.py:upgrade`,
  `db/models.py:LLMModelFlow`). See §9 for why this matters.
- **`TracingProviderConfig`** (`db/models.py`, via `db/tracing.py`): one row per
  tracing provider (Braintrust, Langfuse) with `enabled`, encrypted `api_key`,
  and a `config` JSONB blob.
- **`UserUsage`** (`db/models.py`, via `db/llm_usage.py`): per-user rolling
  window of `input_tokens`, `output_tokens`, `cache_read_tokens`,
  `cache_creation_tokens`, `cost_cents`, upserted with
  `build_usage_upsert_values` (additive merge, not overwrite).

---

## 4. How it works

### 4.1 Resolving which model answers a turn: `get_llm_for_persona`

`factory.py:get_llm_for_persona(persona, user, llm_override, additional_headers, policy_fn)`
is the per-turn entry point. Resolution priority:

1. **`LLMOverride`** (a session-level override), resolved by
   `factory.py:_resolve_provider_and_model`:
   - by `model_configuration_id` if set (a stale id falls back to the default
     LLM, never to a name lookup, because provider display names are not
     unique and a name match could silently pick the wrong same-named
     provider);
   - else by `provider` name plus `model_version`.
2. The persona's `default_model_configuration_id`.
3. `get_default_llm()`, the CHAT-flow default.

After resolving `(provider, model_name)`, it fetches the caller's group
membership with `db/llm.py:fetch_user_group_ids` and checks
`db/llm.py:can_user_access_llm_provider(provider, user_group_ids, persona,
can_manage_llms)`. A failed check falls back to the default LLM rather than
raising. `can_user_access_llm_provider` documents its own decision matrix: `is_public`
gates plain user access (bypassed by `MANAGE_LLMS`), while a persona whitelist
on the provider is enforced unconditionally, even for `is_public=True`
providers.

### 4.2 Building the `LLM`: `llm_from_provider` and `get_llm`

`factory.py:llm_from_provider` resolves `max_input_tokens` (configured value,
else `get_max_input_tokens_from_llm_provider`, which reads the vendored model catalog in
`llm/price_table/` through `llm/model_catalog.py`, then falls back to
`GEN_AI_MODEL_FALLBACK_MAX_TOKENS`) and temperature, in this
precedence: session override, then `ModelConfiguration.temperature_default`,
then `user.temperature_default` (via `UserChatDefaults`), then
`GEN_AI_TEMPERATURE` (applied inside `factory.py:get_llm` if still `None`).

`factory.py:get_llm` merges extra headers and `model_kwargs` from three
sources: the request, provider-specific handling
(`_build_provider_extra_headers`, e.g. OpenRouter attribution headers or a
Bearer token pulled out of `custom_config` for providers in
`PROVIDERS_WITH_SPECIAL_API_KEY_HANDLING`), and a `policy_fn`-provided
`LlmRequestPolicy`. **The policy is merged last on purpose**, so it always wins
over everything else (used for things like incognito retention suppression).
It then constructs `onyx.llm.multi_llm.LitellmLLM`.

Other entry points, all funneling through `llm_from_provider`:
- `get_default_llm()`: fetches `db/llm.py:fetch_default_llm_model` (CHAT flow).
- `get_default_llm_with_vision()`: uses `fetch_default_vision_model`. If that
  model is absent or does not support image input, it returns `None` and image
  summarization is off. It has no fallback and does not scan other models.
- `get_llm_for_contextual_rag(model_configuration_id)` and
  `get_contextual_rag_llm_for_search_settings(search_settings)`: the latter
  uses the search settings' explicit `contextual_rag_model_configuration_id`
  if set, else `fetch_default_contextual_rag_model`.

### 4.3 Default resolution in the DB layer

`db/llm.py:fetch_default_model(db_session, flow_type)` is the shared query: it
joins `ModelConfiguration` to `LLMModelFlow` and filters on
`llm_model_flow_type == flow_type AND is_default == true`. Thin wrappers exist
per flow: `fetch_default_llm_model` (CHAT), `fetch_default_vision_model`,
`fetch_default_contextual_rag_model`, `fetch_default_chat_naming_model`,
`fetch_default_craft_model`.

Setting a new default goes through `db/llm.py:_update_default_model`, which
clears the prior `is_default` row for that flow type and sets the new one in
the same transaction, so the partial unique index is never violated mid-write.
`update_default_provider` (CHAT), `update_default_vision_provider` (checks
`model_supports_image_input` first), `update_default_chat_naming_provider`,
and `update_default_craft_provider` (creates the `LLMModelFlow` row first via
`create_new_flow_mapping__no_commit`, because nothing else ever populates a
CRAFT-flow row) all call it. `fetch_existing_models(db_session, flow_types)`
returns every `ModelConfiguration` that has an `LLMModelFlow` row matching any
flow type in the list.

### 4.4 The LiteLLM wrapper: `LitellmLLM`

`multi_llm.py:LitellmLLM` (subclass of `interfaces.py:LLM`) wraps the LiteLLM
SDK. `_completion` (`multi_llm.py:_completion`) builds the provider-specific
request: it detects model identity (Claude, Qwen, GLM), reasoning capability,
and provider quirks (Ollama, Mistral, Vertex AI), and shapes `stream_options`,
tool-calling params, and reasoning params accordingly. On a `BadRequestError`
naming a rejected kwarg, a retry ladder (`_retry_attempts`) strips that kwarg
and retries with a narrower request, up to the ladder's length.

`LLMConfig.supports_images` records the resolved image capability. A configured
`supports_image_input=True` overrides catalog values. Configured `False` permits
catalog fallback. Unknown catalog capability stays `None`. Direct client callers
can explicitly set `supports_images=False` to disable fallback.
The client shallow-copies string-valued custom configuration at construction.
It deep-copies model settings after merging deployment headers and body defaults.
Explicit image capability overrides skip catalog lookup.
Chat image replay uses this resolved capability; only `None` falls back to the DB/catalog lookup.
Capability remains fixed for that client, including across model steps.
Later caller mutations do not change the client's captured settings.

### 4.5 Streaming contract

`interfaces.py:LLM.invoke(request: GenerationRequest, context)` returns one
`AssistantMessage`. `LLM.stream(request, context)` yields `GenerationEvent` objects
(`models.py`: text, thinking, and tool-call events, then lifecycle and usage events).
`LitellmLLM` builds both on two lower-level methods. `invoke_raw` and `stream_raw` call
`_completion(..., parallel_tool_calls=True, ...)`. `stream_raw` converts each LiteLLM
chunk with `model_response.py:from_litellm_model_response_stream` into a
`ModelResponseStream`. `LitellmLLM.stream` feeds those chunks to
`model_response.py:MessageAccumulator`, which emits the ordered events.
The LLM gateway skips the event layer. It reads `stream_raw` chunks directly.

`model_response.py:ModelResponseStream` carries `choice.delta.content`,
`choice.delta.tool_calls` (a list of `ChatCompletionDeltaToolCall`
**fragments**, not complete calls), and `choice.delta.reasoning_content`. Tool
call fragments are keyed by `index`: an early chunk carries `id` and
`function.name`, later chunks for the same index carry only
`function.arguments` slices with `id`/`name` unset. Callers must accumulate by
`index` (see `model_response.py:MessageAccumulator.add`, or
`ee/onyx/server/gateway/stream_bridge.py:merge_tool_call_delta` for raw chunks);
reading any single chunk's `tool_calls` as complete
truncates the call.

Cost is tracked with `LitellmLLM._track_llm_cost` whenever a chunk's `usage`
is set, which is normally only the final chunk. It records cost only when usage
limits are enabled and the call uses an Onyx-managed API key (some providers emit a
trailing usage-only chunk with empty `choices`, handled explicitly in
`from_litellm_model_response_stream`).

### 4.6 Retries

`multi_llm.py:LitellmLLM.stream_raw` retries only on a fixed set of transient
LiteLLM exceptions: `Timeout`, `APIConnectionError`, `ServiceUnavailableError`,
`InternalServerError`. It retries **only if nothing has been yielded yet**
(`yielded_any` is `False`), up to `1 + LLM_FIRST_CHUNK_MAX_RETRIES` total
attempts. The boundary is the first yielded chunk, even an empty or role-only one. Once any chunk has reached the caller, the same exception class
propagates immediately; the stream is not restarted mid-answer.

### 4.7 Tracing

`LitellmLLM.invoke` and `LitellmLLM.stream` each open their own generation span with
`tracing/llm_utils.py:llm_generation_span`. The flow tag comes from
`GenerationContext.flow`. If the caller sets no flow, the span uses
`LLMFlow.UNTAGGED_INVOKE` or `LLMFlow.UNTAGGED_STREAM` (`tracing/flows.py`). No wrapper
adds spans on its own. `invoke_raw` and `stream_raw` open no span, so a caller of those
methods owns the span.

**This is the single most important verification signal for this component.**
`UNTAGGED_INVOKE` / `UNTAGGED_STREAM` appearing in a tracing dashboard means a
call site invoked an `LLM` without setting `GenerationContext.flow`. Any new call
site should set an explicit flow.

Explicit instrumentation:
- `tracing/llm_utils.py:llm_generation_span(llm, flow, ...)` for any call that
  goes through an `LLM` subclass; it pulls model/provider off `llm.config`.
- `tracing/llm_utils.py:traced_llm_call(flow, model, provider, ...)` for
  direct provider-SDK calls that bypass `LLM` entirely (image generation,
  voice, embeddings/rerank across the model_server boundary).

`tracing/flows.py:LLMFlow` enumerates every tagged flow: chat/agent flows
(`CHAT_RESPONSE`, `CHAT_HISTORY_SUMMARIZATION`), secondary LLM flows (query
rephrase, filter extraction, session naming), Craft (`CRAFT_LLM_GENERATION`),
the gateway (`LLM_GATEWAY`), indexing (`CONTEXTUAL_RAG_*`),
image generation, voice (`STT`/`TTS`), and cross-process calls
(`EMBED_QUERY`, `RERANK`).

`tracing/setup.py:setup_tracing()` registers a
`dynamic_processor.py:DynamicTracingProcessor`, which periodically calls
`provider_config.py:resolve_effective_tracing_config()`. That function prefers
a DB `TracingProviderConfig` row per provider (`_braintrust_from_row`,
`_langfuse_from_row`); if no row exists for a provider, it falls back to that
provider's env vars. Under `MULTI_TENANT`, DB rows are never read and only
env vars apply (`server/manage/tracing/api.py:_reject_if_multi_tenant` also
blocks the admin endpoints outright). `USER_USAGE_TRACKING_ENABLED` gates a
separate `UserUsageTracingProcessor`, independent of Braintrust/Langfuse.

---

## 5. Contracts and invariants

1. **At most one default per flow type**, enforced by the DB partial unique
   index `ix_one_default_per_llm_model_flow` (`db/models.py:LLMModelFlow`),
   not by application logic alone. `_update_default_model` clears the old
   default and sets the new one in one transaction so this index is never
   violated.
2. **Provider access is group- and persona-gated and must stay gated.** Every
   path that resolves an `LLM` for a user-initiated call must run through
   `can_user_access_llm_provider` (or fall back to the default). Do not add a
   new resolution path that skips it.
3. **The policy function is applied last.** `factory.py:get_llm` merges
   `policy_headers` / `policy_model_kwargs` after every other header/kwarg
   source. A new merge step must preserve that ordering, or a policy like
   incognito's retention suppression can be silently overridden.
4. **Tool-call deltas must be accumulated, never read as complete.**
   `ChatCompletionDeltaToolCall` fragments are keyed by `index`; a consumer
   that reads one chunk's `tool_calls` as a finished call will get a partial
   name or truncated arguments.
5. **Retries must not fire after the first yielded chunk.** `yielded_any`
   gates the retry loop in `LitellmLLM.stream_raw`. If it fires after content has
   streamed, the client would see duplicated or garbled output.
6. **Every new LLM call site needs an explicit `LLMFlow` tag.** The untagged
   sentinel flows exist as a safety net, not a substitute for instrumentation.
   Leaving a call untagged degrades cost attribution and dashboard grouping.
7. **API keys are encrypted at rest (`EncryptedString`) and must never be
   logged or returned by an endpoint.** Every provider view returned by
   `server/manage/llm/api.py` masks `api_key` and sensitive `custom_config`
   entries via `_mask_provider_credentials`.

---

## 6. Relationships

**Depends on**
- [[observability]]: the tracing framework (`generation_span`, trace
  processors) that `multi_llm.py` and `tracing/llm_utils.py` build on.
- [[rate-and-usage-limits]]: `db/usage.py` and `server/usage_limits.py`, which
  `LitellmLLM._track_llm_cost` calls into.
- [[auth-and-identity]]: `has_global_permission(user, Permission.MANAGE_LLMS)`
  gates the group-bypass path in `can_user_access_llm_provider`.

**Depended on by**
- [[core-chat-loop]]: `get_llm_for_persona` is how `build_chat_turn` resolves
  the model(s) for a turn.
- [[agents-personas]]: `Persona.default_model_configuration_id` and
  provider/persona whitelisting live on the persona.
- [[llm-gateway]]: the OpenAI-compatible gateway routes external calls through
  this same factory and tags them `LLMFlow.LLM_GATEWAY`.
- [[document-index]]: contextual RAG chunk summarization resolves its model
  through `get_contextual_rag_llm_for_search_settings`.
- Craft (`craft-sessions`): `LLMModelFlowType.CRAFT` and
  `LLMFlow.CRAFT_LLM_GENERATION` are Craft's hooks into this component.
- [[observability]]: LLM cost and per-user usage are recorded here and
  surfaced there.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a new `LLMModelFlowType` value | No database migration is required (the column is a plain `VARCHAR` with no `CHECK` constraint); but you must seed or backfill an `LLMModelFlow` row for it, add a `fetch_default_*` wrapper if callers need one, and decide the fallback behavior when no row exists yet (see §9) |
| adds a provider | `llm/well_known_providers/`, `_build_provider_extra_headers` if it needs special header handling, `PROVIDERS_WITH_SPECIAL_API_KEY_HANDLING` if it needs a synthesized Authorization header, the admin UI catalogue, and a `/admin/llm/{provider}/available-models` endpoint if it supports live model discovery |
| changes the streaming shape (`ModelResponseStream`, `Delta`) | every consumer in [[core-chat-loop]] (`llm_step.py`), `model_response.py:MessageAccumulator`, the gateway's `stream_bridge.py:merge_tool_call_delta`, and any code that assumes tool-call deltas arrive fully formed |
| changes default resolution (`fetch_default_model`, `_update_default_model`) | the partial unique index still holds after a migration or backfill; `get_default_llm` and every `get_default_*` wrapper still returns a model, not `None`, where callers assume one exists |
| adds a new LLM call site | tag it with an `LLMFlow` via `llm_generation_span` or `traced_llm_call`; verify in a Braintrust/Langfuse trace that it does not show up as `UNTAGGED_INVOKE`/`UNTAGGED_STREAM` |
| changes retry behavior in `LitellmLLM.stream_raw` | the `yielded_any` gate must still prevent post-first-chunk retries; confirm against the retryable exception tuple, which is intentionally narrow |
| changes provider credential handling | confirm masking still happens in every response path in `server/manage/llm/api.py`, and that `_restore_masked_custom_config_values` still round-trips a masked value back to the stored one on update |

---

## 8. How to verify a change

### Adding or testing a provider locally

1. Admin > LLM > Add Provider, or `PUT /admin/llm/provider` directly.
2. Use `POST /admin/llm/test` to fire one real call against the draft config
   before saving; it exercises the same `llm_from_provider` path a live turn
   would.
3. Set it as a flow default (`POST /admin/llm/default` etc.) and send a real
   chat message to confirm `get_llm_for_persona` picks it up.

### Confirming a new call site is tagged

1. Connect a tracing provider (`POST /admin/tracing/providers`, or set the
   `BRAINTRUST_*`/`LANGFUSE_*` env vars) and confirm it shows in
   `GET /admin/tracing/providers`.
2. Exercise the new call site.
3. In the tracing dashboard, confirm the span's `model_config.flow` is the new
   `LLMFlow` value, not `untagged_invoke` / `untagged_stream`.

### Tests

```bash
cd backend && uv run pytest tests/unit -k "llm or multi_llm or factory"
cd backend && uv run pytest tests/integration -k llm
```

See `backend/AGENTS.md` for authoritative commands and required env
(`@pytest.mark.secrets(...)` for any test that needs a real provider key).

### What "working" looks like

- `/admin/llm/test` succeeds against the real provider before the config is
  saved.
- Exactly one row has `is_default = true` per flow type (verify with a direct
  query against `llm_model_flow` if in doubt).
- No unexpected `UNTAGGED_INVOKE`/`UNTAGGED_STREAM` spans from the code path
  you touched.
- A forced timeout before the first chunk retries and recovers; a forced
  failure after the first chunk propagates instead of duplicating output.

---

## 9. Footguns

- **`UNTAGGED_INVOKE` / `UNTAGGED_STREAM` in a dashboard means missing
  instrumentation**, not a bug in tracing. Add an explicit `llm_generation_span`
  or `traced_llm_call` at the call site.
- **Deprecated `LLMProvider` and `ModelConfiguration` columns still exist and
  still have live values from before the `LLMModelFlow` migration**:
  `LLMProvider.default_model_name`, `is_default_provider`,
  `is_default_vision_provider`, `default_vision_model`, and
  `ModelConfiguration.supports_image_input`. Reading them instead of the
  corresponding `LLMModelFlow` row will silently reintroduce pre-migration
  behavior.
- **A flow with no seeded `LLMModelFlow` row does not default silently.**
  `fetch_default_model` returns `None` for that flow; callers like
  `get_default_llm` raise (`"No default LLM model found"`) while others
  (`fetch_default_chat_naming_model`) return `None` and the caller must decide
  the fallback. Check the specific caller before assuming a flow is
  populated. Craft in particular is what `db/llm.py:update_default_craft_provider`
  calls a "pointer flow, not a capability": nothing populates a CRAFT
  `LLMModelFlow` row automatically, so it must be created explicitly before it
  can be defaulted.
- **Retry semantics are asymmetric before and after the first chunk.** Before
  any content streams, a transient error retries transparently. After even
  one chunk has reached the caller, the same error propagates as a hard
  failure. Do not assume retry behavior is uniform across a stream's
  lifetime.
- **Provider display names are not unique.** `LLMOverride` resolution
  therefore prefers `model_configuration_id` over `(provider, model_version)`
  whenever it is available; a stale `model_configuration_id` falls back to
  the default LLM rather than attempting a name-based lookup, specifically to
  avoid picking a different same-named provider.
- **The tracing admin API and DB-backed tracing config are unavailable under
  `MULTI_TENANT`.** Env vars are the only configuration surface on cloud;
  `_reject_if_multi_tenant` enforces this at the endpoint level.

---

Related: [[core-chat-loop]], [[agents-personas]], [[observability]],
[[llm-gateway]], [[rate-and-usage-limits]], [[auth-and-identity]],
[[document-index]].
