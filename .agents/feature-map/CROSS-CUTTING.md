# Cross-cutting checklist

Rules that every new route, middleware, outbound HTTP call, table, task, paid
feature, LLM call or search path must keep. A break in one of them usually
fails with no error. Each item names the code and links to the component that
owns the detail. Read that component before you rely on the short form here.
The order of recipes for a task is in the Common tasks table of
[INDEX.md](INDEX.md#common-tasks); this file holds only the rules.
[ARCHITECTURE.md](ARCHITECTURE.md) shows the processes and flows these rules
sit in.

---

## A new route

- **Give it `Depends(require_permission(Permission.X))`.** At startup,
  `backend/onyx/server/auth_check.py:check_router_auth` raises for a route with no known auth
  dependency that is not in `PUBLIC_ENDPOINT_SPECS`. `current_user` alone passes
  that check, but a scoped PAT is refused on any route without
  `require_permission` or `scope_exempt`
  (`backend/onyx/auth/users.py:_scoped_pat_permitted_on_route`).
  [[authorization#every-route-has-auth-dependency]],
  [[authorization#scoped-pat-fails-closed]].
- **`PUBLIC_ENDPOINT_SPECS` only skips the startup check.** The handler must
  check credentials itself ([[onyx-api#two-meanings-of-public]]). EE adds to
  it in `ee/onyx/server/auth_check.py`. A new entry needs a security review.
- **`allow_scope=True` (GATE 1) needs a GATE 2 check in the handler.** Use
  `auth/scoped_permissions.py:assert_within_scope` for writes, with the current
  groups read from the database, `assert_manages_group` for group edits, and
  `db/scoped_permissions.py:within_managed_scope_clause` for reads. Without
  GATE 2, every group manager gets global reach.
  [[authorization#allow-scope-is-reach-only]],
  [[authorization#gate2-uses-stored-groups]].
- **`allow_anonymous=True` admits the anonymous user.** A new one needs a
  security review. Anonymous, bot and service-account identities are real
  `User` objects, so "no session" does not mean "no user"
  ([[authorization#anonymous-stays-on-chat]]).
- **Take the tenant from the request context, never from input**
  ([[multi-tenancy#tenant-from-auth-only]]).
- **A new guard needs a projection key** so the UI hides what the API refuses
  ([[authorization#projection-mirrors-guard]]).
- **A delete or publish route** follows the per-resource rights table
  ([[authorization#scoped-manager-rights]]).
- **A new or re-gated route changes the route manifest.** Regenerate it as
  [[authorization]] Verification says, and review the gate change in the diff.

## A new middleware

- **Write it as pure ASGI.** Do not use `BaseHTTPMiddleware` or
  `@app.middleware("http")`, or streamed responses lose their request context
  ([[streaming-protocol#pure-asgi-middleware]]).

## A new outbound HTTP call

- **Fetch through the SSRF guard,** with the flags from the admin SSRF
  protection level ([[auth-and-identity#outbound-fetch-uses-ssrf-guard]]).

## A new public API route

- **`tags=PUBLIC_API_TAGS` publishes the route; it does not open it.** The route
  still needs its own auth dependency ([[onyx-api#two-meanings-of-public]]).
- **A published route is a contract.** Change it only in an additive way. The
  steps are in the Common tasks row "A public API route".

## A new table

- **Per tenant or global.** A per-tenant table inherits `db/models.py:Base` and
  goes in `backend/alembic/`. A table that exists once inherits `PublicBase` and
  goes in `backend/alembic_tenants/`. The wrong tree means the table never
  exists, or exists in every tenant ([[multi-tenancy#one-alembic-tree]]).
- **A new tenant clones a snapshot.** A migration effect outside the schema,
  such as Redis keys or files, does not reach it ([[multi-tenancy#snapshot-skips-migrations]]).
- **The Community downgrade.** Rows of a paid feature that keep taking effect,
  and link tables that share a resource with a group, must join
  `ee/onyx/db/community_downgrade.py` ([[billing#paid-rows-join-downgrade]],
  [[access-control]]).
- **Document metadata.** A write that changes a document's ACL inputs, sets,
  boost or cc-pair links must bump `Document.last_modified`, or the index keeps
  the old value ([[document-index#bump-last-modified]]).

## A new thread or Celery task

- **A thread does not inherit the tenant.** Start it with a helper from
  `utils/threadpool_concurrency.py`, such as `run_functions_tuples_in_parallel`,
  `start_thread_with_context` or `start_thread_future`, which copy the context.
  Copy once per thread. An agent-runtime run copies the context once, in
  `agents/runtime.py:Run._start`, so set a context variable before the run
  starts ([[multi-tenancy#threads-copy-context]],
  [[core-chat-loop#threads-copy-context]]).
- **A tenant-scoped task needs a `tenant_id` kwarg.** Without it, `TenantAwareTask` runs in
  the default schema with no error ([[multi-tenancy#celery-task-tenant-kwarg]]).
- **Every new send needs `expires=`** ([[background-jobs#send-expires]]).
- **A new task kwarg needs a default,** because old and new workers and senders
  mix during a rolling deploy ([[background-jobs#task-kwargs-defaults]]).
- **A tenant-scoped Redis or cache key needs the tenant; a cross-tenant key
  uses the shared client** ([[multi-tenancy#tenant-in-cache-keys]]).
- Read the other task rules in [[background-jobs]]: the decorator, the queue,
  the ack mode, sessions across external calls, fences and idempotency.

## A new paid feature

- **Gate on the tier, not the edition.** Use
  `server/settings/tier_order.py:tier_at_least` with `get_current_tier()`.
  `global_version.is_ee_version()` is true on every standard image, licensed or
  not ([[editions-and-gating#loaded-ee-not-unlocked]]).
- **A paid route** goes in `PATH_PREFIX_MIN_TIER`, outside every
  `LICENSE_ENFORCEMENT_ALLOWED_PREFIXES` prefix. Raise `FEATURE_NOT_AVAILABLE`
  for a paid field in a shared route
  ([[editions-and-gating#allowlist-skips-tier-gate]],
  [[editions-and-gating#longest-prefix-match]],
  [[editions-and-gating#one-tier-error-shape]]).
- **CE fallbacks.** Reach EE code through `fetch_versioned_implementation` or
  `fetch_ee_implementation_or_noop` at call time, with the same module path and
  signature on both sides. A no-op must never be the only security control
  ([[editions-and-gating#entry-point-sets-edition]],
  [[editions-and-gating#versioned-symbol-same-signature]],
  [[editions-and-gating#noop-not-only-security-control]]).
- **Plan the downgrade** (see A new table, and
  [[billing#add-paid-feature-to-downgrade]]).

## A new LLM call site

Every call site:

- **Open a root trace** with `tracing/framework/create.py:trace` or
  `ensure_trace`, before `Agent.start` for an agent-runtime run. A span outside
  a trace records no usage, so budgets do not count the call
  ([[observability#root-trace-required]]).
- **Tag it with an `LLMFlow`.** `LLM.invoke` and `LLM.stream` open their own
  generation span from `llm/interfaces.py:GenerationContext.flow`, and
  `agents/runtime.py:Agent` refuses a context with no flow. Another call uses
  `tracing/llm_utils.py:llm_generation_span` or `traced_llm_call`
  ([[observability#tag-llm-flow]]).

A call that a user starts (chat, a bot, an API caller):

- **Check the token budget** with `check_token_rate_limits`, as a `Depends` or
  inline. Then `check_api_key_usage` if an API key or PAT can reach it
  ([[rate-and-usage-limits#every-entry-point-checks]],
  [[rate-and-usage-limits#budget-before-api-call-count]]).
- **Check the cloud cost cap** with
  `backend/onyx/server/usage_limits.py:check_llm_cost_limit_for_provider`.
  `chat/process_message.py` and the default-model helpers in `llm/factory.py`
  call it. A provider built another
  way needs its own call ([[rate-and-usage-limits#cost-cap-managed-keys-only]]).

A call that no user starts (indexing, a background task):

- **Check only the global budget, and do not add the cost cap to one step
  alone** ([[indexing-pipeline#llm-enrichment-step]], [[indexing-pipeline]]
  Known issues). The steps are in the Common tasks row "An LLM step at index
  time".

## A new search path

- Call `context/search/preprocessing/access_filters.py:build_access_filters_for_user`
  and pass both of its fields (`access_control_list` and `cc_pair_access`) into
  `IndexFilters`.
- Query through the document index, never with a hand-built OpenSearch query.
  `DocumentQuery._get_search_filters` is the only place a search gets its ACL
  and tenant clauses ([[document-index#filters-in-one-place]]).
- Run `backend/onyx/access/access.py:censor_chunks_for_user` on every chunk you return
  ([[access-control#censor-every-chunk-reader]]).
- Check caller-supplied document set names with
  `backend/onyx/db/document_set.py:filter_document_set_names_by_user_access`
  ([[access-control#document-set-names-checked]]).
- `access_control_list=None` means no restriction. A new one needs a security
  review ([[access-control#none-acl-means-unrestricted]]).

---

## Who is the acting user

The acting user decides the document ACL, the agent access check and the
budgets. A shared principal (anonymous user, service account, API-key user)
gets GLOBAL budgets only ([[rate-and-usage-limits#shared-principals-global-only]]). The API-call
cap and the cost cap are tenant usage limits. They are on by default only on
cloud (`USAGE_LIMITS_ENABLED`).

| Surface | Acting user | Document ACL | Budgets and caps | Origin |
|---|---|---|---|---|
| Web chat | The signed-in user | The user's | USER, USER_GROUP, GLOBAL. No API-call count. | As sent |
| Web chat, anonymous | `get_anonymous_user()` | Public only | GLOBAL | As sent |
| Slack DM, ephemeral reply, slash command | The mapped Slack user, or `get_anonymous_user()` when no user matches the email | The mapped user's | Charged to the mapped user, or the Slack service account when no user matches | `SLACKBOT` |
| Slack channel post | The turn runs as `get_anonymous_user()`. The agent check uses the mapped user. | Public only for indexed documents. Federated Slack results follow the bot install's token. | Charged to the mapped user, or the Slack service account when no user matches | `SLACKBOT` |
| Discord | The user of one shared service API key | The service account's. The key is in no group. | GLOBAL and the API-call cap, for all members together | `API` |
| Widget, API key | The key's service account | The service account's | GLOBAL and the API-call cap | `API` |
| Widget, JWT passthrough | The visitor's own user | The visitor's | USER, USER_GROUP, GLOBAL | `WIDGET` |
| API key | The key's service account, if active | The service account's | GLOBAL and the API-call cap | `API` |
| PAT | The owner, capped by the token's scopes | The owner's | USER, USER_GROUP, GLOBAL, and the API-call cap | `API` |
| MCP server | The bearer's user (PAT, API key or OAuth grant) | That user's, applied by `/search` | The `/search` checks | none |
| Craft sandbox | The session owner, through a Craft PAT | The owner's | Gateway budgets. No API-call count. | none |

Notes:
- **Federated Slack search ignores the document ACL.** On every surface, the
  Slack token decides what comes back: the bot install's token in a bot turn,
  the user's own token on the web and MCP. A Slack channel post can return
  private Slack messages ([[federated-search#slack-results-have-no-acl]]).
- **Slack.** Only a DM, a slash command or an ephemeral channel reply searches
  as the mapped user ([[slack-bot#public-channel-anonymous-search]]). The
  bot runs the turn in its own process and skips the route's `Depends` checks
  ([[slack-bot#chat-route-depends-skipped]]).
- **Origin.** `backend/onyx/server/query_and_chat/chat_backend.py:handle_send_chat_message`
  sets the origin to `API` for any API key or PAT request. Do not branch on
  `DISCORDBOT` or `WIDGET` on the server for those callers
  ([[discord-bot#discordbot-origin-overwritten]]).
- **Widget passthrough** works only on single-tenant deployments
  ([[desktop-widget-extensions#widget-passthrough-single-tenant]]).
- **Discord.** No Discord member maps to an Onyx user, so a private channel does
  not make answers private ([[discord-bot#no-member-identity]]).
- **Craft** model calls go through the gateway with the `CRAFT_SANDBOX` scope
  and the `CRAFT_LLM_GENERATION` flow ([[llm-gateway#craft-token-stays-craft]]).
