# Multi-Tenancy

> How one deployment serves many isolated workspaces. A tenant is a Postgres
> schema on a physical shard, and a context variable that must hold the right
> tenant in every session, thread and task that a request or job creates.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** Self-hosted runs one tenant, `POSTGRES_DEFAULT_SCHEMA`, with
`MULTI_TENANT` off. Schema per tenant, sharding, provisioning, tenant gating
and impersonation run only on cloud (`MULTI_TENANT=true`, EE).

---

## Callers

**Interface.** The tenant of the current request or task, read with
`shared_configs/contextvars.py:get_current_tenant_id`; the tenant-aware DB
sessions in `db/engine/sql_engine.py`; the tenant-prefixed Redis client
(`redis/redis_pool.py:get_redis_client`); the context-copying thread helpers in
`utils/threadpool_concurrency.py`; `TenantAwareTask` for Celery; and the two
Alembic trees.

**Who calls it.**
- Every developer who opens a DB session, a Redis client or a cache, starts a
  thread, executor or Celery task, or adds a table or a migration. On
  self-hosted a lost tenant passes silently, because the default schema is the
  only tenant; on cloud it raises `Tenant ID is not set` or the work does
  nothing.
- [[auth-and-identity]] issues the credentials the tenant is read from.
- [[background-jobs]] fans tasks out per tenant.
- [[document-index]] adds the tenant clause to every index query.
- [[rate-and-usage-limits]] keeps tenant-scoped counters.
- [[billing]] keeps the gated-tenant set that the tenant middleware reads.

**Contracts a caller must keep:** each contract below about where the tenant
comes from, a session, a thread, a task, a cache key, a table or a migration.

---

## Scope

This component owns tenant resolution, tenant-scoped sessions and Redis
clients, shard routing, the catalog tables in `public`, tenant provisioning and
schema builds, the two Alembic trees, cross-tenant support actions, and the
rules for carrying tenant context across threads and tasks.

Neighbours own:
- [[auth-and-identity]]: the credentials the tenant is read from, and the SSO
  workspace token.
- [[access-control]]: the ACL clause next to the tenant clause in the index
  filter.
- [[background-jobs]]: Celery apps and the beat scheduler that fans tasks out
  per tenant.
- [[billing]]: whether a tenant is gated, and the control-plane data behind it.
- [[editions-and-gating]]: CE and EE dispatch.

---

## Architecture

**An HTTP request.**

```
ee/onyx/server/middleware/tenant_tracking.py:tenant_id_middleware   (EE app, MULTI_TENANT only)
  _get_tenant_id_from_request, in this order:
    OAuth-provider token -> tenant in the token
    API key, PAT or SCIM token -> tenant in the token prefix
    Redis session (cookie or mobile bearer) -> tenant in the session value
    anonymous-user cookie -> tenant in its signed JWT (overrides a session)
    nothing -> POSTGRES_DEFAULT_SCHEMA, which holds no tenant data
  CURRENT_TENANT_ID_CONTEXTVAR.set(tenant); reset in finally
  gated-tenant check (Redis set) outside the allowed prefixes
tier_gate_middleware   registered first in ee/onyx/main.py:get_application, so it
                       is innermost and runs after the tenant is set
handler -> db/engine/sql_engine.py:get_session
  on cloud, refuses POSTGRES_DEFAULT_SCHEMA with 403 "User must authenticate"
  get_current_tenant_id() -> shard_routing.get_engine_for_tenant
  -> connection with schema_translate_map={None: tenant_id}
```

Every source is signed or server-issued, so a caller cannot forge a tenant
ID. A valid anonymous-user cookie takes precedence over the session token, so
a browser that holds both goes to the cookie's tenant. A tenant read from a token only selects the schema.
The credential lookup then runs in that schema, so a forged prefix fails
authentication. Paths in `TENANT_RESOLUTION_SKIP_PATHS`, such as health checks
and the OAuth-provider protocol routes, get the default schema.
The tenant middleware is pure ASGI, so the tenant holds until a streamed body
and its background task end ([[streaming-protocol#pure-asgi-middleware]]).
[[billing]] owns the rules of the gated-tenant check in the same middleware
([[billing#failure-directions-differ]], [[billing#recovery-paths-reachable]]).

**Background work.** `background/celery/apps/app_base.py:TenantAwareTask`
reads the `tenant_id` kwarg, sets the context variable for the task body, and
sets it to `None` after. The `reset_tenant_id` postrun handler then sets it to
`POSTGRES_DEFAULT_SCHEMA`. The beat scheduler
(`background/celery/apps/beat.py:DynamicTenantScheduler`) makes one entry per
tenant for tenant tasks and one entry for cloud-wide tasks.

**Shards.** `db/engine/shard_routing.py:get_shard_for_tenant` checks the
`ONYX_DB_SHARD_OVERRIDES` map, then an in-process cache, then the
`public.tenant_shard` row. No row means the default shard. A Redis version
key tells every process to drop its cache when a tenant moves.

**Provisioning.** `ee/onyx/server/tenants/provisioning.py:get_or_provision_tenant`
takes a tenant from the `available_tenant` pool, or builds one. A periodic
task keeps the pool full
(`ee/onyx/background/celery/tasks/tenant_provisioning/tasks.py:check_available_tenants`).
`ee/onyx/server/tenants/schema_management.py:build_tenant_schema` clones a
stored SQL dump of the shard's template schema at the code's Alembic head
(`ee/onyx/db/tenant_snapshot.py:apply_snapshot`). It runs the migration chain
instead when no snapshot exists at that head, or when the schema already has
tables from a failed build.

**Two Alembic trees.** `backend/alembic/` migrates the tenant tables
(`db/models.py:Base`) once per tenant schema. `backend/alembic_tenants/`
migrates only the catalog tables (`PublicBase`) in `public`.

---

## Contracts and traps

1. `tenant-aware-session` **Every DB session comes from a tenant-aware
   helper.** Use `get_session`,
   `db/engine/sql_engine.py:get_session_with_current_tenant`,
   `get_session_with_tenant` or the async versions. A bare
   `Session(bind=engine)` skips the schema map and the shard.
   `db/engine/sql_engine.py:get_catalog_session` is the one helper pinned to `public`, for catalog
   tables only.
2. `tenant-from-auth-only` **The request's tenant comes from authenticated
   context, never from client input.** Some routes take a tenant id in the
   body, such as the control-plane routes behind `control_plane_dep` and the
   request to join a workspace (`ee/onyx/server/tenants/user_invitations_api.py`).
   They name a target and never set the request's own tenant from it.
   `db/engine/sql_engine.py:is_valid_schema_name` and
   `db/engine/tenant_utils.py:TENANT_ID_PATTERN` check every tenant id before
   it becomes a schema name, because a schema name cannot be a SQL parameter.
   `ee/onyx/server/tenants/schema_management.py:drop_schema` checks `validate_tenant_id` for this
   reason.
3. `threads-copy-context` **A new thread does not inherit the tenant.** A raw
   `Thread`, `ThreadPoolExecutor.submit` or `loop.run_in_executor` starts with
   the context variable's default: `None` on cloud, `POSTGRES_DEFAULT_SCHEMA`
   on self-hosted. So the bug shows only on cloud. Use the helpers in
   `utils/threadpool_concurrency.py`, such as
   `run_functions_tuples_in_parallel` and `start_thread_with_context`, which
   copy the context. Or set the variable at the top of the thread and reset it
   in `finally`. `asyncio.create_task` and `asyncio.to_thread` copy the
   context, so they need nothing more. A long-lived daemon thread that serves
   one tenant can set the variable once
   (`background/periodic_poller.py:_poller_loop`). Copy the context once for
   each thread: one `Context` object cannot be entered by two threads at once.
   `agents/runtime.py:Run._start_execution` passes a fresh copy of the
   context captured at start each time a run thread starts.
4. `celery-task-tenant-kwarg` **Every tenant-scoped Celery task needs a
   `tenant_id` kwarg.**
   `background/celery/apps/app_base.py:TenantAwareTask` falls back to `POSTGRES_DEFAULT_SCHEMA` when it is
   missing. On cloud that schema has no tenant data, so the task fails or does
   nothing, with no error that names the cause. Beat adds the kwarg to each
   per-tenant entry; a direct send must pass it. Cloud-wide beat entries
   (`backend/onyx/background/celery/tasks/beat_schedule.py:get_cloud_tasks_to_schedule`)
   carry no tenant on purpose.
5. `read-tenant-with-getter` **Read the tenant with `get_current_tenant_id()`,
   not the raw variable.** `shared_configs/contextvars.py:get_current_tenant_id`
   raises on cloud when the tenant is unset, so a lost context fails loudly.
   Do not treat `None` from `.get()` as a schema.
6. `tenant-in-cache-keys` **A tenant-scoped cache or Redis key needs the
   tenant; a cross-tenant key uses the shared client.**
   `redis/redis_pool.py:get_redis_client` returns a `TenantRedisClient` that
   prefixes every key (`redis/tenant_redis_client.py:_prefix_key`).
   `redis/redis_pool.py:get_shared_redis_client` and
   `cache/factory.py:get_shared_cache_backend` are cross-tenant;
   use them only for data or coordination that spans tenants, such as the
   locks in `cache/locks.py`. A module-level
   `lru_cache` or dict that holds tenant data must include the tenant in its
   key ([[rate-and-usage-limits#any-rate-limit-exists-fast-path]] is an
   example).
7. `one-alembic-tree` **A table belongs to one Alembic tree.** A per-tenant
   table inherits `Base` and goes in `alembic/`. A table that exists once
   inherits `PublicBase` and goes in `alembic_tenants/`. The wrong tree means
   the table is never created, or is copied into every tenant schema.
8. `pin-search-path` **Pin `search_path` per transaction in tenant
   migrations.** Cloud reaches Postgres through PgBouncer in transaction
   pooling. After a migration commits mid-run, the next transaction can use
   another server connection. `alembic/env.py` calls
   `db/engine/migration_search_path.py:pin_search_path_per_transaction`, which
   starts each transaction with `SET LOCAL search_path`. A one-time `SET` would
   send later DDL to the wrong schema while `alembic_version` records success.
9. `snapshot-skips-migrations` **A new tenant may not run your migration.**
   Provisioning clones the template snapshot, which holds the template's tables
   and rows, not the migration chain. A migration whose effect is outside its
   own schema, such as Redis keys, files or catalog rows, does not reach
   tenants built from a snapshot. Rows a migration inserts must be the same on
   every schema (`backend/AGENTS.md`).
   `ee/onyx/db/tenant_snapshot.py:check_snapshot_parity` compares a snapshot
   with a migrated schema.
10. `shard-routing-fails-closed` **Shard routing fails closed.**
    `get_shard_for_tenant` raises `ShardConfigurationError` when the catalog
    names an unknown shard, and `ShardLookupError` when it cannot read the
    catalog. A fallback to the default shard would send a moved tenant's writes
    to its old database.
11. `index-tenant-clause` **Never drop the tenant clause from the index
    filter.** `document_index/opensearch/search.py` adds a `tenant_id` term
    when `tenant_state.multitenant` is true. Single-tenant indices have no
    `tenant_id` field.
12. `cross-tenant-audit` **Cross-tenant actions use a separate context
    variable and an audit event.**
    `ee/onyx/server/tenants/admin_api.py:impersonate_user` needs
    `current_cloud_superuser`, sets `SESSION_TENANT_OVERRIDE_CONTEXTVAR` only
    while it issues the session, and calls `emit_audit_event` on success and
    failure. A new cross-tenant capability needs both.

---

## Decisions

- **Schema per tenant, not a tenant column.** Every query is scoped by the
  connection's schema map, so a query that forgets a filter cannot read
  another tenant. The cost is one migration run per tenant, which the snapshot
  clone and the parallel runner reduce.
- **Raise on a missing tenant.** On cloud, the context variable defaults to
  `None` and the getter raises, so a lost context is an error, not a read of
  the default schema.

---

## Known issues

- **A valid anonymous-user cookie overrides a session** in
  `_get_tenant_id_from_request`. A signed-in user who still holds an anonymous
  cookie for another workspace resolves to that workspace's schema. It is not
  confirmed whether this is intended.
- **The model server trusts a plain tenant header.**
  `utils/middleware.py:tenant_header_middleware` sets the tenant from
  `X-Onyx-Tenant-ID` with no check. Only `backend/model_server/main.py` uses
  it, and no model-server code reads the tenant. It is safe only while the
  model server stays internal, which the code cannot show. Do not add it to
  the API server, or tenant-scoped data access to the model server, without a
  security review.
- **Cloud-only code has thin local coverage.** Local dev and most CI run with
  `MULTI_TENANT` off. Gating, sharding, per-tenant beat entries and other
  `MULTI_TENANT` branches run only in `backend/tests/integration/multitenant_tests/`
  or on cloud. Use `git grep -n MULTI_TENANT` to find the branches a change
  touches.

---

## Dependencies

- [[auth-and-identity]]: tenant resolution reads the credentials it issues.
- [[background-jobs]]: `TenantAwareTask` and the beat fan-out.
- [[editions-and-gating]]: the tenant middleware and provisioning are EE.

---

## Recipes

- `new-table` **Add a table.** Decide `Base` or `PublicBase`, and use the matching Alembic
  tree ([[#one-alembic-tree]]). Copy `db/models.py:TenantShard` for a catalog
  table; list the catalog tables with `git grep -n "(PublicBase)"`.
- `new-thread` **Add a thread or executor.** Use a helper from
  `utils/threadpool_concurrency.py` ([[#threads-copy-context]]); list the
  call sites with `git grep -n run_functions_tuples_in_parallel`.
- `new-celery-task` **Add a Celery task.** Pass `tenant_id` in kwargs, and decide whether beat
  needs a per-tenant or a cloud-wide entry ([[background-jobs]]).
- `new-cross-tenant-action` **Add a cross-tenant admin action.** Copy `impersonate_user`
  ([[#cross-tenant-audit]]).
- `reproduce-multi-tenant-locally` **Reproduce a multi-tenant bug locally.** No switch turns a running local
  dev stack into multi-tenant mode. Copy the `multitenant-tests` job in
  `.github/workflows/pr-integration-tests.yml`: start only the infrastructure
  containers, then run the code with `MULTI_TENANT=true` and `AUTH_TYPE=cloud`.
  Use `backend/tests/integration/common_utils/managers/tenant.py` to create
  tenants.
- `investigate-tenant-not-set` **Investigate "Tenant ID is not set".** The error carries a stack trace. Find
  the first frame that runs in a new thread, executor or task, and check that
  it copies the context or receives `tenant_id`.

---

## Verification

- Integration: `backend/tests/integration/multitenant_tests/` and
  `backend/tests/integration/tests/migrations/`.
- Unit: `backend/tests/unit/onyx/db/engine/` and
  `backend/tests/unit/ee/onyx/server/middleware/`.
- External dependencies: `backend/tests/external_dependency_unit/redis/` and
  `backend/tests/external_dependency_unit/db/`.
- The isolation check: index a document in tenant A and confirm it never
  appears in tenant B's search, chat citations or `/api/search`.
