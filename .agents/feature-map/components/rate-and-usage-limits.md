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
  your group allowance, your user group or your organization) and when the
  budget resets. A limit on one model also says other models are still
  available. It has no retry button, because a retry trips the same budget.
  Craft shows the same banner.
- **An Enterprise admin** sets budgets at Admin > Spending Limits: cost or
  thousands of tokens per day, week or month, on all models or one model, for
  the workspace pool, each user, a group's pool or each member of a group. A
  group manager edits their group's pool on the group page; per-member limits
  are admin-only. A CE workspace has no such page.
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
| Token and cost budgets | LLM tokens or cents in a period, on all models or one, set by an admin | GLOBAL, USER, USER_GROUP, USER_GROUP_MEMBER | `user_usage` daily rollup | `check_token_rate_limits`, `check_model_spend_limits` |
| Tenant usage limits | Weekly LLM cost, indexed chunks, API calls, non-streaming calls, set by the Onyx control plane | Tenant, trial or paid | `tenant_usage_counter`, one row per usage type per period | `check_usage_and_raise`, `check_llm_cost_limit_for_provider` |
| API key and PAT call cap | One tenant usage limit, counted per request | Tenant | `tenant_usage_counter` row for `api_calls` | `check_api_key_usage` |
| HTTP rate limits | Requests to the auth and OAuth provider routers, and to chat feedback | IP and User-Agent, or user | Redis (`fastapi_limiter`) | `get_auth_rate_limiters`, `get_feedback_rate_limiters` |
| Signup and invite limits | Scripted abuse on cloud | IP, admin, tenant | Cache backend, plus `tenant_invite_counter` | `enforce_signup_rate_limit`, `enforce_invite_rate_limit` |

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

**Token and cost budgets.** Each `token_rate_limit` row sets a token budget, a
cost budget or both, for one period: a UTC calendar day, a week from Monday, or
a calendar month (`TokenRateLimitPeriod`). A row applies to all models, or to
one `model_configuration_id`. Only enabled `BLOCK` rows are enforced;
`ALERT_ONLY` rows are stored for a future notification feature. The four scopes
combine like this
(`backend/ee/onyx/server/query_and_chat/token_limit.py`):

- **GLOBAL**, the workspace pool: every budget must have room.
- **USER_GROUP**, a group pool of all members' usage: the user passes if any
  of their groups with an applicable pool has room. Group pools never block
  across groups.
- **USER_GROUP_MEMBER** and **USER**, the per-user allowance: for each
  (period, unit) the largest group value among the user's groups wins, and the
  workspace default (USER) fills each pair no group sets
  (`resolve_member_allowance`). Only the user's own usage counts.

There are two entry points. `check_token_rate_limits` checks the all-models
rows before a request runs. `check_model_spend_limits` checks the rows for one
model, and runs where the user's chosen model is known: chat turns
(`backend/onyx/chat/process_message.py:_select_models`), chat naming when it
runs the chat's own model, the AI Gateway and the public search API. A chat override must name a configured model
(`backend/onyx/llm/factory.py:_resolve_provider_and_model`), so every chat call
carries the id that model rows match. Usage of a model also counts toward the all-models rows.
Helper calls on the default or utility models count toward model usage but are
blocked only by all-models rows. Each check returns at once when a cached,
per-tenant flag says the tenant has no enforced row of its kind. Otherwise it
dispatches to the CE or EE `_check_spend_limits` through
`fetch_versioned_implementation`. EE runs the three checks in parallel. Each
raises at the latest reset among the budgets it exceeds, so a caller who waits
until then does not trip a budget that clears later.

**Spending limit admin API.** `/admin/spending-limits`
(`backend/ee/onyx/server/spending_limits/api.py`) is shaped like the admin
page's cards: the workspace pool, the workspace per-user default, and each
group's pool and per-member allowance. A `PUT` replaces every row on one card in
one transaction, so the page sends the rows it can't edit (ALERT_ONLY) back
unchanged. The replace locks the card first: the `user_group` row (`NOT_FOUND`
when the group does not exist), or an advisory lock for a workspace card. A
card with any enabled row reads as enabled and lists only its enabled rows. A scoped `MANAGE_USER_GROUPS` holder can read their group's cards
and edit its pool. Everything else needs full admin, including a group's
per-member card: a group allowance beats the workspace default upward, so a
manager could otherwise lift their own limit. `GET /users/{user_id}/effective` returns each budget a
user is held to and the group it comes from; for a shared principal it returns
only the GLOBAL pools ([[#shared-principals-global-only]]). Every write calls
`invalidate_any_rate_limit_exists_cache`. A limit raised inside a chat turn
reaches the client as a `StreamingError` whose `details` carry the 429's
`extra` (`backend/onyx/chat/errors.py:chat_error`).

**Usage reset.** A reset sets `token_rate_limit.usage_reset_at` to now and
snapshots what the current daily usage bucket holds. It does not delete usage
rows, so history and exports stay. Every limit stores one
`token_rate_limit_usage_baseline` row per user with usage in that bucket, every
user, not only those it covers now. A per-user limit subtracts the user's own
row. A pool subtracts the sum over the users it covers now
(`backend/onyx/db/token_limit.py:fetch_pool_usage_baselines`), so the baseline
always matches the pool's usage query when members join or leave. Deleting a
user's usage (`POST /admin/usage/reset`) deletes their baselines for resets in
that window. A limit then counts the buckets after the reset day in full, and
the reset day's bucket minus the baseline, clamped at 0. Earlier buckets drop out. One helper does this math
(`backend/onyx/db/user_usage.py:sum_limit_usage`), and `BudgetWindow` carries
the reset and baseline into enforcement, pool usage on the cards and the Usage
tab budget. A per-user check without the user's baselines counts the whole
reset day, so a missed lookup blocks too early, never too late. A reset in an
earlier period changes nothing. Group managers reset their group's pool limits
through `POST /groups/{group_id}/pool/limits/{limit_id}/reset-usage`; every
other limit resets through the admin-only
`POST /limits/{limit_id}/reset-usage`. The reset takes the card lock, and a
card replace keeps a current reset and its baselines on the new row for the
same bucket (`backend/ee/onyx/db/token_limit.py:replace_card_token_rate_limits`).

**Tenant usage limits.** These are synchronous counters on `tenant_usage_counter`,
one row per usage type per period (`backend/onyx/db/usage.py`). An add is one
upsert statement, so concurrent adds are not lost. The old `tenant_usage` table
is no longer read or written ([TECH-DEBT](../TECH-DEBT.md)).

- **Policies.** Each plan has one `LimitPolicy` in
  `backend/onyx/server/usage_limits.py`: `CLOUD_TRIAL` and `CLOUD_PAID` on cloud,
  and `PLAYGROUND` when `IS_PLAYGROUND` is set. The playground skips the billing
  lookup. The types are in `backend/onyx/server/models.py`.
- **Allowances.** A policy has one `Allowance` per limit: the amount, the window,
  whose usage counts, where the usage is read from, and the override field that
  can replace the amount. If a policy has no allowance for a usage type, that
  usage type is not limited on that plan.
- **Periods (windows).** Each `tenant_usage_counter` row holds a tenant's usage
  of one usage type for one period: a start, an end (none for a period that
  never ends) and what it follows (`WindowAnchor`). A new period gets a new row
  that starts at zero; that is how a limit resets. Changing an allowance's
  window therefore starts its count again. Each allowance's window says which period it uses:
  - `CALENDAR`: the calendar week, Monday 00:00 UTC to the next Monday, the same
    for every tenant. Used by cloud. A tenant that signs up on Wednesday is in the
    week that started on Monday.
  - `TENANT_START` with a length: periods start at this tenant's trial start. With
    7 days and a trial that started Wednesday 14:07, the periods run Wednesday
    14:07 to the next Wednesday 14:07, and so on. Used by the playground for LLM
    cost.
  - `TENANT_START` with no length: one period for the whole trial. Used by the
    playground for chunks.

  `TENANT_START` periods need the tenant's trial start. On the playground it
  comes from the control plane through the per-tenant cache below. When it is
  missing, a limit with a length uses calendar periods of that length (the
  calendar week for 7 days), and a whole-trial limit counts in one period that
  never ends, so it cannot reset weekly. A warning is
  logged at most once an hour per tenant in each process. Until the control plane serves the
  trial start, that is every tenant ([TECH-DEBT](../TECH-DEBT.md)).

  The check (before an action) and `record_usage` (after it) both call
  `period_for` to find the current period, so they always read and write the
  same row.
- **Adding usage.** Every place that adds usage calls `record_usage`. It uses the
  cloud trial policy's windows and does no billing lookup, so both cloud plans
  must use the same windows. This is checked when the module loads.
- **Per-user counts.** A `DERIVED` allowance counts rows that already exist
  instead of a counter, and a `USER` scope counts one user; the check then needs
  `user_id`. The playground allows each user
  `USAGE_LIMIT_IMAGE_GENERATIONS_PER_USER_PLAYGROUND` chat images for the whole
  trial, counted from the image files the chat image tool saved in the user's
  chat sessions (`backend/onyx/db/usage.py:count_generated_images`). The tool
  saves them during the call, only once the images are made, so a later check
  sees them. The limit is soft on purpose: parallel image calls and two turns
  at once reserve nothing, so a user can end a few images over it. A usage
  type no plan in force limits returns before any lookup
  (`is_usage_type_limited`), so cloud does no work for it.
- **Playground cache.** `backend/ee/onyx/server/tenants/usage_limit_cache.py`
  keeps each playground tenant's trial start and overrides. The control plane
  owns them; the data plane only caches them, like the billing cache: a miss
  reads one tenant from the control plane, and a failed read caches an empty
  value for 60 seconds so the control plane is not asked on every request. The
  trial start never changes, so each process also keeps it in memory. A sales
  raise is pushed to `POST /tenants/usage-limit-overrides` and applies at once.
  A playground override replaces the plan's amount.
- **Ingestion API.** On the playground, documents pushed to the ingestion API
  are checked against and counted toward the chunk limit, like connector
  indexing. On cloud they are not counted.
- **Overrides.** On cloud, each check finds the plan from the trial status and
  reads the tenant's override from the control plane
  (`backend/ee/onyx/server/tenant_usage_limits.py`, refreshed every 24 h). If
  there is no override, the policy's amount applies. An override replaces the
  amount. It is not added to it.

Checks run before the increment, so the
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
cache keys. One cache lock for each tenant covers the check and the increment.
The limiter checks every bucket before it increments any, so a rejected request
uses no budget. The signup limiter increments first, so a
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
2. `budget-before-api-call-count` **Run the all-models budget check before
   `check_api_key_usage`.** `check_api_key_usage` increments the API-call counter
   when it runs. The order in `backend/onyx/server/features/search/api.py:search`
   keeps a request that the all-models limits reject from using an API call.
   The checks that need the model (`check_model_spend_limits` and
   `check_llm_cost_limit_for_provider`) run after the handler resolves the
   model, so a request that only they reject still uses an API call.
3. `rate-limited-shape` **The 429 shape is a client contract.**
   `backend/onyx/server/query_and_chat/token_limit.py:raise_rate_limited` sends `OnyxErrorCode.RATE_LIMITED` with `scope`,
   `reset_at` and `retry_after_seconds` in the body (passed as `OnyxError`
   `extra`) and a `Retry-After` header. A limit on one model adds `model`, the
   model's display name. The chat client
   (`web/src/app/app/services/lib.tsx`) and Craft
   (`web/src/app/craft/services/apiServices.ts`) match `error_code` and turn it
   into a usage banner with no retry. If you change the code or drop `reset_at`,
   both show an opaque error. The HTTP limiters do not use this shape:
   `fastapi_limiter` sends a plain 429 with no `error_code`.
4. `any-rate-limit-exists-fast-path` **Keep the `any_rate_limit_exists` and
   `any_model_spend_limit_exists` fast paths, and keep them keyed by tenant.**
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
   Anonymous users, service accounts and API-key users skip the group and
   per-user checks
   (`backend/ee/onyx/server/query_and_chat/token_limit.py:is_shared_spend_principal`). A service account carries traffic
   for many callers, such as every Slack user with no Onyx account, so a per-user
   budget would throttle them as one. A PAT resolves to its owner and gets all
   three scopes.
9. `cost-and-token-scans-separate` **Cost and token budgets do not widen each
   other's scans.** A cost-only budget skips the token query, and a long cost
   window does not extend the token cutoff
   (`backend/onyx/server/query_and_chat/token_limit.py:_user_is_rate_limited_by_global`).
   Both kinds reset at the end of their calendar period
   (`backend/onyx/db/user_usage.py:get_period_window_reset`).
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
- **The playground's per-user image limit is soft.** The check reserves
  nothing, image calls in one model step keep running in parallel, and a user
  can run two turns at once, so calls that start together all pass and a user
  can end a few images over the limit. That is accepted: a trial user should
  see the tool make several images at once, and the extra images cost cents.
  Making the calls sequential or reserving images first is not wanted.
- **Only EE can create a budget.** The admin router lives in the EE server code
  and mounts only in the EE app. CE enforcement can read a GLOBAL budget, but CE
  has no supported way to create one. The Community downgrade deletes every
  budget ([[billing]]).
- **Group pools never block across groups, and the largest group allowance
  wins.** A user in several groups should not be stopped by one team's pool while
  another team pays for them, and a group exists to lift its members' limits.
  The costs, documented for admins: joining a group can add a limit for a
  (period, unit) the user had none for, a group must set a pair to lift the
  workspace default for it, and a group made for one user can't lower that
  user below a more generous group they are in.
- **Budgets read a rollup, not a live counter.** Budgets reuse the usage data
  that tracing already records. The cost of this choice is the short lag in
  [[#budgets-lag-usage]].

---

## Known issues

- **Web-search quota has no meter.** The MCP server's `search_web` and
  `open_urls` tools spend web-search provider quota that no check counts
  ([[mcp-server]]).
- **The signup and invite limiters fail open.** The invite limiter lets a
  request through on a cache error or a busy lock, and the signup limiter
  returns on any error. The Postgres lifetime invite cap still holds during a
  cache outage. The cache buckets stop the invite, remove and invite again cycle, which would send
  unlimited invite emails.
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
- `add-budget-scope` **Add a budget scope.** Change the EE checks
  (`backend/ee/onyx/server/query_and_chat/token_limit.py:_check_spend_limits`),
  the card routes in `backend/ee/onyx/server/spending_limits/api.py` and the
  admin page (`web/src/views/admin/SpendingLimitsPage/`). A scope that names a group
  also goes in the `ck_token_rate_limit_group` check on `token_rate_limit`.
- `add-tenant-usage-type` **Add a tenant usage type.** Copy `UsageType.NON_STREAMING_API_CALLS`: add it to
  `backend/onyx/db/enums.py:UsageType` (the counter table needs no new column), the env
  defaults in `shared_configs/configs.py`, the override model
  `TenantUsageLimitOverrides`, and one `Allowance` line on each policy in
  `backend/onyx/server/usage_limits.py` that limits it. A type a cloud policy
  limits also goes in `_CLOUD_TYPES` in
  `backend/tests/unit/onyx/server/test_usage_limits.py`: the policy test fails
  until both cloud policies list exactly those types. A per-user type is a
  `DERIVED` allowance with `scope=LimitScope.USER`, its count under
  `backend/onyx/db/`, and its check passes `user_id`.
- `trip-budget-by-hand` **Trip a budget by hand.** Do this only on a
  disposable test workspace: the PUT replaces every limit on the workspace
  pool. On an EE build, `PUT
  /admin/spending-limits/workspace/pool` with one DAILY limit of
  `cost_budget_cents: 0.001`; one chat message spends more. Send a message, wait
  2 s for the usage flush, and send another. The second gets the 429 and the
  banner. A token budget is at least 1,000 tokens, more than one short message.
- `investigate-limit-not-applied` **Investigate "my limit did not apply".** Check, in order: the entry point
  calls the check ([[#every-entry-point-checks]]); the call ran inside a root
  trace ([[#untraced-call-not-counted]]); the principal is not shared
  ([[#shared-principals-global-only]]); for a new budget, 60 s have passed
  ([[#any-rate-limit-exists-fast-path]]); on cloud, the override fetch succeeded
  ([[#control-plane-failure-directions]]).

---

## Verification

- Unit tests: `backend/tests/unit/onyx/server/test_usage_limits.py`,
  `backend/tests/unit/onyx/server/query_and_chat/`,
  `backend/tests/unit/ee/onyx/server/test_spending_limit_models.py`,
  `backend/tests/unit/onyx/server/manage/` and `backend/tests/unit/onyx/auth/`.
- Entry-point order: `backend/tests/external_dependency_unit/server/`.
- Resolution against real rows:
  `backend/tests/external_dependency_unit/ee/onyx/server/query_and_chat/test_spend_limit_resolution.py`.
- Admin API, a per-member model limit blocking chat, and group-manager gates:
  `backend/tests/integration/tests/spending_limits/` and
  `backend/tests/integration/tests/permissions/test_group_manager_agents.py`.
- End-to-end usage recording: `backend/tests/integration/tests/streaming_endpoints/`.
