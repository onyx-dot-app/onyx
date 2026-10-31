# LLM Gateway

> Onyx as an OpenAI- and Anthropic-compatible LLM API for external tools and
> Craft sandboxes, authorized by a scoped Personal Access Token (PAT). Onyx picks
> the provider, supplies the real credential, and meters every call.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** EE. The router mounts only in `backend/ee/onyx/main.py`, and the
tier gate requires Business or higher for the whole `/gateway` prefix.

---

## User experience

- **A developer** creates a PAT with the `use:llm_gateway` scope, from the LLM
  Gateway section of their settings or from Access Tokens. They point the OpenAI
  SDK, Codex or opencode at `<onyx-host>/api/gateway/v1`, or Claude Code at
  `<onyx-host>/api/gateway`, with the PAT as the bearer token. The client lists
  models, sends requests, and gets answers in the dialect it expects. The caller
  never sees or sets a provider key. The customer guide is
  `documentation/developers/guides/llm_gateway.mdx`.
- **A Craft session** calls the gateway for every model request of its coding
  agent. The user does nothing. The admin's provider configuration decides
  which models the agent can use.
- **An admin** turns the gateway off for the workspace at Admin > LLM Gateway.
  Then new `use:llm_gateway` PATs cannot be created, the scope is hidden, and
  external calls fail with `FEATURE_DISABLED`. Craft keeps working, because
  Craft has its own enablement setting.
- **When it fails**, the caller sees:
  - 402 `FEATURE_NOT_AVAILABLE` on every call below the Business tier;
  - `INSUFFICIENT_PERMISSIONS` for a cookie session, an API key, a PAT with no
    scopes, or a Craft PAT whose user lost Craft access;
  - 404 for a model id that the caller cannot use, with no substitute model;
  - the 429 usage-limit response from [[rate-and-usage-limits]];
  - for a stream that already started, an in-band error event in the client's
    dialect, because the HTTP status was already 200.

---

## Scope

This component owns the gateway policy: which credentials may call it and under
which flow, how a wire model id resolves to a provider model, the translation
between the client dialects and LiteLLM, the two native passthroughs, the
streaming bridge, metering of every generating path, and Craft session
attribution.

Its neighbours own the rest:
- [[llm-providers]]: provider rows, provider access checks, the factory and
  `LitellmLLM`.
- [[authorization]]: `require_permission`, scope implication and scoped PAT
  enforcement (the permission check).
- [[auth-and-identity]]: PAT resolution, which sets the token scopes that the flow
  check reads.
- [[craft-sessions]] and [[craft-sandboxes]]: the Craft PAT, the opencode
  configuration that points at the gateway, and the egress proxy that injects
  the credential.
- [[editions-and-gating]]: the tier middleware and the `/gateway` prefix entry.
- [[observability]]: the tracing pipeline that turns gateway spans into usage.
- [[chat-preferences]]: the workspace `Settings` store that holds
  `llm_gateway_enabled`.

---

## Architecture

```
POST /gateway/v1/{chat/completions | responses | messages}
  -> tier_gate middleware                                      402 below Business
  -> permission check  require_permission(USE_LLM_GATEWAY)
  -> craft_session_binder: verified Craft session id -> ContextVar   attribution only
  -> flow check  _authorize_gateway_request -> gateway_request_flow   LLMFlow or reject
             + Settings.llm_gateway_enabled for LLMFlow.LLM_GATEWAY
  -> check_token_rate_limits(user)
  -> _resolve_metered_gateway_model                                  404, cloud cost cap
  -> passthrough eligible?  yes -> openai_/anthropic_passthrough (httpx to vendor)
                            no  -> handle_* -> llm_from_provider -> invoke_raw / stream_raw
  -> llm_gateway_trace + llm_generation_span                         usage via tracing
```

**Two checks.** The permission check alone admits almost everyone:
`BASIC_ACCESS` and `CRAFT_SANDBOX` both imply `USE_LLM_GATEWAY` (`onyx/auth/permissions.py`), and an
unscoped credential is capped only by the user's own permissions. The flow
check (`server/features/build/craft_gateway.py:gateway_request_flow`) reads
`request.state.token_scopes`. PAT resolution sets it, and the OAuth provider
sets it to `READ_SEARCH` only, which the permission check rejects. It returns:
- `None` when the request has no token scopes (cookie session, API key,
  unscoped PAT);
- `LLMFlow.CRAFT_LLM_GENERATION` for a token with `CRAFT_SANDBOX`, only when
  `is_craft_enabled_for_user` passes;
- `LLMFlow.LLM_GATEWAY` for a token whose scopes imply `USE_LLM_GATEWAY`.

The flow decides two things: whether the workspace switch applies, and the tag
on every span. The gateway is the only caller of
`server/features/build/craft_gateway.py`, although the file sits in the Craft
package.

**Model ids.** The wire id is `<provider_id>/<model_name>`.
`server/gateway/model_catalog.py:build_gateway_model_catalog` builds the ids that
`GET /v1/models` returns. `ee/onyx/server/gateway/api.py:resolve_gateway_model`
parses them, checks access with `fetch_accessible_llm_provider_by_id` (no
agent, so an agent-restricted provider is excluded) and accepts only visible,
chat-capable models. Craft writes the same id format into the sandbox opencode
configuration
(`server/features/build/session/llm_config.py:build_onyx_gateway_config`).

**Translation and passthrough.** `/v1/chat/completions` always translates.
`/v1/responses` goes to the OpenAI passthrough for a true OpenAI model, and
`/v1/messages` goes to the Anthropic passthrough for a provider of type
`anthropic`. The passthroughs keep vendor features that translation loses:
server tools, hosted tools, thinking signatures and encrypted reasoning.
`ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED` and `OPENAI_GATEWAY_PASSTHROUGH_ENABLED`
(`onyx/server/gateway/configs.py`) send traffic back to translation.

**Streaming.** Starlette resumes a sync generator on different threadpool
threads, and a span's ContextVar token cannot reset across contexts.
`ee/onyx/server/gateway/stream_bridge.py:_run_bridged_stream` therefore starts
one worker thread with `start_thread_with_context` and passes SSE frames
through a queue. Each worker opens its trace and span inside that thread.
`_stream_worker_guard` is the one teardown point. It emits a sanitized in-band
error, drains trailing usage within a chunk and time limit, closes the
upstream, and records the span.

**Craft attribution.** opencode sends `X-Onyx-Craft-Session` on every call.
`server/gateway/craft_session.py:resolve_craft_session_id` keeps the id only
when the caller owns that build session, and
`server/gateway/tracing.py:llm_gateway_trace` tags the trace with it. The
header is a hint, not an identity claim, because the sandbox can edit its own
configuration.

---

## Contracts and traps

1. `no-flow-without-token-scopes` **Never infer a gateway flow from the user
   alone.** `server/features/build/craft_gateway.py:gateway_request_flow` must
   return `None` when `token_scopes` is `None`. A fallback that reads the user's permissions lets
   every cookie session and API key call the gateway.
2. `craft-token-stays-craft` **A `CRAFT_SANDBOX` token stays on the Craft
   policy.** It must produce `CRAFT_LLM_GENERATION` or nothing, never
   `LLM_GATEWAY`. Otherwise a sandbox keeps model access after an admin
   disables Craft for its user.
3. `workspace-switch-fails-closed` **The workspace switch fails closed and skips
   Craft.** `ee/onyx/server/gateway/api.py:_authorize_gateway_request`,
   `server/pat/api.py:_validate_assignable_scopes` and
   `server/pat/api.py:list_selectable_scopes` all read settings with
   `raise_on_error=True`. Change the three together. The API check applies only
   to `LLMFlow.LLM_GATEWAY`; the Craft setting controls Craft tokens.
4. `provider-credential-stays-server-side` **The provider credential never
   reaches the caller.** Both passthroughs build the upstream headers fresh,
   with the auth header from `provider.api_key`.
   `ee/onyx/server/gateway/openai_passthrough.py:_build_upstream_headers`
   forwards no inbound header, because an `OpenAI-Organization` header from the
   caller would select a billing scope in the caller's account.
   `ee/onyx/server/gateway/anthropic_passthrough.py:_build_upstream_headers`
   copies only `anthropic-version` and the allowlisted `anthropic-beta` entries.
   Upstream 401 and 403 are not in `_FORWARDABLE_STATUSES`, because they
   describe the Onyx credential. Transport errors log only the exception type,
   because the URL of a custom `api_base` can carry credentials.
5. `passthrough-no-shared-state` **A passthrough never lets one caller reach
   another caller's vendor state.** All callers share one vendor account.
   `ee/onyx/server/gateway/openai_passthrough.py:_build_upstream_request` and
   `ee/onyx/server/gateway/anthropic_passthrough.py:_build_upstream_request`
   reject each field that refers to stored vendor state, and replace each
   caller-identity field with a hash of the Onyx user id. The OpenAI check also
   forces `store` to `false`. Both reject any field that makes the vendor connect
   to a caller-chosen URL, such as MCP servers, because the vendor connects under
   the Onyx account. When a vendor adds a stateful or URL-bearing field, add it
   to both checks.
6. `unknown-model-404` **An unknown model is a 404, never a fallback.** The
   caller chose the model. A silent substitute bills a different model to a
   different budget.
7. `metered-model-resolution` **A new generating endpoint resolves through
   `ee/onyx/server/gateway/api.py:_resolve_metered_gateway_model`.**
   `resolve_gateway_model` alone skips the cloud cost cap on Onyx-managed keys.
   Call `backend/onyx/server/query_and_chat/token_limit.py:check_token_rate_limits` first.
   `count_tokens` and `/v1/models` generate nothing and skip both.
8. `generating-path-opens-span` **Every generating path opens
   `server/gateway/tracing.py:llm_gateway_trace` and
   `tracing/llm_utils.py:llm_generation_span`.** Per-user usage comes from
   these spans ([[observability]]). `invoke_raw` and `stream_raw` open no span.
   A path without the span records no usage, and an untagged one loses its
   flow.
9. `passthrough-tracks-managed-cost` **A passthrough must also call
   `llm._track_llm_cost`.** It bypasses `LitellmLLM`, so the managed-key cost
   counter does not run by itself. `llm/multi_llm.py:LitellmLLM._track_llm_cost`
   counts only Onyx-managed keys when usage limits are on. Without the call,
   the cloud cost cap undercounts. Per-user usage still comes from the spans.
10. `trace-inside-stream-worker` **Open the trace inside the stream worker.** A
    span opened in the endpoint is not active in the worker thread. Do not
    yield SSE from a generator that holds a span.
11. `kill-switch-changes-fidelity` **The kill switches change fidelity, not
    availability.** With a passthrough off, the same request still succeeds
    through translation but loses server tools and thinking signatures. A test
    that checks only success misses this.
12. `one-min-tier-many-copies` **The gateway tier lives in several places.**
    `onyx/server/gateway/configs.py:LLM_GATEWAY_MIN_TIER` feeds the `/gateway`
    entry in `ee/onyx/configs/license_enforcement_config.py:PATH_PREFIX_MIN_TIER`,
    the PAT scope tier and the Craft deployment check
    (`server/features/build/utils.py:is_craft_available_for_deployment`). The
    web copy (`web/src/lib/tiers/utils.ts:LLM_GATEWAY_MIN_TIER`) and the
    `llm_gateway_enabled` write gate in
    `backend/onyx/server/settings/api.py:admin_patch_settings`, which names
    `Tier.BUSINESS`, do not import it. Change all of them together. Do not delete the
    `PATH_PREFIX_MIN_TIER` entry: that opens the gateway below its tier.
13. `count-tokens-estimates` **`count_tokens` can return an estimate.** If the
    passthrough is unavailable,
    `ee/onyx/server/gateway/api.py:gateway_anthropic_count_tokens` uses
    `litellm.token_counter`. If that raises, it returns the JSON length divided
    by four. Clients see no error.

---

## Decisions

- **Gateway calls do not count toward the cloud API-call cap.** No gateway
  endpoint calls `check_api_key_usage`. The decision and its reason are in
  [[rate-and-usage-limits]].
- **Native passthrough over translation-only.** Translation through LiteLLM
  cannot carry vendor features that Claude Code and Codex depend on. The
  passthroughs exist for that fidelity, at the cost of separate metering code.
- **One router for both callers.** Craft does not get its own route. The flow
  check separates the two policies, and the flow tag separates their usage.
- **Sandbox credentials are injected by the egress proxy.** The opencode
  configuration carries a placeholder key. The proxy writes the Craft PAT
  for the API host ([[craft-sandboxes]]).

---

## Known issues

- **Span errors on the passthrough transport path record the exception
  message.** The passthroughs call `span.set_error` with `f"{type(e).__name__}:
  {e}"`, while the logger records only the type, for the credential reason in
  [[#provider-credential-stays-server-side]]. Whether the httpx message can
  carry the URL has not been checked.

---

## Dependencies

- [[llm-providers]]: provider access, `llm_from_provider` and `LitellmLLM`.
- [[authorization]]: `require_permission`, scope implication and scoped PAT enforcement.
- [[auth-and-identity]]: PAT resolution sets the token scopes that the flow check reads.
- [[rate-and-usage-limits]]: token budgets and the managed-key cost cap.
- [[editions-and-gating]]: the tier middleware and the `/gateway` entry in
  `PATH_PREFIX_MIN_TIER` ([[#one-min-tier-many-copies]]).
- [[observability]]: gateway spans become `user_usage` rows.
- [[chat-preferences]]: the workspace `Settings` store holds `llm_gateway_enabled`.

---

## Recipes

- `new-endpoint` **A new endpoint or dialect.** Copy `gateway_chat_completions` in
  `ee/onyx/server/gateway/api.py`; list the current endpoints with
  `git grep -n "@router" backend/ee/onyx/server/gateway/api.py`. Depend on
  `_gateway_user`, call `_authorize_gateway_request`, then
  `check_token_rate_limits`, then `_resolve_metered_gateway_model`. Open the
  trace and span in the handler or, for a stream, in the worker that
  `_run_bridged_stream` runs. Serialize with `to_wire()` so that unset fields
  stay absent.
- `new-passthrough` **A new passthrough.** Copy `ee/onyx/server/gateway/anthropic_passthrough.py`.
  Keep [[#provider-credential-stays-server-side]],
  [[#passthrough-no-shared-state]], [[#generating-path-opens-span]] and
  [[#passthrough-tracks-managed-cost]]. Add an env kill switch in
  `onyx/server/gateway/configs.py` and an eligibility function next to
  `is_anthropic_passthrough_eligible`.
- `new-caller-type` **A new caller type.** Return a new `LLMFlow` from
  `gateway_request_flow`, not a boolean, so usage stays attributable.
- `investigate-cannot-reach` **Investigate "my tool cannot reach the gateway".** Match the error to the
  list in User experience. A 402 is the tier. `INSUFFICIENT_PERMISSIONS` means
  the flow check returned `None`: check that the credential is a PAT with the
  `use:llm_gateway` scope, or a Craft PAT whose user has Craft. A 404 means the
  model id is not in `GET /api/gateway/v1/models` for that PAT: check provider
  group and agent restrictions in [[llm-providers]].
- `setup-manual-call` **Set up a gateway call by hand.** Create a `use:llm_gateway` PAT, call
  `GET /api/gateway/v1/models`, then send a message with a returned id. Usage
  reaches `GET /api/user/usage` only after the tracing flush, so poll for up to
  a minute. The real-client tests need a running API server; see
  `backend/tests/integration/tests/gateway_clients/README.md`.

---

## Verification

- Unit tests: `backend/tests/unit/ee/onyx/server/gateway/`,
  `backend/tests/unit/onyx/server/gateway/`, and the flow check tests in
  `backend/tests/unit/onyx/server/features/craft/`.
- Real clients: `backend/tests/integration/tests/gateway_clients/`.
- Metering: the gateway usage test in
  `backend/tests/integration/tests/streaming_endpoints/` polls until the
  tracing flush writes usage.
- By hand: after a call, check that the usage page shows the tokens. Turn the
  workspace switch off and confirm the PAT gets `FEATURE_DISABLED` while a
  Craft session still answers.
