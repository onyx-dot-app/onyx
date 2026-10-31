# Rate and Usage Limits

> Separate mechanisms that throttle or cap usage: token and cost budgets,
> tenant usage limits, the API-call cap, HTTP rate limits, and signup and invite
> limits. Each has its own storage, scope and enforcement point.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE enforces GLOBAL token budgets only. EE adds USER and USER_GROUP
scope and is the only edition that can create a budget. Tenant usage limits are
on by default only on cloud (`USAGE_LIMITS_ENABLED`). HTTP, signup and invite
limits are CE.

---

## User experience

- **A user over a token or cost budget** sees the message fail with a "Usage
  limit reached" banner. The banner names the scope that tripped (your account,
  your user group or your organization) and when the budget resets. It has no
  retry button, because a retry trips the same budget. Craft shows the same
  banner.
- **An EE admin** sets budgets at Admin > Token Rate Limits: thousands of tokens
  or cents, over a period, for the whole workspace, each user, or a user group. A
  CE workspace has no such page.
- **A cloud tenant** that passes its weekly LLM cost, indexed chunks or API calls
  gets a 429 that names the metric and asks it to upgrade or wait. A trial has
  lower limits than a paid tenant. Its own admin cannot raise the limit.
- **An API key or PAT caller on cloud** has a weekly call allowance on the chat
  and search routes. A trial tenant's allowance is zero by default, so its API
  calls get a 429 that says the API needs a paid plan.
- **Signup and invite limits** are invisible in normal use. They stop scripted
  abuse, such as one IP creating many accounts.

---

## Scope

This component owns the mechanisms in the table. They share a name, but know
which one you are touching before you change it.

| Mechanism | Limits | Scope | Storage | Entry point |
|---|---|---|---|---|
| Token and cost budgets | LLM tokens or cents in a period, set by an admin | GLOBAL, USER, USER_GROUP | `user_usage` daily rollup | `check_token_rate_limits` |
| Tenant usage limits | Weekly LLM cost, indexed chunks, API calls, non-streaming calls, set by the Onyx control plane | Tenant, trial or paid | `tenant_usage` fixed window | `check_usage_and_raise`, `check_llm_cost_limit_for_provider` |
| API key and PAT call cap | One tenant usage limit, counted per request | Tenant | `tenant_usage.api_calls` | `check_api_key_usage` |
| HTTP rate limits | Requests to the auth and OAuth provider routers, and to chat feedback | IP and User-Agent, or user | Redis (`fastapi_limiter`) | `get_auth_rate_limiters`, `get_feedback_rate_limiters` |
| Signup and invite limits | Scripted abuse on cloud | IP, admin, tenant | Redis, plus `tenant_invite_counter` | `enforce_signup_rate_limit`, `enforce_invite_rate_limit` |

Its neighbours own:
- [[observability]]: the tracing pipeline that writes `user_usage`.
- [[billing]]: the license seat limit and the trial-status cache.
- [[slack-bot]]: the bot's per-process QPM gate (`SlackRateLimiter`).
- [[llm-gateway]]: the gateway endpoints, which do not call the API-call cap.

---

## Architecture

**The checks are plain functions, not middleware.** Each entry point that spends
a limited resource calls the check itself, as a FastAPI `Depends` or inline. Use
`git grep -w check_token_rate_limits` to list the current call sites. Inline
calls exist where no route dependency can apply: the Slack bot
(`backend/onyx/onyxbot/slack/handlers/handle_regular_answer.py`), chat session
naming, the AI Gateway, the EE search flow when it runs LLM steps, and the
indexing pipeline (`check_global_token_rate_limits`, GLOBAL scope, no user).

**Token and cost budgets.** `check_token_rate_limits` returns at once when
`any_rate_limit_exists()` says the tenant has no enabled budget. That answer is
cached per tenant for 60 s. Otherwise it dispatches to the CE or EE
`_check_token_rate_limits` through `fetch_versioned_implementation`. EE runs the
USER, USER_GROUP and GLOBAL checks in parallel. Each scope sums the `user_usage`
buckets in the widest window and raises at the latest reset among the budgets it
exceeds. A caller who waits until that time does not trip a budget that clears
later.

**Tenant usage limits.** These are synchronous counters on `tenant_usage`. Each
check reads the trial status and a per-tenant override from the control plane
(`backend/ee/onyx/server/tenant_usage_limits.py`, refreshed every 24 h), then
falls back to the env-var default. Checks run before the increment, so the
rejected request is not counted. Docprocessing increments
`UsageType.CHUNKS_INDEXED` after each batch, and a failed increment does not fail
indexing. LLM enrichment at indexing (contextual RAG and image summarization)
checks the global budget per batch
(`backend/onyx/indexing/indexing_pipeline.py:_partition_documents_blocked_by_llm_spend_limit`).
A document that needs a blocked enrichment becomes a per-document failure.

**Craft.** Both Craft send-message routes call `check_token_rate_limits`
(`backend/onyx/server/features/build/session/messages.py`). On a 429 the Craft
frontend shows the chat usage banner and keeps the session error set, so queued
prompts do not send into the limit.

**Credential attribution.**
`backend/onyx/auth/users.py:_resolve_optional_user` records which credential
authenticated the request (session, PAT, Craft PAT, API key or the OAuth
provider) in `request.state.usage_credential`. `optional_user` copies it into
`CURRENT_USAGE_CREDENTIAL_CONTEXTVAR` for the usage recorder.

**Signup and invite limits.** These run only on cloud, and invite limits only for
trial tenants (`backend/onyx/server/manage/users.py`). The lifetime trial invite
cap is a Postgres row lock
(`backend/onyx/db/tenant_invite_counter.py:reserve_trial_invites`), and a
rejected reservation rolls back. The invite per-minute and per-day buckets are
Redis keys. One Lua script checks every bucket before it increments any, so a
rejected request uses no budget. The signup limiter increments first, so a
rejected signup attempt still counts.

---

## Contracts and traps

1. `every-entry-point-checks` **Every entry point that spends LLM budget must
   call the check itself.** A new route, task or in-process caller that drives an
   LLM call is unmetered until it calls
   `backend/onyx/server/query_and_chat/token_limit.py:check_token_rate_limits`.
   If an API key or PAT can reach it, it must also call
   `backend/onyx/server/api_key_usage.py:check_api_key_usage`. If it can use an
   Onyx-managed provider key, it must call
   `backend/onyx/server/usage_limits.py:check_llm_cost_limit_for_provider`.
   `backend/onyx/llm/factory.py:get_llm_for_persona` does not run the cost check,
   so its callers must. `get_default_utility_llm` and `get_decision_client` run
   it themselves.
2. `budget-before-api-call-count` **Run the budget check before
   `check_api_key_usage`.** `check_api_key_usage` increments the API-call counter
   when it runs. The order in `backend/onyx/server/features/search/api.py:search`
   keeps a request that the budget rejects from using an API call.
3. `rate-limited-shape` **The 429 shape is a client contract.**
   `backend/onyx/server/query_and_chat/token_limit.py:raise_rate_limited` sends `OnyxErrorCode.RATE_LIMITED` with `scope`,
   `reset_at` and `retry_after_seconds` in the body (passed as `OnyxError`
   `extra`) and a `Retry-After` header. The chat client
   (`web/src/app/app/services/lib.tsx`) and Craft
   (`web/src/app/craft/services/apiServices.ts`) match `error_code` and turn it
   into a usage banner with no retry. If you change the code or drop `reset_at`,
   both show an opaque error. The HTTP limiters do not use this shape:
   `fastapi_limiter` sends a plain 429 with no `error_code`.
4. `any-rate-limit-exists-fast-path` **Keep the `any_rate_limit_exists` fast
   path, and keep it keyed by tenant.**
   (`backend/onyx/server/query_and_chat/token_limit.py:any_rate_limit_exists`)
   Most deployments have no budget. Without
   the cache, every chat message costs a query. Without the tenant key, one
   tenant's "no budgets" answer turns off enforcement for another tenant in the
   same worker. After a write, call `invalidate_any_rate_limit_exists_cache`.
   Other processes can lag by up to 60 s.
5. `token-budget-in-thousands` **`token_budget` is stored in thousands of
   tokens.** `backend/onyx/server/query_and_chat/token_limit.py:TOKEN_BUDGET_UNIT`
   scales it on read. The admin UI enters the same
   unit. A change to one side changes what every existing budget enforces.
6. `untraced-call-not-counted` **An LLM call outside a root trace is not
   counted.** It writes no `user_usage` row, so budgets miss it
   ([[observability#root-trace-required]]).
7. `budgets-lag-usage` **Budgets lag real usage by a few seconds.**
   `backend/onyx/tracing/processors/user_usage_processor.py` writes `user_usage`
   from tracing spans in batches, every 2 s or every 200 spans. Quick messages
   can pass a budget before earlier usage lands. A limit test must wait for the
   flush.
8. `shared-principals-global-only` **Shared principals get GLOBAL budgets only.**
   Anonymous users, service accounts and API-key users skip USER and USER_GROUP
   checks
   (`backend/ee/onyx/server/query_and_chat/token_limit.py:_check_token_rate_limits`). A service account carries traffic
   for many callers, such as every Slack user with no Onyx account, so a per-user
   budget would throttle them as one. A PAT resolves to its owner and gets all
   three scopes.
9. `cost-and-token-scans-separate` **Cost and token budgets do not widen each
   other's scans.** A cost-only budget skips the token query, and a long cost
   window does not extend the token cutoff
   (`backend/onyx/server/query_and_chat/token_limit.py:_user_is_rate_limited_by_global`).
   Token budgets reset at the UTC-day boundary where the trailing window drops
   under budget. Cost budgets reset at fixed daily, weekly or monthly boundaries.
10. `cost-cap-managed-keys-only` **The cloud cost cap applies only to
    Onyx-managed provider keys.**
    `backend/onyx/server/usage_limits.py:check_llm_cost_limit_for_provider`
    returns early when `is_onyx_managed_api_key` is false. A tenant with its own
    key is exempt.
11. `control-plane-failure-directions` **The two control-plane reads fail in
    opposite directions.** When the trial status cannot be read,
    `backend/ee/onyx/server/usage_limits.py:is_tenant_on_trial` treats the tenant
    as a trial, which has the lower limits. The status is cached per tenant
    (`backend/ee/onyx/server/billing/billing_cache.py`), and
    [[billing#invalidate-billing-cache]] says which call clears it. When the
    override fetch fails and no earlier fetch succeeded,
    `backend/ee/onyx/server/tenant_usage_limits.py:get_tenant_usage_limit_overrides`
    returns no limit for every tenant, and it retries after 30 minutes. `DEV_MODE`
    also lifts every tenant limit.
12. `api-call-cap-skips-cookies` **`check_api_key_usage` does nothing for cookie
    sessions.** (`backend/onyx/server/api_key_usage.py:check_api_key_usage`) It counts only requests that carry an API key or PAT. Web UI
    traffic never touches `api_calls`.

---

## Decisions

- **The AI Gateway and Craft do not count toward the API-call cap.** A coding
  agent makes hundreds of gateway calls in one session. Whether those count
  toward the cloud cap is an open product decision. Both surfaces still check
  token budgets, and the gateway also checks the managed-key cost cap.
- **Only EE can create a budget.** The admin router lives in the EE server code
  and mounts only in the EE app. CE enforcement can read a GLOBAL budget, but CE
  has no supported way to create one. The Community downgrade deletes every
  budget ([[billing]]).
- **Budgets read a rollup, not a live counter.** Budgets reuse the usage data
  that tracing already records. The cost of this choice is the short lag in
  [[#budgets-lag-usage]].

---

## Known issues

- **Web-search quota has no meter.** The MCP server's `search_web` and
  `open_urls` tools spend web-search provider quota that no check counts
  ([[mcp-server]]).
- **The signup and invite limiters fail open.** The invite limiter lets a
  request through on a Redis error, and the signup limiter returns on any error.
  The Postgres lifetime invite cap still holds during a Redis outage. The Redis
  buckets stop the invite, remove and invite again cycle, which would send
  unlimited invite emails.
- **Two limiters call Redis directly.** The signup and invite limiters use Redis,
  not `CacheBackend` (`backend/AGENTS.md`). They run only on cloud, where Redis
  exists.
- **Auth rate limiting is off by default.** It needs both
  `RATE_LIMIT_MAX_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS`. A new self-hosted
  deployment has no IP throttle on login.

---

## Dependencies

- [[observability]]: the tracing pipeline writes `user_usage`, which budgets read.
- [[editions-and-gating]]: `fetch_versioned_implementation` selects the CE or EE
  check.
- [[multi-tenancy]]: every counter and the fast-path cache are tenant-scoped.
- [[llm-providers]]: `is_onyx_managed_api_key` decides whether the cost cap
  applies.
- [[billing]]: the cached trial status that sets trial or paid limits.

---

## Recipes

- `add-llm-entry-point` **Add an LLM entry point.** Copy `backend/onyx/server/features/search/api.py:search`:
  `Depends(check_token_rate_limits)` before `Depends(check_api_key_usage)`
  ([[#budget-before-api-call-count]]), and `check_llm_cost_limit_for_provider`
  once the provider is known. Outside a route, call the checks inline, as the
  Slack bot does. List the current entry points with
  `git grep -n "check_token_rate_limits\|check_llm_cost_limit_for_provider" backend`.
- `add-budget-scope` **Add a budget scope.** Change the EE parallel check list, the admin UI scope
  tabs (`web/src/app/admin/token-rate-limits/`) and
  `backend/onyx/db/token_limit.py:get_token_rate_limit_scope_and_group_ids`.
- `add-tenant-usage-type` **Add a tenant usage type.** Copy `UsageType.NON_STREAMING_API_CALLS`: add it to
  `backend/onyx/db/usage.py:UsageType`, the `tenant_usage` columns, the env
  defaults in `shared_configs/configs.py`, `_FIELD_AND_DEFAULT` in
  `backend/onyx/server/usage_limits.py`, and the override model
  `TenantUsageLimitOverrides`.
- `trip-budget-by-hand` **Trip a budget by hand.** On an EE build, create a GLOBAL budget of
  `token_budget: 1` (1,000 tokens) for one hour. Send one long chat message, wait
  2 s for the usage flush, and send another. The second gets the 429 and the
  banner.
- `investigate-limit-not-applied` **Investigate "my limit did not apply".** Check, in order: the entry point
  calls the check ([[#every-entry-point-checks]]); the call ran inside a root
  trace ([[#untraced-call-not-counted]]); the principal is not shared
  ([[#shared-principals-global-only]]); for a new budget, 60 s have passed
  ([[#any-rate-limit-exists-fast-path]]); on cloud, the override fetch succeeded
  ([[#control-plane-failure-directions]]).

---

## Verification

- Unit tests: `backend/tests/unit/onyx/server/query_and_chat/`,
  `backend/tests/unit/ee/onyx/server/token_rate_limits/`,
  `backend/tests/unit/onyx/server/manage/` and `backend/tests/unit/onyx/auth/`.
- Entry-point order: `backend/tests/external_dependency_unit/server/`.
- End-to-end usage recording: `backend/tests/integration/tests/streaming_endpoints/`.
