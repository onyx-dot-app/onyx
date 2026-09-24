# Multi-Tenancy

> How one Onyx deployment serves many isolated customers. A tenant is a Postgres
> schema, a physical shard, and a `contextvars` value that must be correct for
> every session, thread, and task the request or job creates.

**Domain:** multi-tenancy
**Edition:** CE runs with exactly one tenant (the `public` schema) and most of this
component is inert. EE/cloud is where sharding, provisioning, gating, and
cross-tenant admin tooling apply.
**Owns:**
`backend/onyx/db/engine/sql_engine.py`, `async_sql_engine.py`, `tenant_utils.py`,
`shard_registry.py`, `shard_routing.py`, `shard_version.py`, `connection_warmup.py`,
`iam_auth.py`, `pg_ssl.py`, `time_utils.py`,
`backend/onyx/db/tenant_shard.py`, `tenant_invite_counter.py`,
`backend/shared_configs/contextvars.py` (the tenant contextvar itself),
`backend/alembic_tenants/` (catalog migrations), `backend/alembic/` (tenant-schema
migrations plus `run_multitenant_migrations.py`),
`backend/onyx/background/celery/apps/app_base.py` (`TenantAwareTask`),
`backend/ee/onyx/server/middleware/tenant_tracking.py`,
`backend/ee/onyx/server/tenants/` (`provisioning.py`, `schema_management.py`,
`admin_api.py`, `product_gating.py`, `tenant_management_api.py`, and neighbors),
`backend/ee/onyx/background/celery/tasks/tenant_provisioning/`, `cloud/`,
`backend/ee/onyx/db/user_tenant_mapping.py`,
`backend/onyx/auth/sso_tenant_token.py`, `backend/onyx/redis/tenant_redis_client.py`,
`redis_tenant_work_gating.py`

**Does not own:** the ACL clause itself ([[access-control]] owns
`_get_acl_visibility_filter`), how a chat turn's worker threads copy tenant context
(described and owned by [[core-chat-loop]]; this document generalizes the pattern),
CE/EE dispatch mechanics ([[editions-and-gating]]).

---

## 1. What the user experiences

A user never sees multi-tenancy directly. On self-hosted Onyx there is exactly one
tenant, the `public` schema, and nothing in this document is visible or relevant.

On Onyx Cloud, a user signs up or is invited into one workspace (a tenant). Every
document, chat, persona, and admin setting they see belongs to that workspace, and
they cannot see or affect any other workspace's data through normal use. An admin
never chooses a schema name or a database; that is entirely infrastructure. Cloud
support staff can impersonate a specific user for troubleshooting
(`ee/onyx/server/tenants/admin_api.py:impersonate_user`), which is the one place a
human intentionally crosses the tenant boundary, and it is audited
(`onyx/utils/audit.py:emit_audit_event`).

For an engineer, the operative rule is: **never let a database session, a cache
key, a background task, or a new thread cross into existence without an explicit
tenant.** Every mechanism in this document exists to make that automatic on the
paths that already exist, and to make it visible when a new path does not.

---

## 2. Surfaces

### Environment configuration

| Variable | File | Effect |
|---|---|---|
| `MULTI_TENANT` | `shared_configs/configs.py` | Master switch. `False` (default): one tenant, the `public` schema, most of this component is a pass-through. `True`: schema-per-tenant, sharding, gating, and cloud-only code paths activate. |
| `ONYX_DB_SHARDS` | `configs/app_configs.py` | JSON object of shard name to connection overrides. Unset means exactly one shard (the default). |
| `ONYX_DB_DEFAULT_SHARD` | same | Name of the always-present default shard; cannot be overridden via `ONYX_DB_SHARDS`. |
| `ONYX_DB_CATALOG_SHARD` | same | Which shard holds the `public` catalog tables (`tenant_shard`, `user_tenant_mapping`, and friends). Defaults to the default shard. |
| `ONYX_DB_NEW_TENANT_SHARD` | same | Shard newly created tenants are placed on. |
| `ONYX_DB_SHARD_POOL_SIZE` / `_OVERFLOW` | same | Pool sizing for non-default shard engines; falls back to the default engine's sizing if unset. |
| `ONYX_DB_SHARD_OVERRIDES` | same | JSON map of `tenant_id -> shard name`, a static operator escape hatch bypassing the `tenant_shard` catalog table. |
| `ONYX_DB_SHARD_MAP_TTL_SECONDS` / `_VERSION_POLL_SECONDS` | same | In-process shard-routing cache TTL and the Redis version-poll interval (`db/engine/shard_version.py`). |
| `USE_IAM_AUTH` | same | RDS IAM auth instead of a static password; token minting is bound to a shard's specific host/port/user (`db/engine/iam_auth.py`). |
| `TARGET_AVAILABLE_TENANTS` | `ee/onyx/background/celery/tasks/tenant_provisioning/tasks.py` | Size of the pre-provisioned tenant pool `check_available_tenants` maintains. |

### Endpoints and tasks

| Surface | Handler | Notes |
|---|---|---|
| `POST /tenants/impersonate` | `ee/onyx/server/tenants/admin_api.py:impersonate_user` | Cloud-superuser only. Issues a token for another tenant via `SESSION_TENANT_OVERRIDE_CONTEXTVAR`, audited. |
| Tenant creation / assignment | `ee/onyx/server/tenants/provisioning.py:get_or_provision_tenant` | Called from the signup/OAuth flow. Draws from the pre-provisioned pool or creates fresh. |
| `CLOUD_CHECK_AVAILABLE_TENANTS` (Celery) | `ee/onyx/background/celery/tasks/tenant_provisioning/tasks.py:check_available_tenants` | Beat task; tops up the pre-provisioned pool and migrates stale pool tenants. |
| SSO discovery / authorize | `backend/onyx/server/sso_discovery.py`, `onyx/auth/sso_tenant_token.py` | Cloud serves every workspace from one domain; discovery resolves the tenant and mints a short-lived signed `workspace_token` (`generate_sso_tenant_token`) that pins the authorize step to one tenant. |
| Alembic (tenant schemas) | `backend/alembic/run_multitenant_migrations.py` | Parallel batched migration runner across every tenant schema on every shard. |
| Alembic (catalog) | `backend/alembic_tenants/` | Migrates only `PublicBase`-derived tables in the `public` schema. |

---

## 3. Data model

```
Physical layout (Postgres):

  shard "default" (or any configured shard)
    schema public              <- catalog tables, PublicBase, always here
      tenant_shard
      user_tenant_mapping / user_tenant_mapping_oauth_account
      available_tenant
      tenant_invite_counter
      tenant_anonymous_user_path
      tenant_sso_domain
    schema tenant_<uuid>        <- one tenant's data, Base-derived tables
      users, chat_session, document, persona, ...
    schema tenant_<uuid>        <- another tenant, same table shapes
    ...

  shard "shard-2" (only if ONYX_DB_SHARDS configures more than one)
    schema tenant_<uuid>
    ...
```

- **`onyx/db/models.py:Base`**: every tenant-scoped table (`User`, `ChatSession`,
  `Document`, and effectively all of `onyx/db/models.py`). One copy of this schema
  exists per tenant, physically separate by Postgres schema.
- **`onyx/db/models.py:PublicBase`**: the catalog tables, always in `public`, never
  duplicated per tenant: `UserTenantMapping`, `UserTenantMappingOAuthAccount`,
  `AvailableTenant`, `TenantAnonymousUserPath`, `TenantSSODomain`,
  `TenantInviteCounter`, `TenantShard`.
- **`public.tenant_shard`** (`db/tenant_shard.py`): `(tenant_id, shard_name,
  updated_at)`. Written by `record_tenant_placement` before a tenant's schema is
  created; absence means "the default shard". Read by `shard_routing.py`.
- **`public.user_tenant_mapping`** (`ee/onyx/db/user_tenant_mapping.py`): email to
  tenant, the reverse lookup used by `get_tenant_id_for_email` /
  `resolve_tenant_id` during login and impersonation.
- **`public.available_tenant`**: the pre-provisioned tenant pool
  `check_available_tenants` (`ee/onyx/background/celery/tasks/tenant_provisioning/tasks.py`)
  keeps topped up, so signup does not pay the ~80s migration cost synchronously.
- **`public.tenant_invite_counter`** (`db/tenant_invite_counter.py`): per-tenant
  trial invite cap, incremented via `reserve_trial_invites` (a Postgres
  `INSERT ... ON CONFLICT DO UPDATE` that row-locks the tenant for the
  transaction) and compensated via `release_trial_invites` on downstream failure.
- **Schema identity is the tenant ID.** A tenant ID doubles as a Postgres schema
  name and is validated by `db/engine/sql_engine.py:is_valid_schema_name`
  (`^[a-zA-Z0-9_-]+$`) and, more strictly, `db/engine/tenant_utils.py:TENANT_ID_PATTERN`
  (a `tenant_` prefix followed by a UUID, an AWS instance ID, or the literal `dev`).
  Both checks exist because a schema name cannot be parameterized in SQL; unqualified
  string interpolation of an unvalidated tenant ID is a SQL-injection path into
  `CREATE SCHEMA`/`DROP SCHEMA` (`ee/onyx/server/tenants/schema_management.py:drop_schema`
  checks `validate_tenant_id` explicitly for this reason).

---

## 4. How it works

### 4.1 An HTTP request: from cookie to a tenant-scoped session

```
add_api_server_tenant_id_middleware              ee/onyx/server/middleware/tenant_tracking.py
  (registered only in EE's app; CE's onyx/main.py does not register any
   tenant-resolving middleware, because in CE MULTI_TENANT is always False)
  └─ _get_tenant_id_from_request
       ├─ extract_tenant_from_auth_header(request)          onyx/auth/utils.py  (API key / PAT)
       ├─ retrieve_auth_token_data_from_redis(request)        session cookie
       ├─ retrieve_auth_token_data_from_bearer(request)       mobile bearer token
       └─ decode_anonymous_user_jwt_token(cookie)              anonymous session
  └─ CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
  └─ (MULTI_TENANT only) is_tenant_gated(tenant_id) check      product_gating.py

... request handler runs, with the contextvar set for its whole async call stack ...

get_session() / get_session_with_current_tenant()             db/engine/sql_engine.py
  └─ get_current_tenant_id()                                   reads the contextvar
  └─ get_engine_for_tenant(tenant_id)                           shard_routing.py
       └─ get_shard_for_tenant(tenant_id)                       cache -> tenant_shard row -> default
  └─ engine.connect().execution_options(schema_translate_map={None: tenant_id})
  └─ Session(bind=connection)
```

Every source in `_get_tenant_id_from_request` is signed or server-issued (a PAT, a
Redis-backed session token, a JWT). None of them lets an unauthenticated caller name
an arbitrary tenant; an unauthenticated request resolves to `POSTGRES_DEFAULT_SCHEMA`,
which owns no tenant data.

**Where this breaks:** `onyx/utils/middleware.py:add_onyx_tenant_id_middleware`
also sets `CURRENT_TENANT_ID_CONTEXTVAR` from a raw `X-Onyx-Tenant-ID` request
header, with no signature and no validation. It is wired up only in
`backend/model_server/main.py`, not in the API server
(`grep -rn "add_onyx_tenant_id_middleware" backend/` finds exactly those two files).
The model server is an internal service, not directly internet-facing, which is the
implicit justification; this document cannot verify the network topology that makes
that safe, and a change that exposes the model server externally, or that reuses
this middleware on the API server, reopens tenant spoofing via a plain header.

### 4.2 A background task: establishing tenant context from scratch

Celery tasks and Redis-triggered background work have no request, so the contextvar
must be set explicitly by whatever dispatches the task:

```
TenantAwareTask.__call__                       background/celery/apps/app_base.py
  tenant_id = kwargs.get("tenant_id") or POSTGRES_DEFAULT_SCHEMA
  CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
  try:
      super().__call__(*args, **kwargs)
  finally:
      CURRENT_TENANT_ID_CONTEXTVAR.set(None)     # see §9: not a token-based reset
```

Every Onyx Celery task base class ultimately derives from `TenantAwareTask`; a task
that does not include `tenant_id` in its kwargs silently runs against the default
schema. The beat scheduler (`background/celery/apps/beat.py`) iterates
`get_all_tenant_ids()` (`db/engine/tenant_utils.py`) and schedules one entry per
tenant per per-tenant task, and one shared entry for cloud-wide tasks
(`MULTI_TENANT` branch in `beat.py:generate_schedule`).

Other places that set the contextvar directly, without going through
`TenantAwareTask`, all follow the same `.set(token)` / `try/finally: .reset(token)`
shape:

- `background/indexing/job_client.py` (indexing subprocess dispatch)
- `background/periodic_poller.py`
- `background/celery/tasks/docprocessing/tasks.py`, `monitoring/tasks.py`
- `tracing/processors/user_usage_processor.py`
- `sandbox_proxy/resolvers/mcp_server.py`
- `onyxbot/slack/listener.py`, `onyxbot/slack/utils.py`, `onyxbot/discord/cache.py`,
  `onyxbot/discord/handle_commands.py` (bot event handlers dispatch per-workspace)
- `key_value_store/factory.py` (uses `DEFAULT_REDIS_PREFIX`, a shared namespace, not
  a real tenant, for KV state that is intentionally cross-tenant)
- `server/features/build/interactive_turns/executor.py`
- `db/engine/sql_engine.py:get_catalog_session` (pins to `POSTGRES_DEFAULT_SCHEMA`
  for the duration of a catalog-table read)
- `scripts/debugging/onyx_db.py`, `onyx_redis.py`, `opensearch/*.py` (dev tooling)

**Where this breaks:** any new thread, thread pool, or `asyncio.to_thread`/executor
call started from inside a request or a task does not automatically inherit the
current contextvar's *live* value across a raw thread boundary unless the caller
copies the context. [[core-chat-loop]] documents the concrete case: `_run_models`
(`chat/process_message.py`) submits each per-model worker with a copied
`contextvars.Context` (`contextvars.copy_context().run`, `process_message.py:1615-1623`)
specifically because tenant ID and tracing context live in contextvars. Generalize
that pattern: **a bare `Thread(target=fn)`, a `ThreadPoolExecutor.submit(fn)`, or a
background `asyncio.create_task` that does not wrap its target in
`contextvars.copy_context().run(...)` loses the tenant context inside that thread**,
and any DB session or Redis client built inside it resolves to whatever the
contextvar's *default* is (`None` under `MULTI_TENANT`, `POSTGRES_DEFAULT_SCHEMA`
otherwise) rather than the request's actual tenant. Under `MULTI_TENANT=True` this
either raises (`get_current_tenant_id` raises `RuntimeError` on `None`, a fail-safe)
or, if some caller has looser handling, is a real fail-open through wrong data
scoping. Standard Python threads *do* inherit the contextvar's value **as it existed
at thread-creation time** in this specific set of call sites, because each one is
explicit; the risk is a new call site that isn't.

`asyncio.to_thread` (used by `db/engine/async_sql_engine.py:get_async_engine_for_tenant`
and `ee/onyx/server/middleware/tenant_tracking.py`'s gating check) does propagate the
calling context automatically, per Python's documented behavior; this is the one
concurrency primitive in this codebase where context propagation is not something a
developer has to remember to add.

---

## 5. Contracts and invariants

1. **Every DB session must be tenant-scoped.** It must come from
   `get_session`, `get_session_with_current_tenant`, `get_session_with_tenant`, or
   `get_async_session` (or their EE equivalents), never from a bare
   `Session(bind=some_engine)` built against an engine resolved outside these
   helpers. The one sanctioned exception is `get_catalog_session`
   (`sql_engine.py`), which is explicitly pinned to `public` for catalog tables.
2. **The tenant comes from the authenticated context, never from client input.**
   The only place a header (`X-Onyx-Tenant-ID`) directly sets the contextvar is
   `onyx/utils/middleware.py:add_onyx_tenant_id_middleware`, wired only into the
   model server (§4.1, §9). No API-server endpoint accepts a tenant ID as a request
   body or query parameter; `is_valid_schema_name`/`TENANT_ID_PATTERN` validate
   every tenant ID that does cross a boundary (a JWT claim, a Redis-cached session,
   an anonymous cookie) before it is used as a schema name.
3. **Every new thread, thread pool, or task must receive tenant context
   explicitly.** Either copy the context (`contextvars.copy_context().run`, as
   [[core-chat-loop]] does) or set the contextvar at the top of the new
   thread/task body and reset it in a `finally` (as every listed call site in §4.2
   does). A new concurrency primitive that does neither is a tenant-context bug,
   not a performance bug.
4. **A tenant-scoped table belongs in `alembic/`, never `alembic_tenants/`.**
   `alembic_tenants/env.py` targets only `PublicBase.metadata`; a table added to
   `onyx/db/models.py:Base` and migrated through `alembic_tenants/` would never
   actually be created, because that tree only ever touches the `public` schema
   catalog tables. Conversely, a genuinely tenant-independent table (something
   that must exist exactly once, not once per tenant) must inherit `PublicBase`
   and go in `alembic_tenants/`, or it will be silently duplicated into every
   tenant schema instead of shared.
5. **The index's tenant filter must never be dropped.** `_get_search_filters`
   (`document_index/opensearch/search.py`) adds a `{"term": {TENANT_ID_FIELD_NAME:
   ...}}` clause whenever `tenant_state.multitenant` is true, independently of and
   AND-ed alongside the ACL clause [[access-control]] adds in the same function.
   Removing or conditionally skipping this clause on any retrieval path is a
   cross-tenant document leak, not a ranking bug. **Single-tenant (`MULTI_TENANT`
   off) indices carry no `tenant_id` field at all** (`schema.py` only adds the
   field, and `search.py` only emits the clause, when `tenant_state.multitenant`
   is true). This is a genuine format difference between CE and cloud indices,
   not merely an unused field.
6. **Code that works single-tenant can still be broken multi-tenant, and vice
   versa.** `MULTI_TENANT=False` is the default local dev and CE path; several
   real behaviors (gating, sharding, the beat multiplier, tenant-scoped rate
   limits, the tenant contextvar's own default value) only exist when
   `MULTI_TENANT=True`. See §7 and §9. A change validated only in one mode has not
   validated the other.
7. **Shard routing fails closed.** `shard_routing.py:get_shard_for_tenant` raises
   `ShardConfigurationError` rather than falling back to the default shard when the
   catalog names a shard this process does not recognize. Silently defaulting
   could route an already-migrated tenant's writes back to the database it moved
   off. The one deliberate default-shard fallback is a missing `tenant_shard` table
   entirely, which means nothing has ever been mapped.
8. **A cross-tenant admin action (impersonation) must be both narrowly scoped and
   audited.** `ee/onyx/server/tenants/admin_api.py:impersonate_user` is gated on
   `current_cloud_superuser`, sets `SESSION_TENANT_OVERRIDE_CONTEXTVAR` (not the
   plain tenant contextvar, so it cannot be confused with an ambient request
   tenant) only for the duration of issuing the token, and emits
   `AuditAction.IMPERSONATE` via `emit_audit_event` on both success and failure.
   A new cross-tenant capability that skips either the scoping or the audit call
   is a security regression, not a style issue.

---

## 6. Relationships

**Depends on**
- [[auth-and-identity]]: supplies the authenticated user/session that tenant
  resolution in §4.1 keys on; the tenant contextvar is meaningless without a prior
  authentication decision.
- [[editions-and-gating]]: `MULTI_TENANT` itself, and most of the CE/EE dispatch
  this component's cloud-only behaviors ride on (`fetch_versioned_implementation`,
  `fetch_ee_implementation_or_noop`).
- [[background-jobs]]: `TenantAwareTask` and the beat scheduler's per-tenant
  schedule generation are the Celery-side half of tenant propagation this
  document describes.

**Depended on by**
- [[core-chat-loop]]: every DB session a chat turn opens is tenant-scoped through
  this component; the turn's worker-thread `contextvars.Context` copy (§4.2) is the
  most-referenced concrete example of the propagation rule this document
  generalizes.
- [[document-index]] and [[access-control]]: the tenant term filter in
  `_get_search_filters` is this component's contribution to that shared
  chokepoint; [[access-control]] documents that it composes with, and never
  substitutes for, the ACL clause. This document is the other half of that
  composition.
- [[chat-persistence]]: every table it owns is a `Base`-derived, per-tenant-schema
  table, migrated through `alembic/`, not `alembic_tenants/`.
- [[observability]]: tracing context propagation follows the same contextvar
  discipline (`tracing/processors/user_usage_processor.py` sets the tenant
  contextvar around usage recording); the tracing admin API is one of the
  `MULTI_TENANT`-conditional behaviors in §7.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a new table | Does it belong once per tenant (`Base`, `alembic/`) or once globally (`PublicBase`, `alembic_tenants/`)? Getting this backwards means the table is either duplicated into every schema or never created at all (§5.4). |
| adds a new thread or thread pool anywhere reachable from a request or task | Does it copy `contextvars.Context`, or set/reset the tenant contextvar explicitly? An uncopied thread silently resolves to the default tenant or raises, depending on `MULTI_TENANT` (§4.2, §9). |
| adds a new Celery task | Does it take `tenant_id` and route through `TenantAwareTask` (or an equivalent explicit `.set()`/`.reset()`)? Does the beat schedule need a per-tenant entry (`beat.py:generate_schedule`) or a single cloud-wide one? |
| adds a new global cache (in-process `lru_cache`/`functools.cache`, a module-level dict) that stores anything derived from tenant data | It needs the tenant in its key, or it must genuinely be tenant-independent (see §9 for what was checked and found safe). |
| changes session creation (`get_session`, `get_async_session`, or their EE equivalents) | Every one of the call sites in §5.1; confirm `schema_translate_map` still gets built from `get_current_tenant_id()`, never a value the caller could substitute. |
| adds a new retrieval entry point that queries the document index | [[access-control]]'s and this document's §5.5: it must go through `_get_search_filters`, which appends both the ACL clause and, under `MULTI_TENANT`, the tenant term clause. |
| changes shard routing, the catalog table, or `ONYX_DB_SHARDS`/`ONYX_DB_SHARD_OVERRIDES` | `shard_version.py`'s invalidation contract (§5.7); a routing change during an in-flight tenant migration is the failure mode this whole subsystem exists to prevent. |
| adds a new cross-tenant admin capability | §5.8: scoping via a narrow contextvar (not the ambient tenant one) plus an audit event, mirroring `impersonate_user`. |
| adds a new `MULTI_TENANT`-conditional branch | Confirm the CE/self-hosted path is still exercised by CE tests, not only assumed correct by symmetry (§9). |

---

## 8. How to verify a change

### Tests

```bash
# Integration: real tenant creation, shard migration, mobile-token tenant resolution
cd backend && uv run pytest tests/integration/multitenant_tests
cd backend && uv run pytest tests/integration/tests/migrations/test_alembic_tenants.py
cd backend && uv run pytest tests/integration/tests/migrations/test_run_multitenant_migrations.py

# Unit: contextvar/session/shard-routing correctness in isolation
cd backend && uv run pytest tests/unit/onyx/db/engine/test_tenant_utils.py
cd backend && uv run pytest tests/unit/onyx/document_index/test_tenant_scoping.py
cd backend && uv run pytest tests/unit/onyx/auth/test_session_tenant_resolution.py
cd backend && uv run pytest tests/unit/onyx/auth/test_password_login_tenant_conflict.py
cd backend && uv run pytest tests/unit/onyx/auth/test_rekey_tenant_mapping_after_login.py
cd backend && uv run pytest tests/unit/ee/onyx/server/middleware/test_tenant_tracking.py
cd backend && uv run pytest tests/unit/ee/onyx/server/tenants/test_impersonation_tenant_binding.py
cd backend && uv run pytest tests/unit/ee/onyx/server/tenants/test_tenant_resolution_by_oauth_account.py
cd backend && uv run pytest tests/unit/onyx/background/celery/tasks/tenant_provisioning

# External dependency: real Redis, real rollback path
cd backend && uv run pytest tests/external_dependency_unit/tenant_work_gating
cd backend && uv run pytest tests/external_dependency_unit/db/test_tenant_provisioning_rollback.py
cd backend && uv run pytest tests/external_dependency_unit/redis/test_tenant_redis.py
```

`tests/integration/common_utils/managers/tenant.py` is the reusable test helper for
creating and tearing down a real tenant in an integration test.

See `backend/AGENTS.md` for authoritative commands and required secrets/env.

### Manual reproduction

This repository's local dev stack normally runs with `MULTI_TENANT` unset (CE mode,
one tenant, `public` schema), so exercising the multi-tenant paths requires setting
`MULTI_TENANT=true` and re-running `alembic upgrade head` against a fresh tenant
schema, or driving the integration test fixtures above. There is no documented
one-command way to flip a running local dev stack into multi-tenant mode; treat that
gap as a real testing blind spot (§9).

To inspect tenant state directly in Postgres (per the root `AGENTS.md` `psql`
recipe):

```bash
PGPASSWORD="${POSTGRES_PASSWORD:-password}" psql -h "${POSTGRES_HOST:-localhost}" -U postgres \
  -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'tenant_%';"
PGPASSWORD="${POSTGRES_PASSWORD:-password}" psql -h "${POSTGRES_HOST:-localhost}" -U postgres \
  -c "SELECT * FROM public.tenant_shard;"
```

### What "working" looks like

- A document indexed for tenant A never appears in tenant B's search results, chat
  citations, or `/api/search` output, verified the same way [[access-control]]'s
  two-user test verifies ACL isolation, but across two tenants instead of two users.
- A Celery task dispatched with `tenant_id=A` reads and writes only schema
  `tenant_A`'s tables; `SELECT current_schema()` inside the task's session (or the
  `psql` query above) confirms this if in doubt.
- Migrating one tenant does not affect another tenant's `alembic_version`; catalog
  tables are unaffected by any `alembic/` (tenant-tree) migration.
- Shard routing failures raise loudly (`ShardConfigurationError`,
  `ShardLookupError`) rather than silently defaulting a migrated tenant back to its
  old database.

---

## 9. Footguns

- **The tenant contextvar is `CURRENT_TENANT_ID_CONTEXTVAR`
  (`shared_configs/contextvars.py`).** Its default is `None` when `MULTI_TENANT` is
  true and `POSTGRES_DEFAULT_SCHEMA` otherwise. Reading it through
  `get_current_tenant_id()` raises `RuntimeError` on a `None` default rather than
  silently returning `None`, specifically so a code path that forgot to establish
  tenant context fails loudly instead of resolving to "no tenant." Do not read the
  raw contextvar with `.get()` and treat `None` as a valid schema name.
- **`TenantAwareTask.__call__` resets with `.set(None)`, not a saved token.** Every
  other tenant-context call site in this codebase (§4.2's list) captures the token
  from `.set(tenant_id)` and calls `.reset(token)` in a `finally`, which restores
  whatever value was there before (correct under nested contexts). `app_base.py`'s
  `TenantAwareTask` instead force-sets the contextvar to `None` unconditionally
  after the task body runs. On a worker process this is fine because each task
  invocation starts a fresh context; it would not be fine if `TenantAwareTask`
  instances were ever nested or reused inside a shared context, which as of this
  writing they are not. Flag any refactor that changes how Celery invokes
  `TenantAwareTask` as needing to re-verify this.
- **A raw thread or executor started without `contextvars.copy_context()` loses
  tenant context.** [[core-chat-loop]]'s `_run_models` gets this right by copying
  the context per worker specifically because an earlier version of this exact bug
  class existed. Any new `Thread(...)`, `ThreadPoolExecutor.submit(...)`, or manual
  `asyncio.create_task` that captures no context and then opens a DB session or
  builds a Redis client inside itself is reading or writing against the wrong
  tenant, or raising, not against "no tenant" safely.
- **`onyx/utils/middleware.py:add_onyx_tenant_id_middleware` trusts a bare
  `X-Onyx-Tenant-ID` header with no signature check.** It is wired into
  `backend/model_server/main.py` only, never the API server. The exposure is
  currently bounded by a second fact: the model server never reads the value back.
  `grep -rn "CURRENT_TENANT_ID_CONTEXTVAR\|get_current_tenant_id\|get_session"
  backend/model_server/` returns nothing, so the middleware sets a contextvar that
  no code in that service consumes and it opens no tenant-scoped DB session. The
  header therefore cannot currently steer data access. Two things would change
  that: reusing this middleware on a service that does read the contextvar, or
  adding tenant-aware logic to the model server. Either is a security review. The
  network-isolation assumption (that the model server is unreachable from outside
  the cluster) is not verifiable from code, so do not rely on it alone.
- **Two Alembic trees, easy to confuse.** `backend/alembic_tenants/` migrates
  `PublicBase` (catalog) tables in `public` only; `backend/alembic/` migrates
  `Base` (tenant) tables, once per tenant schema, and is the one
  `run_multitenant_migrations.py` fans out across every tenant and shard. Adding a
  table to the wrong `Base` subclass, or writing its migration in the wrong tree,
  produces a table that either never gets created or gets silently duplicated into
  every tenant schema.
- **`MULTI_TENANT`-only code paths are easy to leave untested.** Local dev and most
  of CI run with `MULTI_TENANT` unset. Gating, tenant-scoped rate limiting, the
  beat-schedule multiplier (`pruning/tasks.py:_get_pruning_block_expiration`), the
  sharding layer, and the tracing-admin-API rejection (§ table below) are all
  invisible in that default configuration. A change that only ran self-hosted
  tests has not exercised any of them.
- **Caches checked for missing tenant keys, none found.** Redis
  access is uniformly tenant-prefixed through `TenantRedisClient`
  (`onyx/redis/tenant_redis_client.py:_prefix_key`), which the module's own
  docstring calls out as security-relevant specifically to prevent this class of
  bug. The billing cache (`ee/onyx/server/billing/billing_cache.py`) keys
  explicitly by `tenant_id`. The handful of in-process `@lru_cache`/
  `@functools.cache` decorators found (`llm/model_capabilities.py:get_model_map`,
  `llm/multi_llm.py`'s two log-dedup caches, `indexing/document_push.py:get_document_push_config`,
  `db/engine/iam_auth.py:create_ssl_context_if_iam`) all cache process-global,
  non-tenant-derived state (litellm's static model map, log-once flags, env-derived
  config, TLS context construction), not tenant data. This is a snapshot, not a
  standing guarantee: any new module-level cache must be checked against this same
  question before it is added.

---

## Unverifiable / not fully confirmed

- Whether the model server (`backend/model_server/`) is genuinely unreachable from
  outside the cluster in every deployment topology, which is the implicit
  justification for `add_onyx_tenant_id_middleware` trusting a raw header. Not
  verified from the code in this repository.
- The full list of `MULTI_TENANT`-conditional behaviors below is a representative
  sample (`grep -rn "MULTI_TENANT" backend/onyx backend/ee | grep -v test` returns
  roughly 300+ matches across ~100 files), not an exhaustive enumeration. Treat any
  specific claim of "this is the only place X differs" as unverified unless this
  document says so explicitly.

### `MULTI_TENANT`-conditional behavior (representative)

| Area | File:symbol | Behavior under `MULTI_TENANT=True` |
|---|---|---|
| Tracing admin API | `onyx/server/manage/tracing/api.py:_reject_if_multi_tenant` | Rejects tracing-provider configuration outright (`OnyxErrorCode.SINGLE_TENANT_ONLY`). |
| Forced document sets | `onyx/context/search/forced_document_set.py:get_forced_document_set_names` | Feature disabled entirely; `FORCED_DOCUMENT_SET_NAMES` is ignored. |
| Beat scheduling | `background/celery/apps/beat.py:generate_schedule` | Cloud-wide tasks scheduled once for all tenants rather than once per tenant. |
| Pruning/fence block expiration | `background/celery/tasks/pruning/tasks.py:_get_pruning_block_expiration`, `_get_fence_validation_block_expiration` | Base expiration multiplied by `OnyxRuntime.get_beat_multiplier()`; unmultiplied otherwise. |
| Feature flags | `onyx/feature_flags/factory.py:get_default_feature_flag_provider` | Uses the PostHog-backed provider (also enabled under `DEV_MODE`); otherwise a no-op provider that always returns `False`. |
| Signup rate limiting | `onyx/auth/signup_rate_limit.py:enforce_signup_rate_limit` | Enforced only when both `MULTI_TENANT` and `SIGNUP_RATE_LIMIT_ENABLED`; a no-op otherwise. |
| Password-login lockdown fields | `onyx/server/security/api.py` | `_PASSWORD_LOCKDOWN_FIELDS` and `OPERATOR_LOCKED_FIELDS` are rejected outright when present in the payload. |
| SSO domain enforcement | `onyx/server/manage/sso/api.py` | Email-domain routing/verification (`allowed_email_domains`, TXT-record domain status) only applies; single-tenant skips both checks. |
| Web-search provider base URL | `onyx/server/manage/web_search/api.py` | An update that changes `config.base_url` for an existing provider is rejected. |
| Tenant work-gating (Redis) | `onyx/redis/redis_tenant_work_gating.py` | All public functions (mark-active, size gauge, prune) are no-ops when `MULTI_TENANT` is false. |
| Usage limits default | `shared_configs/configs.py:USAGE_LIMITS_ENABLED` | Defaults to `MULTI_TENANT`'s value (on for cloud, off self-hosted) unless explicitly overridden. |
| Document index tenant filter | `document_index/opensearch/search.py`, `schema.py` | Tenant `term` clause and the `tenant_id` field itself exist only when `tenant_state.multitenant` is true (§5.5). |
| Open-URL tool tenant scoping | `tools/tool_implementations/open_url/open_url_tool.py` | Passes a real `tenant_id` into the crawl/index request only under `MULTI_TENANT`; `None` otherwise. |
| `DISABLE_VECTOR_DB` guard | `onyx/main.py` | Raises at startup if combined with `MULTI_TENANT` (incompatible configuration). |
