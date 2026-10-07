# LLM Gateway

> Onyx as an LLM API for other tools. An OpenAI- and Anthropic-compatible
> endpoint that external clients and Craft sandboxes call with a scoped
> token, letting Onyx supply the real provider credential and record cost.
> The gateway sits in front of [[llm-providers]]; it does not duplicate the
> provider factory, the LiteLLM wrapper, or tracing, it calls into them.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** platform (EE surface, consumed by Craft and by external tools)
**Edition:** EE only. The router only exists when EE code loads
(`backend/ee/onyx/main.py`), and the path prefix is gated at
`Tier.BUSINESS` (`backend/onyx/server/gateway/configs.py`).
**Owns:**
`backend/ee/onyx/server/gateway/api.py`, `openai_passthrough.py`,
`anthropic_passthrough.py`, `stream_bridge.py`,
`backend/onyx/server/gateway/configs.py`, `models.py`, `model_catalog.py`,
`backend/onyx/server/features/build/craft_gateway.py`

**Does not own:** the provider factory, the LiteLLM wrapper, model defaults,
or tracing internals. Those belong to [[llm-providers]]; this document
covers only what is specific to exposing them as an external API.

---

## 1. What the user experiences

A developer or an admin mints a Personal Access Token (PAT) scoped to
`use:llm_gateway`, or Craft mints one automatically for a sandbox. They point
an OpenAI- or Anthropic-compatible client (the OpenAI SDK, `codex`,
`claude -p`, opencode) at `https://<onyx-host>/gateway`, using the PAT as the
bearer token. The client lists models, sends a chat/response/message request,
and gets back tokens streamed in the dialect it expects, exactly as if it
were talking to OpenAI or Anthropic directly. Onyx supplies the provider
credential; the caller never sees it and never configures it.

A Craft sandbox is the other caller. Every sandbox gets its own scoped PAT,
and its coding agent (opencode) is configured to call the gateway instead of
a real provider, so a Craft session's cost, model choice, and access all flow
through the same provider configuration an admin manages under
**Admin > LLM** (see [[llm-providers]]).

The feature requires at least the Business tier. On a lower tier, every
`/gateway/*` request is rejected with a 402 naming the required plan, before
any gateway code runs.

An admin can also turn the gateway off for the whole workspace, from
**Admin > LLM Gateway** (`web/src/app/admin/llm-gateway`) or `PATCH
/admin/settings` (`Settings.llm_gateway_enabled`, default on). While off,
every `/gateway/*` request from a third-party PAT is rejected with
`FEATURE_DISABLED`, minting a new `use:llm_gateway` PAT is rejected, and the
scope is hidden from `GET /user/pats/scopes`. A user who already has the
gateway settings page open sees a disabled notice instead of the settings
form. This switch does not affect Craft: a sandbox's `CRAFT_SANDBOX`-scoped
PAT keeps working, because admins control Craft's own gateway use through
the Craft-specific setting (§4.2).

---

## 2. Surfaces

### HTTP endpoints (router prefix `/gateway`, `backend/ee/onyx/server/gateway/api.py`, `router`)

| Method | Path | Handler | Dialect | Notes |
|---|---|---|---|---|
| GET | `/gateway/v1/models` | `gateway_list_models` | OpenAI | Lists every model the caller can access, built from `model_catalog.py:build_gateway_model_catalog`. |
| POST | `/gateway/v1/chat/completions` | `gateway_chat_completions` | OpenAI (Chat Completions) | Always the translation path (`handle_chat_completion`); there is no OpenAI Chat Completions passthrough. |
| POST | `/gateway/v1/responses` | `gateway_responses` | OpenAI (Responses) | Translation path (`handle_responses_request`) or, for a true OpenAI model, the native passthrough in `openai_passthrough.py`. |
| POST | `/gateway/v1/messages` | `gateway_anthropic_messages` | Anthropic (Messages) | Translation path (`handle_anthropic_messages`) or, for a direct Anthropic provider, the native passthrough in `anthropic_passthrough.py`. |
| POST | `/gateway/v1/messages/count_tokens` | `gateway_anthropic_count_tokens` | Anthropic | No token-rate-limit check; nothing is generated. Prefers the Anthropic passthrough, falls back to a local `litellm.token_counter` estimate. |

Every endpoint depends on `require_permission(Permission.USE_LLM_GATEWAY)`
(every endpoint in `api.py`) as GATE 1, then calls
`_authorize_gateway_request` (`api.py`), which calls
`craft_gateway.py:gateway_request_flow` as GATE 2 and then checks the workspace
`llm_gateway_enabled` setting for non-Craft traffic. See §4.2 for why both
gates, plus the workspace setting, exist.

### PAT scope

`Permission.USE_LLM_GATEWAY` (`"use:llm_gateway"`,
`backend/onyx/db/enums.py`) is a selectable PAT scope
(`backend/onyx/server/pat/models.py`, `SELECTABLE_PAT_SCOPES`), gated
in the UI at `min_tier=LLM_GATEWAY_MIN_TIER` (Business). It is also implied
by `Permission.BASIC_ACCESS` and by `Permission.CRAFT_SANDBOX`
(`backend/onyx/auth/permissions.py`, `IMPLIED_PERMISSIONS`). GATE 1 therefore
accepts users whose permissions include `BASIC_ACCESS`, and Craft PATs with the
explicit `CRAFT_SANDBOX` scope. GATE 2 rejects an unscoped PAT, because
`token_scopes` is `None`. A user needs a PAT with an explicit scope that implies
`USE_LLM_GATEWAY`. See §4.2 and [[auth-and-identity]] for what `PAT scope`
means mechanically.

### Configuration (`backend/onyx/server/gateway/configs.py`)

`GATEWAY_PATH_PREFIX` (`/gateway`) and `LLM_GATEWAY_MIN_TIER` (`Tier.BUSINESS`) are
Python constants, not environment variables. `GATEWAY_PATH_PREFIX` is the router's
mount prefix and the key `PATH_PREFIX_MIN_TIER` gates on. `LLM_GATEWAY_MIN_TIER` is the
minimum tier for the whole `/gateway` prefix. The timeout values below are also
constants. Only the two passthrough kill switches read the environment.

| Variable | Default | Effect |
|---|---|---|
| `ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED` | on (`!= "false"`) | Kill switch: `false` forces Anthropic-backed providers through the OpenAI-shaped translation path instead of the native passthrough, losing server tools and thinking-signature fidelity. |
| `OPENAI_GATEWAY_PASSTHROUGH_ENABLED` | on (`!= "false"`) | Same kill switch for true-OpenAI models on `/v1/responses`. |
| `ANTHROPIC_PASSTHROUGH_CONNECT_TIMEOUT_SECONDS` / `_READ_TIMEOUT_SECONDS` | 10 / 600 | httpx timeouts for the Anthropic passthrough. |
| `OPENAI_PASSTHROUGH_CONNECT_TIMEOUT_SECONDS` / `_READ_TIMEOUT_SECONDS` | 10 / 600 | Same, OpenAI passthrough. |
| `GATEWAY_LLM_TOTAL_TIMEOUT_SECONDS` | 600 (constant, not env) | Total budget for one non-streaming translated call (`invoke_raw(total_timeout_s=...)`). |

**Not env, admin-configured:** `Settings.llm_gateway_enabled`
(`server/settings/models.py`, default `True`) is the workspace on/off switch
described in §1 and §4.2. Changing it requires the Business tier or higher
and writes an `LLM_GATEWAY_ENABLED_CHANGE` audit event
(`server/settings/api.py:admin_patch_settings`).

---

## 3. Data model

The gateway introduces no new tables. It reads the same rows
[[llm-providers]] owns:

- `LLMProvider` / `ModelConfiguration` (`db/models.py`), resolved through
  `resolve_gateway_model` (`api.py`) and
  `db/llm.py:fetch_accessible_llm_provider_by_id` /
  `fetch_all_accessible_llm_providers`.
- `PersonalAccessToken` (`db/models.py`, via `db/pat.py`), whose `scopes`
  column is a nullable list of `Permission` strings; `None` means
  unrestricted (capped only by the owning user's own effective
  permissions).

It writes the same usage ledger [[llm-providers]] and
[[rate-and-usage-limits]] already document: `UserUsage`
(`db/models.py`, via `db/user_usage.py:record_user_usage`), populated
asynchronously from tracing spans, not synchronously by the gateway request.

---

## 4. How it works

### 4.1 One request's life

```
POST /gateway/v1/chat/completions               ee/onyx/server/gateway/api.py
  ├─ tier_gate middleware                             ee/onyx/server/middleware/tier_gate.py
  │    PATH_PREFIX_MIN_TIER["/gateway"] = Tier.BUSINESS
  ├─ require_permission(Permission.USE_LLM_GATEWAY)   GATE 1 (FastAPI Depends)
  ├─ _authorize_gateway_request                       api.py
  │    ├─ gateway_request_flow                         onyx/server/features/build/craft_gateway.py
  │    │    GATE 2: resolves the LLMFlow tag, or rejects
  │    └─ workspace switch: Settings.llm_gateway_enabled (LLM_GATEWAY flow only)
  ├─ check_token_rate_limits(user)                     onyx/server/query_and_chat/token_limit.py
  ├─ resolve_gateway_model                              api.py
  │    └─ fetch_accessible_llm_provider_by_id           db/llm.py
  ├─ handle_chat_completion / handle_responses_request / handle_anthropic_messages
  │    └─ llm_from_provider                             onyx/llm/factory.py  (see [[llm-providers]])
  │    └─ llm.invoke_raw / llm.stream_raw                onyx/llm/multi_llm.py:LitellmLLM
  │         (or the native passthrough: openai_passthrough.py / anthropic_passthrough.py)
  └─ llm_generation_span(flow=...)                      tracing → user_usage rollup
```

The tier check runs as ASGI middleware before the route body executes
(`ee/onyx/server/middleware/tier_gate.py`), so an under-tier tenant
never reaches GATE 1 or GATE 2. `PATH_PREFIX_MIN_TIER[GATEWAY_PATH_PREFIX] =
LLM_GATEWAY_MIN_TIER` (`ee/onyx/configs/license_enforcement_config.py`)
is the entry that ties `/gateway` to Business. On tier-resolution failure the
middleware fails closed to `Tier.COMMUNITY` (`tier_gate.py`), which
denies the gateway rather than allowing it.

### 4.2 Authentication and scope: two gates and a workspace switch

After GATE 2 resolves the flow, `_authorize_gateway_request` checks the workspace
`llm_gateway_enabled` setting (`server/settings/models.py:Settings`,
default on) whenever the resolved flow is `LLMFlow.LLM_GATEWAY` (a
directly-scoped caller, not a Craft sandbox); if it is off, the request is
rejected with `OnyxErrorCode.FEATURE_DISABLED` before any provider or model
resolution happens. The check reads settings with `raise_on_error=True`, so
a settings-store read failure fails closed (rejects the request) rather than
silently treating the gateway as enabled. `_validate_assignable_scopes`
(`server/pat/api.py`) applies the same setting when a PAT is minted, and
`list_selectable_scopes` hides `use:llm_gateway` from the option list while
it is off (see [[auth-and-identity]]). This switch is orthogonal to the
per-Craft-sandbox enablement GATE 2 already checks; a Craft sandbox's
`CRAFT_SANDBOX`-scoped PAT is never subject to it.

**GATE 1** (`require_permission(Permission.USE_LLM_GATEWAY)`, every endpoint
in `api.py`) is the ordinary PAT-scope cap described in
[[auth-and-identity]]: a token's own `scopes` (or the owning user's full
`effective_permissions`, if unscoped) must imply `USE_LLM_GATEWAY`. Because
`USE_LLM_GATEWAY` is implied by both `BASIC_ACCESS` and `CRAFT_SANDBOX`
(`auth/permissions.py`), GATE 1 alone passes for almost any logged-in
user's PAT and for every Craft sandbox PAT.

**GATE 2** (`craft_gateway.py:gateway_request_flow`) is what actually decides
*which policy* the request is attributed to, and it treats the two cases
asymmetrically:

- If `request.state.token_scopes` is `None` (no scopes attached to this
  request), it returns `None` and the request is rejected with
  `OnyxErrorCode.INSUFFICIENT_PERMISSIONS`
  (`api.py:_authorize_gateway_request`). The module's own docstring is
  explicit about why this branch exists: **"Session/API-key auth carries no
  token scopes and must never match"**
  (`craft_gateway.py:is_craft_gateway_request`). A cookie session or a plain
  API key can satisfy GATE 1 through the owning user's `effective_permissions`
  but carries no `token_scopes` object at all, so it can never reach a
  gateway response. `request.state.token_scopes` is only ever set from a PAT
  resolution (`onyx/auth/users.py`).
- If the token's raw scopes include `Permission.CRAFT_SANDBOX`, the request
  **must** also pass `is_craft_gateway_request`, which requires both that the
  scope set implies `USE_LLM_GATEWAY` (true by the implication above) *and*
  `is_craft_enabled_for_user(user)`
  (`onyx/server/features/build/utils.py`). Only then does it return
  `LLMFlow.CRAFT_LLM_GENERATION`; otherwise it returns `None` and the call is
  rejected, even though GATE 1 already passed.
- If `CRAFT_SANDBOX` is absent but the scopes imply `USE_LLM_GATEWAY`
  directly, it returns `LLMFlow.LLM_GATEWAY` with no Craft-enablement check
  at all.

This asymmetry matters because a Craft sandbox's PAT is minted with exactly
`scopes=[Permission.CRAFT_SANDBOX]`
(`onyx/server/features/build/db/sandbox.py`), which implies
`USE_LLM_GATEWAY` mechanically. Without GATE 2's extra
`is_craft_enabled_for_user` check, a sandbox whose owning user has since had
Craft disabled (or whose deployment has Craft turned off) would still be able
to call the gateway on GATE 1 alone, because the implied-permission closure
does not know or care that the token came from Craft. GATE 2 is the place
that re-attaches the Craft-specific business rule a bare scope check cannot
express, and it is also what decides the `LLMFlow` tag used for cost
attribution (§4.6).

### 4.3 Tier gating

Enforced by `add_tier_gate_middleware`
(`ee/onyx/server/middleware/tier_gate.py`) against the
longest-matching-prefix entry in `PATH_PREFIX_MIN_TIER`
(`ee/onyx/configs/license_enforcement_config.py`), where
`GATEWAY_PATH_PREFIX` maps to `LLM_GATEWAY_MIN_TIER = Tier.BUSINESS`
(`onyx/server/gateway/configs.py`). The current tier is resolved by
`ee/onyx/utils/tier.py:get_tier`, cloud tenants from a Redis-cached
control-plane value, self-hosted from the license payload's `customer_tier`.
See [[editions-and-gating]] for `Tier`/`tier_at_least` mechanics and
[[billing]] for how a tenant's tier is set in the first place.

### 4.4 Model resolution

A caller-supplied model string has the wire form `"<provider_id>/<model_name>"`
(`api.py:resolve_gateway_model`). `resolve_gateway_model` parses the
id, loads that `LLMProviderModel` through
`db/llm.py:fetch_accessible_llm_provider_by_id` (is_public / group rules,
same access check [[llm-providers]] documents; no persona context, so a
persona-restricted provider is excluded even if otherwise public), then
looks for a `ModelConfiguration` on that provider matching `model_name` and
`is_visible == True`. Any failure (malformed id, provider not found or not
accessible, model not visible) raises the same
`OnyxErrorCode.NOT_FOUND` **without falling back to a default model**.
`model_catalog.py:build_gateway_model_catalog` builds the id strings
`GET /gateway/v1/models` returns, so a caller listing models and then calling
one back gets a working round-trip by construction; a caller inventing its
own id gets a clean 404.

`CraftLLMProviderConfig` for a sandbox
(`onyx/server/features/build/session/llm_config.py:build_onyx_gateway_config`)
constructs exactly these ids and points the sandbox's coding agent at
`{ONYX_SERVER_URL}/gateway/v1`; a stale stored selection is re-validated
against currently-accessible providers on every use, never trusted as-is
(`llm_config.py:parse_agent_selection` docstring).

### 4.5 Credential substitution

The caller authenticates with a PAT; it never supplies, and never sees, the
provider's own API key. Two paths attach the real credential differently:

- **Translation path** (`handle_chat_completion`, `handle_responses_request`,
  `handle_anthropic_messages`): `llm_from_provider(model_name, llm_provider,
  temperature)` (`onyx/llm/factory.py`, see [[llm-providers]] §4.2) builds a
  `LitellmLLM` whose config carries the provider's decrypted key internally;
  the request never touches it directly.
- **Native passthrough** (`openai_passthrough.py`, `anthropic_passthrough.py`):
  `_build_upstream_headers` sets `Authorization: Bearer <provider.api_key>`
  (OpenAI) or `x-api-key: <provider.api_key>` (Anthropic) fresh on every
  call, and both explicitly **never forward the caller's inbound headers**
  (`openai_passthrough.py`: *"Never forward inbound headers:
  OpenAI-Organization/OpenAI-Project would select a billing scope in the
  caller's OpenAI account, not ours"*; `anthropic_passthrough.py`:
  *"the inbound Authorization header is an Onyx PAT, not an Anthropic key"*).

On credential leakage back to the caller: I can confirm the response bodies
built by this code path never include `provider.api_key` or any header the
gateway received from upstream that would carry it (both passthrough modules
build response/error payloads from parsed JSON fields, not by echoing
upstream headers). Errors are explicitly sanitized: a 401/403 from the
provider is never forwarded verbatim (`_FORWARDABLE_STATUSES` in both
passthrough modules excludes 401/403, with the comment *"401/403 describe
OUR credential, not the caller's request, so they are sanitized"*,
`openai_passthrough.py`), and transport-error logging deliberately logs
only `type(e).__name__`, not the exception's string form, because *"for
custom `api_base` values [it] can embed query credentials"*
(`openai_passthrough.py`, `anthropic_passthrough.py`). I did
not find a code path that logs or returns `provider.api_key` itself; I have
not exhaustively audited every logger call in `onyx/llm/` for an unrelated
leak, so treat "never leaks" as verified for the gateway's own code, not for
the whole LLM stack.

### 4.6 `store` handling on the OpenAI passthrough

**Yes, `store` is forced to `false`**, unconditionally, on every OpenAI
Responses passthrough call: `_build_upstream_request` sets
`body["store"] = False` regardless of what the caller sent
(`openai_passthrough.py`), with the comment *"OpenAI defaults this to
true, which would persist state under our shared key where any other
gateway caller could read it back"*. The gateway also refuses
`previous_response_id` and a `conversation` field outright
(`_NO_STORAGE_MESSAGE`, `openai_passthrough.py`), so a caller cannot
even attempt to read back a stored response through this endpoint. The
non-passthrough `ResponsesRequest.store` field is separately documented as
"tolerated-and-ignored" (`onyx/server/gateway/models.py`) because
that path never talks to OpenAI's own stateful Responses surface at all, it
goes through `LitellmLLM.invoke_raw`/`.stream_raw`, which has no storage concept to
force off.

### 4.7 Cost and usage

Every generation handler opens `_gateway_trace(flow, model)` (a `trace("llm_gateway",
...)`) and an `llm_generation_span(llm, flow=flow, ...)`
(`api.py:_gateway_trace`, repeated in both passthrough modules).
`gateway_list_models` and `gateway_anthropic_count_tokens` open neither, so
metadata and token-count requests are not usage-metered. `flow` is
the `LLMFlow` GATE 2 resolved: `LLMFlow.LLM_GATEWAY` for a directly-scoped
caller, `LLMFlow.CRAFT_LLM_GENERATION` for a Craft sandbox
(`onyx/tracing/flows.py`). The span records usage on completion;
`user_usage` rows are still written asynchronously by the shared tracing
drain thread, not synchronously by the gateway request (see
[[rate-and-usage-limits]] §9 and [[llm-providers]] §4.7).

The native passthrough paths bypass `LitellmLLM.invoke_raw`/`.stream_raw` entirely
(they call the provider directly over `httpx`), so they also bypass that
class's normal cost-tracking hook. Both modules compensate by calling
`llm._track_llm_cost(usage)` manually once they have parsed the upstream
usage payload (`openai_passthrough.py`,
`anthropic_passthrough.py`), converting OpenAI's or
Anthropic's own usage shape into the shared `Usage` model first
(`_usage_from_openai_wire`, `_usage_from_anthropic_wire`). A reasoning-token
or per-server-tool-use count that has no `Usage` field yet is attached to
`span.span_data.model_config` instead, so it is visible in traces even
though it is not yet priced.

See [[observability]] for the tracing pipeline and dashboard side of this.

### 4.8 Rate limiting

`gateway_chat_completions`, `gateway_responses`, and
`gateway_anthropic_messages` each call `check_token_rate_limits(user)`
(`onyx/server/query_and_chat/token_limit.py`, `api.py`)
**after** GATE 2 but before resolving the model, exactly as
[[rate-and-usage-limits]] already documents. `count_tokens` does not call it
(`api.py`, comment: *"No token rate limit check: nothing is generated by
this endpoint"*), which is correct since it never invokes a model.

The same three endpoints resolve the model through
`_resolve_metered_gateway_model`, which runs
`check_llm_cost_limit_for_provider` on the resolved provider's key. On cloud,
this is the weekly cost cap on Onyx-managed keys, the same check the chat
route runs. `count_tokens` skips it too.

**None of the five endpoints calls `check_api_key_usage`, on purpose.** A
coding agent makes hundreds of gateway calls per session, so counting them
against the cloud API-call cap is a product decision that has not been made.
A PAT-driven gateway call does not increment the tenant's `api_calls` counter
the same PAT would increment on `/chat/send-chat-message`.

### 4.9 Streaming

`stream_bridge.py:_run_bridged_stream` is the shared mechanism for every
streaming endpoint (translation and both native passthroughs). It spawns the
actual work on a **separate thread** via
`onyx/utils/threadpool_concurrency.py:start_thread_with_context`, which
copies the calling thread's `contextvars.Context` into the new thread before
starting it. The worker function (`_stream_worker`,
`_responses_stream_worker`, `_anthropic_stream_worker`,
`_openai_passthrough_stream_worker`, `_passthrough_stream_worker`) opens its
own `_gateway_trace` and `llm_generation_span` **inside that thread**, with
an explicit comment repeated at every call site: *"Runs on its own thread
after the endpoint has returned the StreamingResponse, so the trace must be
opened here rather than in the endpoint for the generation span to see an
active trace"* (e.g. `api.py:_stream_worker`). This sidesteps the known bug class
where a `contextvars`-backed span context is lost across an SSE generator
that Starlette resumes on a different thread each time it is pumped: instead
of relying on generator-resumption context (which is what breaks), the
gateway hands the worker a snapshotted context up front and does all tracing
work inside that one thread, communicating results back to the ASGI layer
only through a plain `queue.Queue`
(`stream_bridge.py:_run_bridged_stream`). The main coroutine that
yields SSE frames to the client never touches the span or trace context at
all; it only drains the queue.

Each dialect's stream worker converts `LitellmLLM.stream_raw`'s
`Iterator[ModelResponseStream]` (or, for native passthrough, raw upstream SSE
lines) into its own wire format: OpenAI chat-completion chunks
(`ChatCompletionChunk.from_stream_chunk`), OpenAI Responses events
(`ResponsesOutputTextDeltaEvent` etc.), or Anthropic content-block events
(`AnthropicContentBlockDeltaEvent` etc.), reusing
`stream_bridge.py:merge_tool_call_delta` /
`finalize_tool_calls` for tool-call-delta accumulation, per
[[llm-providers]] §4.5's contract. `_stream_worker_guard`
(`stream_bridge.py`) is the single teardown point: on any exception
it emits a sanitized, dialect-appropriate in-band error frame (the HTTP
status is already 200 by the time a worker runs, so failures cannot surface
as a different status code), then always drains for trailing usage
(`_drain_for_usage`, bounded by `_USAGE_DRAIN_MAX_CHUNKS` /
`_USAGE_DRAIN_MAX_SECONDS`), closes the upstream iterator/`ExitStack`, and
records the span before signalling `_STREAM_END`.

---

## 5. Contracts and invariants

1. **The provider credential must never reach the caller.** Neither
   passthrough forwards the caller's inbound `Authorization` header upstream,
   and both build the upstream credential header fresh from
   `provider.api_key` on every call (§4.5). A change that starts copying any
   inbound header wholesale toward the provider, or that echoes an upstream
   response header back to the caller unfiltered, breaks this.
2. **A token without a gateway-capable scope must be rejected, and session
   or API-key auth must never satisfy the gateway.**
   `gateway_request_flow` returns `None` whenever
   `request.state.token_scopes` is `None`, which is exactly the case for
   cookie-session and API-key requests (`craft_gateway.py`, §4.2). Do not add
   a fallback that infers a flow from the user object alone.
3. **A `CRAFT_SANDBOX` token must stay bound to the Craft policy.** It may
   only produce `LLMFlow.CRAFT_LLM_GENERATION`, and only when
   `is_craft_enabled_for_user` also passes; it must never fall through to the
   plain `LLMFlow.LLM_GATEWAY` path (§4.2).
4. **Every call must be metered and tagged.** Every generation handler, translation and
   passthrough, streaming and non-streaming, opens a `_gateway_trace` plus an
   `llm_generation_span`/manual `_track_llm_cost` call. A new endpoint or a
   new passthrough branch that skips this loses its span (translation
   path: `llm.invoke_raw` and `llm.stream_raw` open no span, see
   [[llm-providers]] §4.7) or **silently unmetered cost** at worst
   (passthrough path, which never calls `LLM.invoke_raw`/`.stream_raw` and
   must call `llm._track_llm_cost` itself).
5. **`store` must stay forced false on the OpenAI Responses passthrough**,
   and `previous_response_id`/`conversation` must stay refused. Relaxing
   either reopens the cross-user stored-state read this code exists to
   prevent (§4.6).
6. **An unknown model must fail cleanly, never fall back to a default.**
   `resolve_gateway_model` raises `OnyxErrorCode.NOT_FOUND` for a malformed
   id, an inaccessible provider, or an invisible/absent model (§4.4). Do not
   add a "pick the default model instead" fallback here; a gateway caller
   picked its model explicitly and a silent substitution would bill the
   wrong model to the wrong budget.
7. **Tier gating happens before any gateway code runs.** The `/gateway`
   prefix must stay in `PATH_PREFIX_MIN_TIER` at `Tier.BUSINESS` or higher;
   removing the entry (rather than deliberately changing the tier) reopens
   the feature below its licensed tier.

---

## 6. Relationships

**Depends on**
- [[llm-providers]]: the provider factory (`llm_from_provider`), the
  `LitellmLLM` wrapper and its cost/tracing hooks, `LLMFlow`, and the
  provider-access check (`can_user_access_llm_provider` via
  `fetch_accessible_llm_provider_by_id`) that this component's model
  resolution reuses verbatim.
- [[auth-and-identity]]: PAT scopes and `require_permission`'s token-scope
  capping are GATE 1; `Permission.CRAFT_SANDBOX` and `Permission.
  USE_LLM_GATEWAY` are defined there.
- [[rate-and-usage-limits]]: `check_token_rate_limits` and the cloud cost cap
  gate every content-generating endpoint; `check_api_key_usage` is absent on
  purpose (§4.8).
- [[editions-and-gating]]: `Tier`, `tier_at_least`, and the
  `PATH_PREFIX_MIN_TIER` middleware mechanism this component's tier gate is
  one entry in.
- [[billing]]: how a tenant's `Tier` is actually set (cloud subscription or
  self-hosted license), which `ee/onyx/utils/tier.py:get_tier` resolves.
- [[observability]]: the tracing spans this component opens, and the
  `user_usage` rollup they feed.

**Depended on by**
- [[craft-sandboxes]] / [[craft-sessions]]: every sandbox's coding agent is
  configured to call this gateway
  (`onyx/server/features/build/session/llm_config.py:build_onyx_gateway_config`),
  authenticated by a per-sandbox `CRAFT_SANDBOX`-scoped PAT
  (`onyx/server/features/build/db/sandbox.py:ensure_sandbox_pat`).
- External tools: any OpenAI- or Anthropic-compatible CLI or SDK pointed at
  `/gateway` with a `use:llm_gateway` PAT (Claude Code, Codex, opencode; see
  the integration tests in §8).
- [[multi-tenancy]]: every provider lookup and rate-limit/usage check this
  component performs is tenant-scoped, inherited from the underlying DB
  session and [[rate-and-usage-limits]] machinery, not reimplemented here.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds an endpoint or a new dialect | wire it through both GATE 1 (`require_permission(Permission.USE_LLM_GATEWAY)`) and GATE 2 (`_authorize_gateway_request`); add `check_token_rate_limits` and resolve through `_resolve_metered_gateway_model` unless the endpoint generates nothing; open a `_gateway_trace`/`llm_generation_span` or call `_track_llm_cost` manually if it bypasses `LLM.invoke_raw`/`.stream_raw` |
| changes scope checks (`gateway_request_flow`, `IMPLIED_PERMISSIONS`) | re-verify the asymmetry in §4.2 still holds: a bare `USE_LLM_GATEWAY` grant must not require Craft enablement, and a `CRAFT_SANDBOX` token must still require it; re-run `backend/tests/unit/onyx/server/features/craft/test_craft_gateway.py` |
| changes the `llm_gateway_enabled` check (`_authorize_gateway_request`, `_validate_assignable_scopes`, `list_selectable_scopes`) | re-verify it still fails closed on a settings-read error, still exempts Craft sandbox traffic, and still blocks both new PAT minting and existing-PAT gateway calls; re-run `backend/tests/unit/ee/onyx/server/gateway/test_llm_gateway_api.py` and `backend/tests/unit/onyx/server/pat/test_pat_api.py` |
| changes model resolution (`resolve_gateway_model`, the `<provider_id>/<model_name>` wire format) | `model_catalog.py:build_gateway_model_catalog` (the id format `GET /v1/models` returns must still round-trip), and `onyx/server/features/build/session/llm_config.py` which parses the same id format for Craft's stored selection |
| changes metering (`_gateway_trace`, `_track_llm_cost`, the `LLMFlow` tags) | [[observability]]'s dashboard grouping, and `backend/tests/integration/tests/streaming_endpoints/test_gateway_usage_tracking.py`, which asserts `user_usage` actually increases after a gateway call |
| changes streaming (`stream_bridge.py`, either stream worker) | the contextvars-copy-then-open-span-in-thread pattern (§4.9) must be preserved for any new streaming branch; a naive `async def` generator that opens a span before yielding will silently produce untagged or cross-request-contaminated spans |
| changes `store`/persistence handling on the OpenAI passthrough | re-confirm `store=False` is still forced and `previous_response_id`/`conversation` are still refused (§4.6); this is a cross-user data exposure risk under the shared organization key, not just a correctness nit |
| changes tier gating (`PATH_PREFIX_MIN_TIER`, `LLM_GATEWAY_MIN_TIER`) | `ee/onyx/configs/license_enforcement_config.py`'s longest-prefix-wins ordering, and any nested path that should resolve to a stricter tier than `/gateway` itself |

---

## 8. How to verify a change

### Tests

```bash
# Gateway request/scope/streaming unit tests
uv run --env-file .vscode/.env pytest backend/tests/unit/ee/onyx/server/gateway/test_llm_gateway_api.py
# Craft policy asymmetry (GATE 2) unit tests
uv run --env-file .vscode/.env pytest backend/tests/unit/onyx/server/features/craft/test_craft_gateway.py
uv run --env-file .vscode/.env pytest backend/tests/unit/onyx/server/features/craft/test_session_gateway_config.py
uv run --env-file .vscode/.env pytest backend/tests/unit/onyx/server/gateway
# Usage metering, end to end
uv run --env-file .vscode/.env pytest backend/tests/integration/tests/streaming_endpoints/test_gateway_usage_tracking.py
# Real client integration tests (need ANTHROPIC_API_KEY / OpenAI secrets)
uv run --env-file .vscode/.env pytest backend/tests/integration/tests/gateway_clients/test_claude_code_gateway.py
uv run --env-file .vscode/.env pytest backend/tests/integration/tests/gateway_clients/test_codex_gateway.py
```

See `backend/AGENTS.md` for required env and secrets.

### Manual reproduction (mint a PAT, call the gateway, confirm metering)

1. As an admin, configure an LLM provider under **Admin > LLM** (or
   `PUT /admin/llm/provider`) if one is not already configured.
2. Create a PAT scoped to the gateway:
   `tests/integration/common_utils/managers/pat.py:PATManager.create(...,
   scopes=[Permission.USE_LLM_GATEWAY])` is the test-suite equivalent of what
   the frontend PAT-creation UI does; outside a test, use the PAT admin UI
   (`GET /user/pats/scopes` lists selectable scopes, see [[auth-and-identity]]).
3. `GET /gateway/v1/models` with `Authorization: Bearer <pat>` and confirm
   the configured provider's models appear as `<provider_id>/<model_name>`.
4. `POST /gateway/v1/chat/completions` (or `/v1/messages` for Anthropic)
   with that model id and a real message; confirm a real streamed or
   non-streamed answer comes back.
5. `GET /user/usage` (`backend/onyx/server/features/usage/api.py`) as the
   same user and confirm token counts for that model increased; the tracing
   drain thread flushes on a roughly 2-second interval, so poll for up to
   ~45 seconds (see `test_gateway_usage_tracking.py:_POLL_TIMEOUT_SECONDS`).
6. Repeat as a user on a sub-Business tier (or with `LICENSE_ENFORCEMENT_ENABLED`
   simulating a Community license) and confirm every `/gateway/*` call
   returns 402 with `error_code: "FEATURE_NOT_AVAILABLE"` before touching
   any provider.

### What "working" looks like

- A caller with only `use:llm_gateway` (no Craft) gets `LLMFlow.LLM_GATEWAY`
  spans; a Craft sandbox's calls get `LLMFlow.CRAFT_LLM_GENERATION`.
- No `provider.api_key` value appears in any gateway response body, error
  body, or log line.
- `store` is `false` in every outbound OpenAI Responses passthrough request,
  regardless of what the caller sent.
- An unknown or inaccessible model id returns 404, never a substituted model.
- Below Business tier, every `/gateway/*` request is rejected by the tier
  gate before any handler code runs.

---

## 9. Footguns

- **`Permission.USE_LLM_GATEWAY` is implied by `BASIC_ACCESS`.** GATE 1
  (`require_permission`) alone passes for nearly any logged-in user's
  unscoped PAT or session-derived permission set. GATE 2
  (`gateway_request_flow`) is the only thing standing between "any user" and
  "an actual gateway response", specifically because it also refuses to
  match session/API-key auth at all (§4.2). Do not reason about gateway
  access from GATE 1 in isolation.
- **The cost cap needs the resolved provider, so it runs after model
  resolution.** A new generating endpoint must resolve through
  `_resolve_metered_gateway_model`, not `resolve_gateway_model`, or it skips
  the cloud cost cap. Gateway calls are not counted by `check_api_key_usage`
  (§4.8).
- **No `/build/llm-gateway` route exists anywhere in the repository.**
  `grep -rn "llm-gateway" backend/onyx/server/features/build/` matches
  nothing; `craft_gateway.py` is a policy helper
  (`gateway_request_flow`/`is_craft_gateway_request`), not a second router,
  and Craft's sandboxes call the one router under `/gateway`, mounted only
  from `backend/ee/onyx/main.py`.
- **Native passthrough bypasses `LitellmLLM.invoke_raw`/`.stream_raw` entirely**, so
  it also bypasses their built-in cost-tracking hook. Both
  passthrough modules compensate with a manual `llm._track_llm_cost(usage)`
  call; a future passthrough addition that forgets this call meters nothing,
  with no span or `UNTAGGED_*` sentinel to reveal the gap,
  because neither raw method runs on that path.
- **The kill switches (`ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED`,
  `OPENAI_GATEWAY_PASSTHROUGH_ENABLED`) silently change fidelity, not just
  availability.** Turning a passthrough off does not disable the model; it
  routes the same request through the OpenAI-shaped translation layer
  instead, which cannot carry server-side tools, thinking-block signatures,
  `pause_turn`, or fine-grained streaming (`anthropic_passthrough.py`).
  A test that only checks "the call still succeeds" will not catch this
  degradation.
- **`count_tokens` degrades to a rough local estimate on failure**, not an
  error: if the Anthropic passthrough has a transport failure
  (`AnthropicPassthroughUnavailable`), or `litellm.token_counter` itself
  raises, the endpoint falls back to
  `len(json.dumps(...)) // 4` (`gateway_anthropic_count_tokens` in `api.py`). A caller relying on
  exact token counts (e.g. Claude Code's context-window tracking) can get a
  materially wrong number without any error surfacing.
- **A stream worker's trace must be opened inside the worker thread, not the
  endpoint coroutine.** Every stream worker repeats the same comment for a
  reason (§4.9); opening the span before handing off to
  `start_thread_with_context` would open it in the wrong context and the
  worker's actual generation would show up untagged.

---

Related: [[llm-providers]], [[auth-and-identity]], [[rate-and-usage-limits]],
[[observability]], [[editions-and-gating]], [[billing]], [[craft-sandboxes]],
[[craft-sessions]], [[multi-tenancy]].
