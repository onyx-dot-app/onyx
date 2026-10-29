# LLM Providers

> Admins configure LLM providers, their models and the default model for each
> task, and a factory resolves the model for every call. The factory builds
> `LitellmLLM`, the wrapper that owns streaming, retries and managed-key cost
> tracking.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE. The access check is CE code, but user groups are EE, so
restricting a provider to groups needs EE.

---

## User experience

- **An admin** adds a provider at Admin > Language Models (OpenAI, Anthropic,
  Bedrock, Ollama, an OpenAI-compatible endpoint and others), enters
  credentials, and picks which models users can see. They choose the default
  chat model and, optionally, a router model for Auto mode. They set the task
  models for chat naming and search selection on Chat Preferences, and the
  image captioning (vision) model on Index Settings.
  When they create a provider or change its key, the page runs a test call
  first. A bad credential or an unknown model fails the test, and nothing is
  saved. The page runs this test, not the save API.
- **An admin** sets up decision providers at Admin > Decision Models and may
  select one decision model. It starts unset and never inherits the chat model.
- **A user** picks a model per chat, or keeps the agent's model, or the
  workspace default. Tokens and, where the model supports it, reasoning stream
  in. A short network failure before the first token retries without notice.
  A failure after the first token ends the answer where it stopped.
- **When a user's choice is not allowed** (a provider restricted to other
  groups or other agents, or a deleted model), the chat silently uses the
  workspace default. The user sees no error.
- **An admin who deletes a provider** clears it from every agent and personal
  default that used it. Those chats fall back to the workspace default.

---

## Scope

This component owns provider and model configuration, provider access rules,
the per-task model designations ("model flows"), model resolution for each
call, the `LitellmLLM` wrapper and its request shaping, the model catalog,
the LiteLLM patches, cooperative cancellation of a model call, and Decision
Models.

Its neighbours own:
- [[observability]]: `LLMFlow` tags, generation spans, tracing providers and
  the `user_usage` rollup.
- [[rate-and-usage-limits]]: the managed-key cost cap that `_track_llm_cost`
  feeds.
- [[llm-gateway]]: exposing these providers as an external API.
- [[chat-preferences]]: the task-model selectors on the Chat Preferences page
  and the personal default model setting.
- [[voice]]: the Zoom credential that Zoom Decisions sign with.
- [[image-generation]]: the hidden provider rows that image-generation
  configs own.

---

## Architecture

**Per-turn resolution.** `llm/factory.py:get_llm_for_persona` picks the model in
this order: the session's `LLMOverride` (by `model_configuration_id`, else
provider name plus model), then `Persona.default_model_configuration_id`, then
the CHAT default. It then calls `db/llm.py:can_user_access_llm_provider`. A
missing model or a failed access check falls back to the CHAT default with a
log warning, not an error.

**Access matrix.** `can_user_access_llm_provider` decides who may use a
provider. MANAGE_LLMS bypasses the group check, never the agent check.

| Provider has | `is_public` true | `is_public` false |
|---|---|---|
| no groups, no agents | every user | only MANAGE_LLMS holders |
| agents only | every user, only with a listed agent | only with a listed agent |
| groups only | every user | group members and MANAGE_LLMS holders |
| groups and agents | every user, only with a listed agent | group check and agent check |

**Building the client.** `llm/factory.py:llm_from_provider` resolves
`max_input_tokens` (configured value, else the model catalog) and temperature
(session, then model default, then user default, then `GEN_AI_TEMPERATURE`). It
rejects a model without CHAT capability. It calls `policy_fn` with the
resolved provider to get the `LlmRequestPolicy`. `llm/factory.py:get_llm`
merges the request and env headers, then the provider headers
(`_build_provider_extra_headers`), then the policy headers and model kwargs.

**Model flows.** `LLMModelFlow` rows join a `ModelConfiguration` to an
`LLMModelFlowType`, with an `is_default` flag. A row without the flag is a
capability (the model supports chat, vision or decisions). The default row is
the designation for that task. The partial unique index
`ix_one_default_per_llm_model_flow` allows at most one default per flow type
across all providers.

| Factory | When no default exists |
|---|---|
| `get_default_llm` (CHAT) | raises `ValueError` |
| `get_default_llm_with_vision` | returns `None`; image summarization is off |
| `get_default_utility_llm` (CHAT_NAMING, SEARCH_SELECTION) | returns `None`; caller uses its own model |
| `get_search_selection_llm` | returns the caller's `fallback`, never the naming model |
| `get_contextual_rag_llm_for_search_settings` (CONTEXTUAL_RAG) | returns `None` when the search settings name no model either |
| `get_decision_client` | returns `None` |

`get_default_utility_llm` and `get_decision_client` run the managed-key cost
check themselves and skip the user access check. An admin designation applies
to every user.

**Setting a default.** `db/llm.py:update_default_model` clears the old default
and sets the new one in one transaction. CHAT_NAMING, SEARCH_SELECTION and
CRAFT are pointer flows: `db/llm.py:update_default_pointer_model` requires a
CHAT-capable model and creates the flow row if it is missing. Setting a default
makes the model visible, except for the flows in `_HIDDEN_DEFAULT_FLOW_TYPES`.
So a hidden model can be the naming, selection or decision model and stay out
of the chat picker.

**The wrapper.** `llm/multi_llm.py:LitellmLLM` has two layers. `invoke_raw` and
`stream_raw` return provider chunks (`ModelResponseStream`). `invoke` and
`stream` add the event layer (`GenerationEvent`, see `backend/onyx/llm/README.md`)
and open a generation span. The agent runtime
(`agents/runtime.py`) uses `stream`; the gateway uses the raw layer and opens
its own spans. `_completion` shapes the request
for each model family and provider. When a provider 400 names a reasoning or
temperature kwarg, `_completion` retries without it (`_retry_attempts`). It
never drops tools, tool choice or messages. `_track_llm_cost` counts cost only when
usage limits are on and the key is Onyx-managed. Per-user usage comes from
spans, not from this call.

**Env-only provider config.** Some `custom_config` keys have no LiteLLM kwarg
(for example, some cloud credentials). `LitellmLLM` puts them into
`os.environ` for one call through `llm/multi_llm.py:temporary_env_and_lock`.
That call holds the write side of the process-wide `_env_rwlock`, and every
other call holds the read side, so no concurrent call sees the injected
secrets. `invoke_raw` streams and reassembles such a call to release the write
lock after connection setup. Lock waits count against the call deadline.
`server/security/store.py:llm_custom_config_env_injection_enabled` is always
false on multi-tenant: process-wide env vars are safe only when one admin owns
the deployment. With injection off, the keys are dropped with a warning and no
call takes the lock.

**Model catalog.** `llm/model_catalog.py` is the source for prices, limits and
capabilities. It fetches each provider's `price_table/<provider>.json` from the
`main` branch on GitHub, with a TTL and a negative cache. The vendored copy is
the floor when the fetch fails or `ONYX_AIRGAPPED` is set.

**Router models.** A `ModelConfiguration` with `is_router` (for example
`openrouter/auto`) has no price. `LitellmLLM._routed_model` reads the model the
router served, and `_track_llm_cost` prices that model. An admin cost override
on the router row still wins.

**Decision Models.** A decision model answers typed questions (predicate,
choice, score) with probabilities, through
`llm/decisions/client.py:DecisionClient`, not through LiteLLM. Decision
providers (the `DecisionProvider` enum in `llm/decisions/models.py`) save
through `db/llm.py:upsert_decision_provider`. Of the flow rows, it adds or
removes only DECISION rows. It keeps chat settings, defaults, visibility and
access, and adds new models hidden. The selection is the DECISION default row.
It is opt-in and never chosen by discovery or provider creation. No product
code calls `get_decision_client`. Only the admin and Zoom test endpoints build
a client.

---

## Contracts and traps

1. `stale-config-id-no-name-lookup` **A stale `model_configuration_id` falls
   back to the default, never to a name lookup.** Provider display names are
   not unique, so a name match can pick a different provider
   (`llm/factory.py:_resolve_provider_and_model`).
2. `access-check-matches-listing` **Keep the access check in the factory and in
   `db/llm.py` the same.** The factory passes
   `has_global_permission(user, MANAGE_LLMS)` as `can_manage_llms`. A mismatch
   with the listing endpoints shows a model in the picker that silently
   resolves to the default model.
3. `request-policy-merges-last` **The request policy merges last.**
   `llm/factory.py:get_llm` applies `policy_headers` and `policy_model_kwargs`
   after every other source, so incognito retention suppression wins. A new
   merge step must come before it.
4. `retry-before-first-chunk` **Retry only before the first chunk.**
   `llm/multi_llm.py:LitellmLLM.stream_raw` retries the transient LiteLLM errors while
   `yielded_any` is false, up to `1 + LLM_FIRST_CHUNK_MAX_RETRIES` attempts. A
   retry after content would duplicate output. The boundary is the first
   chunk, even a role-only one.
5. `tool-call-deltas-by-index` **Accumulate tool-call deltas by `index`.** A raw
   chunk carries fragments: the first one for an index has the id and name,
   later ones only argument text. Use
   `llm/model_response.py:MessageAccumulator` or
   `ee/onyx/server/gateway/stream_bridge.py:merge_tool_call_delta`. On the
   event layer, execute a call only after `ToolCallEndEvent`.
6. `raw-caller-owns-span` **A raw-layer caller owns the span and its
   `LLMFlow`.** `invoke` and `stream` open a span tagged from
   `GenerationContext.flow`. Without a flow, the span is `UNTAGGED_INVOKE` or
   `UNTAGGED_STREAM`. `invoke_raw` and `stream_raw` open none
   ([[observability]]).
7. `provider-api-mask-and-invalidate` **A provider API path masks, restores and
   invalidates.** Every provider view in `server/manage/llm/api.py` passes
   through `_mask_provider_credentials`. On update,
   `_restore_masked_custom_config_values` turns a masked value back into the
   stored one; a path without it saves the mask as the credential. Every write
   calls `server/manage/llm/provider_cache.py:invalidate_provider_listing_cache`,
   because the non-admin listings are cached per tenant and group set. Writes
   outside this API call it too, such as the persona API (the listing includes
   each agent's default model) and the Community downgrade. Search for
   `invalidate_provider_listing_cache` to find every caller.
8. `personal-default-string-format` **Deleting a provider clears personal
   defaults by string match.** `User.default_model` stores
   `<display name>__<provider type>__<model>`. `db/llm.py:remove_llm_provider`
   clears matching values, and for a nameless provider it matches both the
   empty name and the provider id. A new writer of that string must use the
   same format.
9. `selected-decision-blocks-delete` **A selected decision model blocks
   deletion.** `server/manage/llm/api.py:delete_llm_provider` and
   `db/voice.py:delete_voice_provider` refuse while the selection is on that
   provider. `db/llm.py:upsert_decision_provider` refuses to drop the selected model. Clear the
   selection first.
10. `image-gen-rows-hidden-from-list` **Image-generation configs own hidden
    provider rows.** Each config has its own `LLMProvider` named
    `Image Gen - <image_provider_id>`. The provider list hides these rows unless
    the caller passes `include_image_gen=true`. A client that syncs providers,
    such as the Terraform provider, must pass it, or it reads those rows as
    deleted. [[image-generation]] explains why its writes do not use the
    provider upsert.
11. `env-lock-every-litellm-call` **Every LiteLLM call goes through the env
    lock.** A new path that calls LiteLLM outside
    `llm/multi_llm.py:LitellmLLM._completion`
    skips `temporary_env_and_lock`. On a single-tenant deployment with
    injection on, it can then read another provider's injected secrets. Keep
    `llm_custom_config_env_injection_enabled` false on multi-tenant
    ([[multi-tenancy]]).
12. `agent-cancelled-base-exception` **`AgentCancelled` is a `BaseException`.**
    `llm/cancellation.py:AgentCancelled` bypasses `except Exception`, so a Stop
    is not handled as a model or tool error. Catch it on purpose. A broad
    `except BaseException` swallows a Stop. On cancellation, `LitellmLLM.stream`
    emits a `GenerationErrorEvent` with `stop_reason="aborted"` and records the
    partial content and usage.
13. `claude-thinking-tool-loop` **Claude thinking stays on for the whole tool
    loop.** For the Anthropic reasoning styles, `_completion` sends thinking on
    every request, so the effort setting holds across tool turns.
    `llm/litellm_singleton/monkey_patches.py:_patch_anthropic_keeps_requested_thinking`
    stops LiteLLM from dropping it on tool turns. Do not remove the patch as
    cleanup. Claude behind an OpenAI-style gateway is the exception:
    `llm/multi_llm.py:_prompt_in_tool_loop` skips reasoning there, because the
    signed thinking block cannot always be replayed.
14. `flow-rows-not-deprecated-columns` **Read defaults from the `LLMModelFlow`
    rows, not the deprecated columns.** `LLMProvider.default_model_name`,
    `is_default_provider`, `is_default_vision_provider` and
    `default_vision_model` are not kept in step and can hold stale values.
    `ModelConfiguration.supports_image_input` is deprecated for default
    selection (use the VISION flow), but it is still the per-model image
    override: `llm_from_provider` passes `True` when it is set, else `None`, and
    `LitellmLLM` then asks the catalog. So an admin can turn on vision for a
    model that the catalog does not know, but never turn it off. Chat image
    replay (`chat/prompt_formatting.py:prepare_model_messages`) reads the resolved
    `LLMConfig.supports_images`. Do not remove that read.

---

## Decisions

- **Designations live in `LLMModelFlow`, not on the provider.** One table
  carries both capability and default for each task. A new task needs no new
  columns, and the partial index guards the one-default rule.
- **Utility designations bypass picker access.** Chat naming and search
  selection are workspace settings that run for every user. Document ACLs,
  tenant policy and the cost cap still apply.
- **Decisions use their own client.** Decision protocols return structured
  probabilities that LiteLLM does not model. Requests have a finite timeout
  and no automatic retries.

---

## Known issues

- **Unverified column width for new flow types.** The `llm_model_flow_type`
  column is `Enum(native_enum=False)` with no CHECK constraint. The migration
  that created it imports the live enum, so the VARCHAR length depends on when
  it ran. Check the column width before you add a flow type with a longer name.
- **Cancellation is cooperative.** The wrapper checks the signal between
  reads, so a stalled provider holds the turn until the stall timeout.

---

## Dependencies

- [[observability]]: generation spans and `LLMFlow` tags.
- [[rate-and-usage-limits]]: the managed-key cost check and counter.
- [[authorization]]: `MANAGE_LLMS` for the group-check bypass.
- [[voice]]: the Zoom credential for Zoom Decisions.
- [[multi-tenancy]]: env injection stays off on multi-tenant deployments.

---

## Recipes

- `new-provider` **A provider.** Copy the OpenRouter entries; list them with
  `git grep -n -i openrouter backend/onyx/llm web/src/lib/languageModels`. The
  name enum is `llm/constants.py:LlmProviderNames`, and the web registry of
  modals is `web/src/lib/languageModels/constants.ts`. Add header handling to
  `_build_provider_extra_headers` or `PROVIDERS_WITH_SPECIAL_API_KEY_HANDLING`
  if it needs it. Add a model-discovery endpoint in `server/manage/llm/api.py`
  if it can list models. Copy `web/src/sections/modals/languageModels/OpenRouterModal.tsx` for the admin
  modal; list
  the modals with `ls web/src/sections/modals/languageModels/`.
- `new-task-designation` **A task designation.** Add the `LLMModelFlowType` value (see Known issues).
  Write the factory with an explicit no-default behaviour, and add the value to
  `_HIDDEN_DEFAULT_FLOW_TYPES` if the model must stay out of the picker. Copy
  CHAT_NAMING: `git grep -n CHAT_NAMING backend/onyx` lists its writer, factory
  and admin route.
- `new-call-site` **An LLM call site.** Copy a `get_default_utility_llm` caller; list them with
  `git grep -n get_default_utility_llm backend/onyx`. Set
  `GenerationContext.flow`, or open `llm_generation_span` around a raw call
  ([[#raw-caller-owns-span]]). Run the cost check if the call can use a managed
  key ([[rate-and-usage-limits]]).
- `investigate-different-model` **Investigate "the chat used a different model".** Look for the factory's
  fallback warnings in the API server log: a missing
  `model_configuration_id` and a failed access check each log a warning before
  the CHAT default is used. Check the provider against the access matrix for
  that user and agent.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/llm/` and
  `backend/tests/unit/onyx/server/manage/llm/`.
- Integration tests: `backend/tests/integration/tests/llm_provider/`.
- Playwright: the provider setup and decision model specs in
  `web/tests/e2e/admin/`.
- By hand: add a provider and run the test call. Set it as default and send a
  chat message. Restrict it to a group the user is not in and confirm that the
  chat answers with the default model.
