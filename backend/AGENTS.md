# BACKEND STANDARDS

Guidance for the Python backend (`backend/`): the FastAPI app, Celery workers, database, and
tests. Additive to the root `AGENTS.md`.

## Key Rules

- Use explicit validation in application code. Reserve `assert` for tests. `python -O` removes
  asserts, and a failed one gives the caller no useful error. Ruff rule `S101` checks this on
  pre-commit for `backend/onyx`, `backend/ee`, `backend/shared_configs` and `backend/model_server`.
  Write an explicit check that raises:
  - Type narrowing: `if x is None: raise RuntimeError("why x is always set")`.
  - Internal invariant: `if not ok: raise RuntimeError("Bug: ...")`, or `ValueError` for a bad
    argument.
  - Input validation: `raise OnyxError(OnyxErrorCode.INVALID_INPUT, "...")` on a request path
    (see "Error Handling"). Use `ValueError` for configuration and
    `ConnectorMissingCredentialError` for missing connector credentials.

  A deliberate exception goes on the line as `# noqa: S101 - <reason>`. Do not add a file to
  `[tool.ruff.lint.per-file-ignores]` in `pyproject.toml` for `S101`.
- Set a finite HTTP timeout. Ruff `S113` checks requests in application code.
  Use an existing timeout that fits the call. Celery thread pools cannot enforce task time limits.
- Use timezone-aware datetimes for timestamps. Ruff `DTZ` checks datetime construction and parsing.
  Use `datetime.now(UTC)` for the current time in UTC.
- Use Pydantic `BaseModel` for application models. Ruff `TID251` bans `dataclasses.dataclass`.
  For a deliberate exception, use an inline `# noqa` with the rule code and reason.
- Declare owned protocol implementations through explicit inheritance.

- Put ALL db operations under the `backend/onyx/db` / `backend/ee/onyx/db` directories. Don't run
  queries outside of those directories. Exception: `backend/onyx/cache/postgres_backend.py` is the
  PostgreSQL implementation of `CacheBackend`, so its queries belong there.
  `lint/check_db_ops_outside_db.py` enforces this on commit. It fails when a file outside
  those directories gains a query, a statement or a session write. The existing ones are frozen
  in `lint/db_ops_outside_db_baseline.txt`, and a count there can only go down. A deliberate
  exception needs `# db-ops-outside-db: allow <reason>` on its line, or on a comment line above
  the statement.
- When creating new FastAPI APIs, do NOT use the `response_model` field. Instead, just type the
  function. `lint/check_no_response_model.py` enforces this on commit. `response_model=None`
  is allowed. `# no-response-model: allow <reason>` on the decorator marks a deliberate exception.
  `lint/no_response_model_baseline.txt` counts the older uses in each file. After you remove
  one, regenerate it with `--write-baseline`.
- OpenSearch is the only document index backend for search and indexing. Onyx no longer uses
  Vespa. Some live Celery names still say "vespa" (the `vespa_metadata_sync` queue, the
  `check_for_vespa_sync_task` task, the `onyx.background.celery.tasks.vespa` module); they sync
  the document index and keep their names so running deployments are not disrupted.
- Do not use `getattr`: it hides attribute access from the type checker. Use
  plain attribute access when the name is statically known. A genuinely dynamic
  lookup needs an `# ods: ignore[getattr]` comment with a brief justification
  (checked by `ods check-getattr`).
- Use `CacheBackend` (`get_cache_backend()` / `get_shared_cache_backend()` in
  `backend/onyx/cache/factory.py`) for cache and short-lived state: one-time codes, counters,
  rate limits, locks. Do not call Redis directly or write Lua scripts. Onyx can run with
  PostgreSQL as its cache (`CACHE_BACKEND=postgres`, for example Onyx Lite), so direct Redis
  code breaks those deployments. If `CacheBackend` does not have an operation you need, add it
  to the interface with both the Redis and PostgreSQL implementations.
  `lint/check_no_direct_redis.py` enforces this on commit: it fails when a file gains a
  direct use of Redis above the count in `lint/no_direct_redis_baseline.txt`. Do not raise a
  count. `# no-direct-redis: allow <reason>` on the line, or on a comment line directly above
  it, marks a deliberate exception. After you move code to `CacheBackend`, run the script with
  `--write-baseline` to lower the counts.
- Do not use functions as constants. A value that depends only on startup configuration (env
  vars, `app_configs`) is a module-level constant computed once, not a zero-argument function
  that recomputes it on every call. If the configuration can be invalid, the loader returns
  `None` and logs instead of raising, so a bad value disables the feature rather than breaking
  imports. Tests patch the module constant.

## Import Boundaries

`lint/check_import_boundaries.py` (pre-commit hook `import-boundaries`) fails a commit that
adds an import across one of these boundaries. The contracts are in `lint/import_boundaries.toml`.

| Code | Must not import |
| --- | --- |
| `shared_configs` | Any other backend package |
| `model_server` | `ee`, `scripts`, `lint`, `tests`, and `onyx` except the modules that `Dockerfile.model_server` copies |
| `onyx`, `ee` | `model_server`, `scripts`, `lint` |
| `ee`, `model_server`, `shared_configs`, `scripts`, `lint`, `alembic` | `tests` |
| `onyx/server/features/build/sandbox/image` (sandbox daemon) | Any backend package |
| `onyx/skills/builtin` | Any backend package. `onyx` and `ee` must not import it |
| `onyx`, `ee` | The entry points `onyx.main`, `ee.onyx.main`, `onyx.mcp_server_main`, `onyx.webhook_server_main` |
| `onyx`, `ee` | `onyx.mcp_server` and `onyx.webhook_server`, except from their entry points |
| `onyx`, `ee`, `scripts`, `model_server` | `onyx.db._deprecated`. Only `alembic` migrations use it |
| `onyx` | `ee`. Use `fetch_versioned_implementation` or `fetch_ee_implementation_or_noop` |
| `onyx` | `tests` |
| The `onyx` modules that `Dockerfile.model_server` copies | Any `onyx` module that the image does not copy |
| `alembic` migrations | `ee` |
| `onyx/configs` | Any `onyx` package except `configs` and `utils` |
| `onyx`, `ee` outside `server` and `background` | `onyx.background`, except the Celery client app |
| A connector in `onyx/connectors` | Another connector. Shared code goes in `cross_connector_utils`, `google_utils` or `microsoft_utils` |
| A source in `ee/onyx/external_permissions` | Another source. Shared code goes in `microsoft_utils` |
| A task package in `onyx/background/celery/tasks` | Another task package. Shared code goes in `shared` |

- Every `import` statement counts: module level, inside a function, and under `TYPE_CHECKING`.
- The failure message gives the contract and where the code goes. Move the code. Do not move the
  import into a function to hide it.
- A deliberate import needs a `[[contract.exception]]` entry with a reason.
- Run all contracts with `python3 backend/lint/check_import_boundaries.py`.
- A tree without Enterprise code, such as the FOSS mirror, skips the paths under `ee/`.

## Background Workers (Celery)

Onyx uses Celery for asynchronous task processing. Worker apps live in
`backend/onyx/background/celery/apps/`; the periodic schedule is defined in
`backend/onyx/background/celery/tasks/beat_schedule.py`.

| Worker | Role |
| --- | --- |
| `primary` | Coordinates core background tasks: connector management/deletion, document-index sync, pruning checks, LLM model updates, user file sync |
| `docfetching` | Fetches documents from connectors, spawns docprocessing tasks; watchdog for stuck connectors |
| `docconversion` | Conversion stage: turns stub batches from a listing into document batches, then sends docprocessing tasks |
| `docprocessing` | Indexing pipeline: upsert docs to Postgres, chunk, embed via model server, write chunks to the document index, update metadata |
| `light` | Fast lightweight ops: metadata sync, permissions upsert, checkpoint / index-attempt cleanup |
| `heavy` | Resource-intensive ops: pruning, document permissions sync, external group sync, CSV generation |
| `monitoring` | System health monitoring & metrics collection |
| `user_file_processing` | User-uploaded file indexing & project synchronization |
| `scheduled_tasks` | Executes user-scheduled (Craft) task runs |
| `beat` | Scheduler for periodic tasks; uses `DynamicTenantScheduler` for multi-tenant support |

Key facts:

- All workers use thread pools (not processes) — this is why Celery time limits don't work (see below).
- Multi-tenant: `DynamicTenantScheduler` explicitly adds `tenant_id` to each Celery Beat task's
  kwargs; direct task sends must propagate it themselves (`TenantAwareTask` silently falls back to
  the default schema when it's absent).
- Tasks route to named queues and carry a separate High/Medium/Low priority (`OnyxCeleryQueues` /
  `OnyxCeleryPriority` in `backend/onyx/configs/constants.py`); Redis coordinates inter-process
  communication; task state and metadata live in PostgreSQL.

### Defining Tasks

- Always use `@shared_task` rather than `@celery_app`
- Put tasks under `background/celery/tasks/` or `ee/background/celery/tasks`
- Add a task only for work that runs again: a periodic check, a step of a pipeline, or a
  user-started job that is heavy, long, or must survive an API restart. A run-once backfill or
  migration is not a task. `lint/check_celery_task_allowlist.py` fails a task or beat entry that
  is not in `lint/celery_task_allowlist.txt`, where each line gives a one-line reason.
- Never enqueue a task without an expiration. Always supply `expires=` when
  sending tasks, either from the beat schedule or directly from another task. It
  should never be acceptable to submit code which enqueues tasks without an
  expiration, as doing so can lead to unbounded task queue growth.
  `lint/check_celery_task_expires.py` enforces this on commit for `send_task`, `apply_async`,
  `delay` and beat schedule entries. `# celery-expires: allow (<reason>)` on the line that opens
  the call marks a deliberate exception.

### Task Time Limits

Since all tasks are executed in thread pools, the time limit features of Celery are silently
disabled and won't work. Timeout logic must be implemented within the task itself.

### Testing Worker Changes

If you make any updates to a celery worker and you want to test these changes, you will need
to ask the user to restart the celery worker. There is no auto-restart on code-change mechanism.

## Database & Migrations

Run all `alembic` commands from `backend/` (where `alembic.ini` lives) through `uv run`.

CI runs the pytest-alembic built-ins for both migration chains against fresh Postgres databases.
To run them locally from `backend/`, use `uv run pytest -m alembic tests/integration/tests/migrations/`.

### Running Migrations

```bash
# Standard migrations
uv run alembic upgrade head

# Multi-tenant (Enterprise)
uv run alembic -n schema_private upgrade head
```

### Creating Migrations

```bash
# Create migration
uv run alembic revision -m "description"

# Multi-tenant migration
uv run alembic -n schema_private revision -m "description"
```

Write the migration manually and place it in the file that alembic creates when running the above command.

Rows a revision in `alembic/versions` inserts must be identical on every schema: fixed ids and
literal values, no `uuid4()`, `now()`, randomness or env reads. The template snapshot is cloned
into new tenants and compared with a fresh build on deploy, so a run-dependent value breaks the
comparison. Schema defaults and updates to existing rows are fine.
`scripts/check_migration_determinism.py` enforces this on commit for revisions newer than the
rule, and `# migration-determinism: allow` marks a deliberate exception.

A deploy runs every pending revision in one transaction (`alembic/env.py`).

- Do not add deferrable constraints. Their checks wait until commit, so an `ALTER TABLE` on the
  table in a later revision of the same deploy fails with "pending trigger events".
  `tests/integration/tests/migrations/test_no_deferrable_constraints.py` enforces this.
- Add a CHECK constraint only when a race or another writer can break the rule that application
  code keeps. Name that case in a comment.
- A new CHECK or FK on an existing table scans every row under a lock that blocks the table. Add it
  with `postgresql_not_valid=True`. Commit, then validate it, as `9d8f310ac672` does. A later
  revision is not enough, because it runs in the same transaction and keeps the lock.
- Test a backfill with seeded rows and a single upgrade to `head`, as
  `tests/integration/tests/migrations/test_plugin_backfill_single_run_upgrade.py` does.

The `migration-design` pre-commit hook checks both revision chains in
`lint/check_migration_design.py`. It checks one head per chain and exempts DDL
at and before `ff11c4042c42` in `alembic/versions` and `af8d808d89dd` in
`alembic_tenants/versions`.

- `not-valid` requires `postgresql_not_valid=True` on direct CHECK and FK
  operations on existing tables. Add the column first, then add its foreign key
  in a separate operation. Review the commit and validation sequence.
- `deferrable` prohibits literal `deferrable=True` and `initially="DEFERRED"`
  on constraint declarations in upgrades and their helpers.
- `not-null` requires a server default for a direct NOT NULL column addition
  on an existing table. You can add a nullable column, backfill it, then set NOT NULL.
- `blocking-index` flags direct `op.create_index` calls on existing tables.
  Commit first and use a separate AUTOCOMMIT connection, as in `9d8f310ac672`.
  The concurrent option alone leaves the call inside the migration transaction.
- `single-head` requires one head in each revision directory.

For the table exemptions, create the literal table in the same function before
the operation. The check reads Python call shapes. Review raw SQL and dynamic DDL.
For a deliberate DDL exception, add `# migration-design: allow <rule> - <reason>`
on a line of the call. Repair revision graph errors in the revision metadata.

## Testing Strategy

Run pytest through `uv run` from the repo root — no venv activation needed (`uv run` uses the
lockfile-pinned environment and creates/syncs `.venv` as needed).

There are 4 main types of tests within Onyx:

### Model choice for tests that make real LLM calls

When a test makes a real LLM call (e.g. External Dependency Unit / integration tests
that hit a live provider), use the cheap-and-fast tier for each provider:

- **OpenAI**: `gpt-6-luna`
- **Anthropic**: `claude-haiku-4-5`

### Unit Tests

These should not assume any Onyx/external services are available to be called.
Interactions with the outside world should be mocked using `unittest.mock`. Generally, only
write these for complex, isolated modules e.g. `citation_processing.py`.

To run them:

```bash
uv run pytest -xv backend/tests/unit
```

### External Dependency Unit Tests

These tests assume that all external dependencies of Onyx are available and callable (e.g. Postgres, Redis,
MinIO/S3, OpenSearch are running + OpenAI can be called + any request to the internet is fine + etc.).

However, the actual Onyx containers are not running and with these tests we call the function to test directly.
We can also mock components/calls at will.

The goal with these tests are to minimize mocking while giving some flexibility to mock things that are flakey,
need strictly controlled behavior, or need to have their internal behavior validated (e.g. verify a function is called
with certain args, something that would be impossible with proper integration tests).

A great example of this type of test is `backend/tests/external_dependency_unit/connectors/confluence/test_confluence_group_sync.py`.

To run them:

```bash
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit
```

### Integration Tests

Standard integration tests. Every test in `backend/tests/integration` runs against a real Onyx deployment. We cannot
mock anything in these tests. Prefer writing integration tests (or External Dependency Unit Tests if mocking/internal
verification is necessary) over any other type of test.

Tests are parallelized at a directory level.

When writing integration tests, make sure to check the root `conftest.py` for useful fixtures + the `backend/tests/integration/common_utils` directory for utilities. Prefer (if one exists), calling the appropriate Manager
class in the utils over directly calling the APIs with a library like `requests`. Prefer using fixtures rather than
calling the utilities directly (e.g. do NOT create admin users with
`admin_user = UserManager.create(name="admin_user")`, instead use the `admin_user` fixture).

A great example of this type of test is `backend/tests/integration/tests/streaming_endpoints/test_chat_stream.py`.

To run them:

```bash
uv run --env-file .vscode/.env pytest backend/tests/integration
```

### Playwright (E2E) Tests

These tests are an even more complete version of the Integration Tests mentioned above. Has all services of Onyx
running, _including_ the Web Server.

Use these tests for anything that requires significant frontend <-> backend coordination.

Tests are located at `web/tests/e2e`. Tests are written in TypeScript. Spec-writing rules
(Page Object Model, locator priority) live in `web/tests/e2e/README.md`.

To run them (the `playwright` script expands to `playwright test`; use it rather than
`bunx`/`npx`, which can silently fetch an unpinned Playwright version):

```bash
cd web && bun run playwright <TEST_NAME>
```

For shared fixtures, best practices, and detailed guidance, see `backend/tests/README.md`.

## Error Handling

**Always raise `OnyxError` from `onyx.error_handling.exceptions` instead of `HTTPException`.
Never hardcode status codes or use `starlette.status` / `fastapi.status` constants directly.**

A global FastAPI exception handler converts `OnyxError` into a JSON response with the standard
`{"error_code": "...", "detail": "..."}` shape. This eliminates boilerplate and keeps error
handling consistent across the entire backend.

```python
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

# ✅ Good
raise OnyxError(OnyxErrorCode.NOT_FOUND, "Session not found")

# ✅ Good — no extra message needed
raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)

# ✅ Good — upstream service with dynamic status code
raise OnyxError(OnyxErrorCode.BAD_GATEWAY, detail, status_code_override=upstream_status)

# ❌ Bad — using HTTPException directly
raise HTTPException(status_code=404, detail="Session not found")

# ❌ Bad — starlette constant
raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
```

Available error codes are defined in `backend/onyx/error_handling/error_codes.py`. If a new error
category is needed, add it there first — do not invent ad-hoc codes.

`lint/check_no_http_exception.py` enforces this on commit for `backend/onyx` and `backend/ee`.
Violations that predate the check are counted per file in `lint/no_http_exception_baseline.txt`,
and a file fails when its count rises. A deliberate exception carries
`# http-exception: allow <reason>` on or directly above the line.

**Upstream service errors:** When forwarding errors from an upstream service where the HTTP
status code is dynamic (comes from the upstream response), use `status_code_override`:

```python
raise OnyxError(
    OnyxErrorCode.BAD_GATEWAY, detail, status_code_override=e.response.status_code
)
```

## AI/LLM Integration

Text generation uses `LLM` with `GenerationRequest` and `GenerationContext`.
The LiteLLM adapter implements the client. Models remain configurable per feature.

### Tracing — every LLM invocation must be tagged

Every LLM, embedding, rerank, image-generation, voice (STT/TTS), and intent-classification call must open a generation span tagged with a value from the `LLMFlow` registry in `backend/onyx/tracing/flows.py`. Use one of:

- `GenerationContext(flow=LLMFlow.X)` for shared client calls. The client owns the generation span.
- `llm_generation_span(llm=llm, flow=LLMFlow.X, input_messages=...)` for raw provider operations in protocol gateways.
- `traced_llm_call(flow=LLMFlow.X, model=..., provider=..., input_messages=...)` for direct provider SDK / `litellm` / model_server HTTP calls that bypass the `LLM` abstraction.

Rules:

1. Add a new `LLMFlow` enum value before instrumenting a new operation. Don't pass raw strings.
2. Flow tags name the **operation** (e.g. `IMAGE_EDIT`, `RERANK`) — not the provider. Provider lives in `model_config["model_provider"]`.
3. Shared calls without a flow emit `LLMFlow.UNTAGGED_INVOKE` or `UNTAGGED_STREAM`. These sentinels indicate missing instrumentation. Fix the call site.

Pre-commit runs `check_import_boundaries.py` to restrict provider SDK imports to adapters and recorded exceptions.
The check covers import statements. Review HTTP calls and calls through shared clients for flow tags.
