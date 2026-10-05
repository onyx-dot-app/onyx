# Rate and Usage Limits

> Every mechanism that throttles or caps usage: admin-configured LLM token
> budgets, cloud tenant usage caps, API key/PAT call caps, plain HTTP rate
> limiting, and signup/invite abuse limits. These are five separate
> mechanisms with separate storage and separate scopes; they only share a
> name.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** platform
**Edition:** Mixed. Token rate limits: CE enforces GLOBAL scope only; EE adds
USER and USER_GROUP scope, and EE is also the only edition that can create or
edit any rate limit (see §9). Tenant usage limits and their control-plane
overrides are EE/cloud-only. HTTP and invite/signup rate limiting are CE.
**Owns:**
`backend/onyx/server/query_and_chat/token_limit.py`,
`backend/onyx/server/api_key_usage.py`, `backend/onyx/server/usage_limits.py`,
`backend/onyx/server/tenant_usage_limits.py`, `backend/onyx/db/token_limit.py`,
`backend/onyx/db/usage.py`, `backend/onyx/db/user_usage.py`,
`backend/onyx/server/token_rate_limits/models.py`,
`backend/onyx/server/middleware/rate_limiting.py`,
`backend/onyx/auth/signup_rate_limit.py`,
`backend/onyx/server/manage/invite_rate_limit.py`,
`backend/onyx/db/tenant_invite_counter.py`,
`backend/ee/onyx/server/query_and_chat/token_limit.py`,
`backend/ee/onyx/server/usage_limits.py`,
`backend/ee/onyx/server/tenant_usage_limits.py`,
`backend/ee/onyx/server/token_rate_limits/api.py`,
`backend/ee/onyx/db/token_limit.py`,
`web/src/app/admin/token-rate-limits/`

---

## 1. What the user experiences

A regular user who trips a token or cost budget sees a chat message fail with
a usage-limit banner instead of an answer. The banner names the scope that
tripped ("your account", "your organization", "your user group") and does not
offer a retry button, because retrying immediately would just re-trip the
same budget. The same banner renders in the Craft/Build agent view.

An admin on Enterprise Edition configures token or cost budgets from
**Admin > Token Rate Limits** (`web/src/app/admin/token-rate-limits/`): a
budget in thousands of tokens or in cents, over a period in hours, at
Global, Per User, or Per User Group scope. The Per User and Per User Group
tabs only render when the workspace is at least `Tier.ENTERPRISE`
(`TokenRateLimitsPanel.tsx:enterpriseTier`); a Community deployment has no
admin surface to create a rate limit at all (see §9).

A cloud (`MULTI_TENANT`) tenant on a trial plan that exceeds its weekly LLM
cost, indexed-chunk, or API-call allowance gets a 429 with a plan-upgrade
message. This is unrelated to token rate limits: it is enforced per tenant,
not per user, and configured by Onyx's control plane, not by the tenant's own
admin.

A caller using an API key or personal access token (PAT) against the chat
endpoint hits a separate weekly API-call cap tied to the same tenant usage
system.

An anonymous visitor hammering signup or an admin bulk-inviting users hits
Redis-backed abuse limits that exist purely to stop scripted abuse; they are
invisible in normal use.

---

## 2. Surfaces

### HTTP endpoints that enforce `check_token_rate_limits`

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/chat/send-chat-message` | `handle_send_chat_message` | Also runs `check_api_key_usage`. `chat_backend.py:handle_send_chat_message` |
| (inline) | chat session auto-naming | `_generate_or_fallback_chat_session_name` | Calls `check_token_rate_limits` directly, not as a `Depends`. `chat_backend.py:_generate_or_fallback_chat_session_name` |
| POST | `/build/sessions/{id}/send-message` | (Craft turn) | Called inline before creating the user message. `features/build/session/messages.py:send_message`  |
| POST | `/build/sessions/{id}/subagents/{sub_id}/send-message` | `send_subagent_message` | `features/build/session/messages.py:send_subagent_message` |
| POST | `/gateway/v1/chat/completions`, `/gateway/v1/responses`, `/gateway/v1/messages` | `gateway_chat_completions`, `gateway_responses`, `gateway_anthropic_messages` | The AI Gateway (OpenAI/Anthropic-compatible passthrough), EE-only. `_resolve_metered_gateway_model` also runs `check_llm_cost_limit_for_provider` on the resolved provider's key. `ee/onyx/server/gateway/api.py` |
| POST | `/search` | `search` | Called inline before the LLM is resolved. Also runs `check_api_key_usage`. Used by the MCP server. `features/search/api.py:search` |
| POST | `/search/send-search-message` | `handle_send_search_message` | The EE Search UI. Checks the token budgets and the cloud cost cap only when the request runs query expansion or LLM document selection. `ee/onyx/server/query_and_chat/search_backend.py` |
| POST | `/search/search-flow-classification` | `search_flow_classification` | Runs only the cloud cost cap (`check_llm_cost_limit_for_provider`), not the token budgets. Same file. |
| (in process) | Slack bot answer | `handle_regular_answer` | Called inline, charged to `usage_user`. An over-budget request gets the budget message in the thread. `onyxbot/slack/handlers/handle_regular_answer.py` |

### HTTP endpoints that enforce `check_api_key_usage`

| Method | Path | Handler |
|---|---|---|
| POST | `/chat/send-chat-message` | `chat_backend.py:handle_send_chat_message` |
| POST | `/search` | `features/search/api.py:search` |

No other endpoint declares `check_api_key_usage`. See §9 for what this means
for the Gateway and Craft/Build surfaces.

### Indexing-side global check

`check_global_token_rate_limits` (`token_limit.py`) enforces only the GLOBAL
scope, without a user principal, from the indexing pipeline:
`onyx/indexing/indexing_pipeline.py` (the step that embeds and indexes
document batches). This exists because indexing can itself burn LLM budget
(vision/summarization models) with no requesting user to attribute the call
to.

### Environment configuration

| Variable | Default | Effect |
|---|---|---|
| `USAGE_LIMITS_ENABLED` | `MULTI_TENANT` | Gate for the whole tenant-usage-limit system (`shared_configs/configs.py`). |
| `USAGE_LIMIT_WINDOW_SECONDS` | 604800 (7 days) | Fixed window for tenant usage buckets (`shared_configs/configs.py`). |
| `USAGE_LIMIT_LLM_COST_CENTS_TRIAL` / `_PAID` | 3200 / 6400 | Weekly LLM cost cap, cents (`shared_configs/configs.py`). |
| `USAGE_LIMIT_CHUNKS_INDEXED_TRIAL` / `_PAID` | 400000 / 4000000 | Weekly indexed-chunk cap. |
| `USAGE_LIMIT_API_CALLS_TRIAL` / `_PAID` | 0 / 40000 | Weekly API/PAT call cap. |
| `USAGE_LIMIT_NON_STREAMING_CALLS_TRIAL` / `_PAID` | 0 / 160 | Weekly non-streaming call cap. |
| `AUTH_RATE_LIMITING_ENABLED` | derived | On when both `RATE_LIMIT_MAX_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS` are set (`app_configs.py`). Off by default. |
| `RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | unset | The auth-router HTTP rate limit. |
| `FEEDBACK_RATE_LIMIT_MAX_REQUESTS` / `_WINDOW_SECONDS` | 100 / 60 | Per-user chat-feedback limiter, on by default. |
| `SIGNUP_RATE_LIMIT_ENABLED` | `false` | Gates `enforce_signup_rate_limit`; only takes effect when `MULTI_TENANT` is also true. |
| `NUM_FREE_TRIAL_USER_INVITES` | 10 | Lifetime invite cap per trial tenant (`app_configs.py`). |

Admin-configured, not env: every `TokenRateLimit` row (budget, period, scope),
created through `/admin/token-rate-limits/*` (EE-only router,
`ee/onyx/server/token_rate_limits/api.py`).

---

## 3. Data model

### `token_rate_limit` (`TokenRateLimit`, `db/models.py:TokenRateLimit`)

| Column | Meaning |
|---|---|
| `enabled` | Soft-disable without deleting the row. |
| `token_budget` | Nullable; stored in **thousands of tokens** (`TOKEN_BUDGET_UNIT = 1000` in `token_limit.py`). |
| `cost_budget_cents` | Nullable; `Numeric(18,6)` for sub-cent accumulation. |
| `period_hours` | The rolling window length. Token budgets must normalize to a supported period (`normalize_token_period_hours`); cost budgets must be daily/weekly/monthly (`COST_BUDGET_PERIOD_HOURS`). |
| `scope` | `TokenRateLimitScope`: `GLOBAL`, `USER`, or `USER_GROUP` (`configs/constants.py:TokenRateLimitScope`). |

A check constraint (`ck_token_rate_limit_budget_set`) requires at least one of
`token_budget` / `cost_budget_cents` to be non-null; a limit with neither is
impossible to insert.

### `token_rate_limit__user_group` (`TokenRateLimit__UserGroup`)

Many-to-many join between a `TokenRateLimit` (scope `USER_GROUP`) and
`user_group`. The admin API attaches one group per limit today, but the
schema allows more; `db/token_limit.py:get_token_rate_limit_scope_and_group_ids`
returns every group id, not just one.

### `user_usage` (`UserUsage`, physical table name kept for compatibility)

A daily rollup of LLM token/cost usage, keyed by `(user_id or system
attribution, window_start, model, flow, provider, incognito)`. Written by
`db/user_usage.py:record_user_usage`, an upsert. This is the table
`check_token_rate_limits` scans; **it is not incremented synchronously by the
chat request**, see §9.

### `tenant_usage` (`TenantUsage`)

One row per `USAGE_LIMIT_WINDOW_SECONDS` window (default weekly), holding
`llm_cost_cents`, `chunks_indexed`, `api_calls`, `non_streaming_api_calls`
counters for the current tenant. Read/written synchronously in
`db/usage.py:get_or_create_tenant_usage`, `check_usage_limit`,
`increment_usage`.

### `tenant_invite_counter` (`TenantInviteCounter`)

One monotonic counter per tenant, `total_invites_sent`, incremented under a
row lock by `db/tenant_invite_counter.py:reserve_trial_invites` and
compensating-decremented by `release_trial_invites` on downstream failure.

### Redis / cache keys

| Key pattern | TTL | Owner | Meaning |
|---|---|---|---|
| `signup_rate:{ip}:{bucket}` | 3600s | `auth/signup_rate_limit.py` | Per-IP signup attempts this hour. |
| `ratelimit:invite_put:admin:{user_id}:min` / `:day` | 60s / 86400s | `server/manage/invite_rate_limit.py` | Per-admin invite cadence and volume. |
| `ratelimit:invite_put:tenant:{tenant_id}:day` | 86400s | same | Tenant-wide invite volume per day. |
| `ratelimit:invite_remove:admin:{user_id}:min` / `:day` | 60s / 86400s | same | Per-admin remove-invited-user cadence. |
| `_any_rate_limit_exists_cache` (in-process `TTLCache`, not Redis) | 60s | `token_limit.py` | Per-tenant "does any enabled TokenRateLimit exist" fast-path. |

The FastAPI-limiter buckets for `get_auth_rate_limiters` /
`get_feedback_rate_limiters` live in Redis under keys `fastapi_limiter`
manages internally, not owned by this component's code.

---

## 4. How it works

### 4.1 Token rate limits (`check_token_rate_limits`)

```
check_token_rate_limits(user)                    token_limit.py
  └─ any_rate_limit_exists()                       # tenant-scoped TTLCache fast path
  └─ fetch_versioned_implementation(...)            # CE vs EE dispatch, see editions-and-gating
       CE: _check_token_rate_limits                 token_limit.py
             └─ _user_is_rate_limited_by_global      # GLOBAL scope only
       EE: _check_token_rate_limits                 ee/.../token_limit.py
             ├─ _user_is_rate_limited                # USER scope
             ├─ _user_is_rate_limited_by_group       # USER_GROUP scope
             └─ _user_is_rate_limited_by_global       # GLOBAL scope, run in parallel
```

For each applicable scope, the check:
1. Fetches enabled `TokenRateLimit` rows for that scope.
2. If any row sets a `token_budget`, sums `user_usage` token buckets since the
   widest token window (`_get_cutoff_time`) and compares per-limit
   (`_token_budget_reset`). Cost budgets are summed the same way over
   `cost_budget_cents` buckets (`_cost_budget_reset`).
3. If any limit is over budget, raises `OnyxError(RATE_LIMITED)` with the
   **latest** reset time among the exceeded limits at that scope
   (`_raise_for_latest_reset`) so a caller who waits it out does not
   immediately re-trip a limit that clears later.
4. EE also runs USER, USER_GROUP, and GLOBAL checks **in parallel**
   (`run_functions_tuples_in_parallel`); a user who belongs to a group that
   is *not* over budget is not blocked by that group, only by ones that are.
5. Anonymous users and service accounts (`AccountType.SERVICE_ACCOUNT`, or an
   email that matches `is_api_key_email_address`) skip USER/USER_GROUP checks
   and are subject to GLOBAL only, even on EE
   (`ee/.../token_limit.py:_check_token_rate_limits`). A service account is a
   shared principal: API keys, and the Slack service account that carries the
   usage of every Slack user with no Onyx account. A per-user budget on it
   would throttle all of those callers as one. A PAT resolves to its owner, a
   normal user, so PAT traffic gets the full USER/USER_GROUP/GLOBAL check.
   `BOT` accounts (one per Slack user) are normal users here.

"Token" here means **LLM tokens accumulated in the `user_usage` rollup**, not
an HTTP request count. The rollup is written asynchronously from tracing
spans, not from this check itself (see §9).

### 4.2 API key usage (`check_api_key_usage`)

```
check_api_key_usage(request)                       api_key_usage.py
  └─ is_usage_limits_enabled()                       # USAGE_LIMITS_ENABLED, off unless MULTI_TENANT
  └─ get_hashed_api_key_from_request / get_hashed_pat_from_request
       (no match -> no-op; this check is a no-op for cookie-session users)
  └─ check_usage_and_raise(usage_type=API_CALLS)      usage_limits.py
  └─ increment_usage(usage_type=API_CALLS)            db/usage.py
```

This is a synchronous counter on `tenant_usage.api_calls`, incremented on
every call that reaches this dependency, checked **before** it increments so
the request that would tip the tenant over is rejected rather than counted
twice.

### 4.3 Tenant usage limits (`usage_limits.py`, `tenant_usage_limits.py`)

`check_usage_and_raise` and `check_llm_cost_limit_for_provider` are the two
call sites. Both:
1. Resolve `is_trial` via `is_tenant_on_trial_fn`, versioned CE (`always
   False`) vs EE (`ee/.../usage_limits.py`, cached against the control plane
   via `cached_is_tenant_on_trial`, defaulting to **trial-restrictive on
   error**).
2. Resolve the limit via `get_limit_for_usage_type`, which checks a
   per-tenant override (`_get_tenant_override`, EE only, fetched from the
   control plane every 24h by `ee/.../tenant_usage_limits.py:load_usage_limit_overrides`)
   before falling back to the env-var default. `NO_LIMIT = -1` means
   unlimited.
3. Compare current `tenant_usage` counters against the limit and raise a
   detailed `OnyxError(RATE_LIMITED)` naming the metric, current value, and
   limit.

`check_llm_cost_limit_for_provider` only enforces when the LLM call would use
an **Onyx-managed default API key** (`is_onyx_managed_api_key`); a tenant
using its own provider key is exempt from the cost cap.

### 4.4 HTTP-level rate limiting (`server/middleware/rate_limiting.py`)

Two independent `fastapi_limiter.RateLimiter` instances, both backed by
Redis via `FastAPILimiter.init`:
- `get_auth_rate_limiters()`: applied as router-level `dependencies` to the
  whole auth router by `main.py:include_router_with_global_prefix_prepended`
  (login, register, password reset, etc). Keyed by IP + User-Agent
  (`rate_limit_key`). Disabled unless both env vars are set.
- `get_feedback_rate_limiters()`: applied to
  `/chat/create-chat-message-feedback` and
  `/chat/remove-chat-message-feedback` only. Keyed by authenticated user id
  (`user_scoped_rate_limit_key`), falling back to IP + User-Agent for the
  anonymous shared user. On by default.

Neither limiter touches the chat turn endpoint.

### 4.5 Signup and invite limits

`enforce_signup_rate_limit` (`auth/signup_rate_limit.py`): a plain Redis
`INCR` + `EXPIRE` per client IP, 5/hour, only active when `MULTI_TENANT` and
`SIGNUP_RATE_LIMIT_ENABLED`. Called from `auth/users.py` at the
email/password registration path.

Invite limits (`server/manage/invite_rate_limit.py`), called from
`server/manage/users.py` around the invite-users endpoint:
- A **lifetime** trial cap (`NUM_FREE_TRIAL_USER_INVITES`, default 10),
  enforced through the monotonic `tenant_invite_counter` row lock
  (`reserve_trial_invites`), rolled back on rejection.
- Three Redis buckets checked and incremented **atomically in one Lua
  script** (`_CHECK_AND_INCREMENT_SCRIPT`): admin/minute, admin/day,
  tenant/day. Applies to trial tenants only; paid tenants rely on seat
  limits and the lifetime cap instead.
- A separate two-bucket limiter for remove-invited-user
  (`enforce_remove_invited_rate_limit`), defending the invite-then-remove
  bypass pattern.
- Fails open (logs a warning, lets the request through) on Redis
  connection/timeout errors, so self-hosted "Lite" deployments without Redis
  are not blocked from inviting users.

### 4.6 Mechanism-to-enforcement map

| Mechanism | Enforced where | Scope key | On breach |
|---|---|---|---|
| Token rate limit (LLM tokens) | `check_token_rate_limits`: chat send, chat naming, Craft send-message/subagent-message, AI Gateway v1 endpoints, indexing pipeline (global only) | Global (CE+EE), User, User Group (EE only) | `OnyxError(RATE_LIMITED)`, 429, `reset_at` = latest exceeded-limit reset |
| Token rate limit (LLM cost) | same call sites | same | same |
| API key/PAT call cap | `check_api_key_usage`: chat send only | Tenant | `OnyxError(RATE_LIMITED)`, 429, detail names calls/limit |
| Tenant usage limit (LLM cost, chunks indexed, API calls, non-streaming calls) | `check_usage_and_raise` / `check_llm_cost_limit_for_provider`: indexing pipeline, chat LLM-cost path, `check_api_key_usage` | Tenant, trial vs paid | `OnyxError(RATE_LIMITED)`, 429, detail names metric |
| HTTP auth rate limit | Auth router, all routes | IP + User-Agent | `fastapi_limiter` 429 (plain HTTP, no `OnyxError` payload) |
| HTTP feedback rate limit | Chat feedback endpoints | User id (or IP+UA for anonymous) | same |
| Signup rate limit | Registration endpoint | Client IP | `OnyxError(RATE_LIMITED)`, 429 |
| Invite rate limit | Invite / remove-invited endpoints | Admin user, tenant | `OnyxError(RATE_LIMITED)`, 429, or `OnyxErrorCode.TRIAL_INVITE_LIMIT_EXCEEDED` for the lifetime cap |

---

## 5. Contracts and invariants

1. **A limit must be enforced on every path that reaches the limited
   resource, not only the web chat endpoint.** `check_token_rate_limits` and
   `check_api_key_usage` are ordinary functions, not middleware; a new entry
   point that drives an LLM turn must call them explicitly. See §9 for the
   entry points that currently do not.
2. **A breach must return a well-formed error the clients already handle.**
   The wire shape is `OnyxErrorCode.RATE_LIMITED` (429) with `extra.scope`,
   `extra.reset_at`, `extra.retry_after_seconds` and a `Retry-After` header
   (`token_limit.py:raise_rate_limited`). `[[chat-frontend]]`'s
   `services/lib.tsx` (the `app/services/lib.tsx` "app" chat surface) and the
   Craft `BuildMessageList.tsx` both special-case
   `response.status === 429 && data.error_code === RATE_LIMITED_ERROR_CODE`
   into a synthetic, non-retryable `StreamingError`. Changing the error code
   string, dropping `extra.reset_at`, or returning a different status breaks
   both renderers silently (the raw error would just print as opaque text).
3. **Counters must be tenant-scoped.** `user_usage` and `tenant_usage` rows
   are read/written inside `get_session_with_current_tenant` /
   tenant-scoped sessions; `_any_rate_limit_exists_cache` is keyed by
   `tenant_id` explicitly so one tenant's "no limits configured" answer never
   suppresses another tenant's enforcement in a shared worker process.
4. **A limit check must not be expensive per request.**
   `any_rate_limit_exists()` is a 60s TTL-cached fast path so the common
   no-limits-configured case costs no DB query per chat message
   (`token_limit.py:any_rate_limit_exists`). Any change to the token-limit
   check must preserve this short-circuit or the chat endpoint takes a DB
   round trip added by feature that is disabled for most deployments.
5. **The admin-entered token budget is in thousands.** `TOKEN_BUDGET_UNIT =
   1000` converts on read (`_token_budget_reset`); a change here without
   updating the admin UI's label or `MAX_TOKEN_BUDGET_THOUSANDS` silently
   changes what every existing limit enforces.
6. **A cost-only limit must not trigger the token-usage scan, and vice
   versa.** `_has_token_budget` / `cost_budget_limits` split the two so a
   long cost-only window does not widen the token-bucket query
   (`_user_is_rate_limited_by_global`'s comment on this is explicit).
7. **Rejected invite/signup attempts must not consume budget.**
   `enforce_invite_rate_limit` checks before incrementing (single atomic Lua
   script); `reserve_trial_invites` rolls back the session on rejection so a
   failed request does not burn the lifetime trial cap.

---

## 6. Relationships

**Depends on**
- [[editions-and-gating]]: `fetch_versioned_implementation` is how CE/USER+USER_GROUP-blind
  enforcement becomes EE's three-scope enforcement, and how CE's
  no-trial-detection becomes EE's control-plane-backed detection.
- [[multi-tenancy]]: every counter (`user_usage`, `tenant_usage`,
  `tenant_invite_counter`, the rate-limit-exists cache) is tenant-scoped;
  `USAGE_LIMITS_ENABLED` itself defaults to `MULTI_TENANT`.
- [[observability]]: `user_usage` rows are written by the tracing pipeline
  (`tracing/processors/user_usage_processor.py`), not by this component; the
  token-budget check reads a table it does not populate.
- [[llm-providers]]: `is_onyx_managed_api_key` and `check_llm_cost_limit_for_provider`
  only apply the cost cap when Onyx's own default provider key is in use.
- [[auth-and-identity]]: signup and invite limits sit inline in
  `auth/users.py` and `server/manage/users.py`; anonymous/API-key user
  detection (`AccountType.SERVICE_ACCOUNT`, `is_api_key_email_address`)
  changes which token-limit scopes apply.

**Depended on by**
- [[core-chat-loop]]: `check_token_rate_limits` and `check_api_key_usage` gate
  `handle_send_chat_message`.
- [[chat-frontend]]: renders the 429/`RATE_LIMITED` payload as a
  `StreamingError` banner.
- [[editions-and-gating]]: the token-rate-limit admin router is the concrete
  example of "an EE-only router the CE app never mounts."
- Craft/Build (no dedicated component doc yet): `features/build/session/messages.py`
  calls `check_token_rate_limits` inline for both the main send-message and
  subagent send-message endpoints.
- [[indexing-pipeline]]: `check_global_token_rate_limits` runs inside the
  indexing pipeline's LLM-using steps.
- [[onyx-api]]: any API-key/PAT caller of `/chat/send-chat-message` is subject
  to both `check_token_rate_limits` (GLOBAL scope only if it resolves to an
  API-key identity) and `check_api_key_usage`.
- [[slack-bot]]: calls `check_token_rate_limits` inline before each answer;
  see §9.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a new chat entry point (a new endpoint or in-process call that drives `handle_stream_message_objects` or an equivalent LLM turn) | it must declare `check_token_rate_limits`, and, if it can be reached with an API key/PAT, `check_api_key_usage`; otherwise it is an unmetered, unlimited path. An in-process caller must call the check inline, as the Slack bot does (§9) |
| changes the token-rate-limit scope model (adds a scope, changes CE/EE split) | the EE `_check_token_rate_limits` parallel-check list, the admin UI tabs (`TokenRateLimitsPanel.tsx:enterpriseTier`), and `get_token_rate_limit_scope_and_group_ids` |
| changes the 429 error shape (`error_code`, `extra` keys, status code) | `web/src/app/app/services/lib.tsx` and `web/src/app/craft/components/BuildMessageList.tsx`, both of which pattern-match the exact fields; a mismatch degrades to an opaque thrown error instead of the usage banner |
| changes counter storage (moves `user_usage` off the daily-rollup model, or `tenant_usage` off the fixed-window model) | the token-budget scan's cutoff-time math (`_get_cutoff_time`, `get_token_window_start`) and the tenant-usage window math (`get_current_window_start`); both assume the current bucket shape |
| changes how tenant trial status or overrides are fetched | `ee/.../tenant_usage_limits.py`'s 24h/30min refresh cadence and its trial-restrictive fail-safe on error |
| changes the invite or signup Redis scripts | the fail-open behavior on Redis errors (invite limiter) versus fail-closed-on-exception behavior (signup limiter logs and returns, also effectively fails open); keep both consistent with the "Lite" no-Redis deployment story |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/unit/onyx/server/query_and_chat/test_token_limit.py
cd backend && uv run pytest tests/unit/onyx/server/query_and_chat/test_any_rate_limit_exists_tenant_scope.py
cd backend && uv run pytest tests/unit/ee/onyx/db/test_user_group_cost_token_limit.py
cd backend && uv run pytest tests/unit/ee/onyx/server/token_rate_limits
cd backend && uv run pytest tests/unit/onyx/server/test_token_rate_limit_budget_models.py
cd backend && uv run pytest tests/unit/onyx/server/manage/test_invite_rate_limit.py
cd backend && uv run pytest tests/unit/onyx/auth/test_signup_rate_limit.py
cd backend && uv run pytest tests/external_dependency_unit/server/test_feedback_rate_limiting.py
cd backend && uv run pytest tests/integration/tests/streaming_endpoints/test_user_usage_tracking.py
cd backend && uv run pytest tests/integration/tests/streaming_endpoints/test_gateway_usage_tracking.py
```

See `backend/AGENTS.md` for required env and secrets.

### Manual reproduction (trip a token rate limit locally)

1. As an admin, `POST /admin/token-rate-limits/global` (EE build) with a
   tiny `token_budget` (e.g. `1`, meaning 1000 tokens) and `period_hours: 1`.
2. Send one chat message that produces a real LLM response, large enough to
   exceed 1000 tokens combined input+output.
3. Send a second chat message. `POST /chat/send-chat-message` returns 429
   with `error_code: "RATE_LIMITED"` and `extra.reset_at` roughly one hour
   out.
4. In the web UI, confirm the message renders as a non-retryable usage-limit
   banner, not a generic error.
5. Confirm `invalidate_any_rate_limit_exists_cache()` took effect immediately
   in this process; a second admin process may lag up to 60s
   (`_ANY_RATE_LIMIT_EXISTS_CACHE_TTL_SECONDS`).

### What "working" looks like

- A configured limit blocks the exact scope it names and no other.
- The reset time returned is honored: waiting past `reset_at` and retrying
  succeeds.
- No entry point that reaches an LLM call for a limited scope skips the
  check silently.

---

## 9. Footguns

- **The Slack bot and `POST /search` call the chat engine or the LLM in
  process, so no route dependency protects them.** Each one calls
  `check_token_rate_limits` inline: the Slack bot charges it to `usage_user`
  (the mapped Onyx user, else the Slack service account) before it builds the
  answer (`handle_regular_answer.py`), and `search/api.py:search` checks the
  caller before it resolves an LLM. A new in-process entry point gets no
  budget check unless it adds one. `SlackRateLimiter` (`ONYX_BOT_MAX_QPM`) is
  a separate, per-process QPM gate and is not a budget.
- **The AI Gateway (`ee/onyx/server/gateway/api.py`) checks
  `check_token_rate_limits` and the cloud cost cap, but never
  `check_api_key_usage` (on purpose, see [[llm-gateway]] §4.8).** Gateway
  callers authenticate via `Permission.USE_LLM_GATEWAY`, not necessarily the
  API-key/PAT path `check_api_key_usage` inspects, but if a PAT is used here
  it is not counted toward the tenant API-call cap the way the same PAT
  would be on `/chat/send-chat-message`.
- **Craft/Build (`features/build/session/messages.py`) checks
  `check_token_rate_limits` on both send-message endpoints but never
  `check_api_key_usage`.** A Craft turn driven by an API key/PAT does not
  count against the tenant's API-call cap.
- **The MCP surface spends LLM tokens through `POST /search`.** Its
  `search_indexed_documents` tool calls that endpoint, and the retrieval
  pipeline makes LLM calls: `select_sections_for_expansion` every time, and
  `keyword_query_expansion` and `decide_time_filter` unless query expansion
  is skipped. `/search` runs all three checks (token budgets, the cloud cost
  cap, and `check_api_key_usage`). The MCP server's `search_web` and
  `open_urls` tools spend web-search provider quota, which none of these
  checks meter. See [[mcp-server]] §9.
- **Community Edition cannot create or edit any `TokenRateLimit`, including
  GLOBAL scope, through the admin API.** `ee/onyx/server/token_rate_limits/api.py`
  says so directly: "Spending limits are an Enterprise feature, so every
  endpoint here is mounted only by the EE app." The CE enforcement code
  (`onyx/server/query_and_chat/token_limit.py:_check_token_rate_limits`)
  does support GLOBAL scope, but a CE deployment has no supported way to
  populate that row short of writing to the database directly.
- **`user_usage` is populated asynchronously, with a lag.** Token usage is
  written by `tracing/processors/user_usage_processor.py`, a background
  drain thread flushing every 2 seconds or every 200 buffered spans
  (`_DEFAULT_FLUSH_INTERVAL_SECONDS`, `_FLUSH_BATCH_SIZE`), not synchronously
  inside `check_token_rate_limits`. A user can send several messages in
  quick succession before their own prior usage lands in the table the
  check reads, allowing a short burst past the budget.
- **`check_api_key_usage` is a no-op for ordinary cookie-session users.** It
  only checks/increments when the request carries a hashed API key or PAT
  (`get_hashed_api_key_from_request`, `get_hashed_pat_from_request`); web UI
  chat traffic never touches the tenant `api_calls` counter.
- **The invite rate limiter fails open on Redis errors by design.** It runs
  only for cloud trial tenants (`MULTI_TENANT and is_tenant_on_trial_fn`,
  `server/manage/users.py`); self-hosted and Lite never call it. The trial's
  lifetime invite cap (`NUM_FREE_TRIAL_USER_INVITES`, `reserve_trial_invites`)
  is a Postgres counter and holds during a Redis outage. What an outage loses
  is the per-minute and per-day Redis buckets, which exist to stop the
  invite -> remove -> invite cycle (removal releases a trial slot) from
  sending unlimited invite emails.
- **HTTP-level auth rate limiting is off unless both `RATE_LIMIT_MAX_REQUESTS`
  and `RATE_LIMIT_WINDOW_SECONDS` are set**; a fresh deployment has no IP
  throttle on login/signup HTTP traffic beyond the separate, `MULTI_TENANT`-
  gated `enforce_signup_rate_limit`.
