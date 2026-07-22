# PROJECT KNOWLEDGE BASE

This file provides guidance to AI agents when working with code in this repository.

## KEY NOTES

- Python deps live in a `uv`-managed virtualenv at `.venv` (repo root). If it doesn't exist yet, create it
  with `uv sync --frozen`, then `source .venv/bin/activate`.
- Test secrets live in gitignored env files: an OpenAI key in `.env` at the repo root, and `.vscode/.env`
  (used by the test commands below). If `.vscode/.env` doesn't exist, create it by copying
  `.vscode/env_template.txt` and filling in the values. If a key you need is missing, ask the user rather
  than skipping tests.
- If using `playwright` to explore the frontend, log in with username `admin_user@example.com` and password
  `TestPassword123!` (the admin user created by the playwright global setup — see
  `web/tests/e2e/constants.ts`). If it doesn't exist yet, register it via the signup page; the first user
  registered automatically becomes admin. The app can be accessed at `http://localhost:3000`.
- You should assume that all Onyx services are running. To verify, you can check the `backend/log` directory to
  make sure we see logs coming out from the relevant service.
- To connect to the Postgres database, use:
  `PGPASSWORD="${POSTGRES_PASSWORD:-password}" psql -h "${POSTGRES_HOST:-localhost}" -U postgres -c "<SQL>"`.
  This works on a host checkout and inside the devcontainer. If no `psql` client is available, fall back to
  `docker exec onyx-relational_db-1 psql -U postgres -c "<SQL>"` (no `-it` — agent shells have no TTY).
- When making calls to the backend, always go through the frontend. E.g. make a call to `http://localhost:3000/api/persona` not `http://localhost:8080/api/persona`
- Put ALL db operations under the `backend/onyx/db` / `backend/ee/onyx/db` directories. Don't run queries
  outside of those directories.

## Project Overview

**Onyx** (formerly Danswer) is an open-source Gen-AI and Enterprise Search platform that connects to company documents, apps, and people. It features a modular architecture with both Community Edition (MIT licensed) and Enterprise Edition offerings.

### Background Workers (Celery)

Onyx uses Celery for asynchronous task processing. Worker apps live in
`backend/onyx/background/celery/apps/`; the periodic schedule is defined in
`backend/onyx/background/celery/tasks/beat_schedule.py`.

| Worker | Role |
| --- | --- |
| `primary` | Coordinates core background tasks: connector management/deletion, document-index sync, pruning checks, LLM model updates, user file sync |
| `docfetching` | Fetches documents from connectors, spawns docprocessing tasks; watchdog for stuck connectors |
| `docprocessing` | Indexing pipeline: upsert docs to Postgres, chunk, embed via model server, write chunks to the document index, update metadata |
| `light` | Fast lightweight ops: metadata sync, permissions upsert, checkpoint / index-attempt cleanup |
| `heavy` | Resource-intensive ops: pruning, document permissions sync, external group sync, CSV generation |
| `monitoring` | System health monitoring & metrics collection |
| `user_file_processing` | User-uploaded file indexing & project synchronization |
| `scheduled_tasks` | Executes user-scheduled (Craft) task runs |
| `beat` | Scheduler for periodic tasks; uses `DynamicTenantScheduler` for multi-tenant support |

Key facts:

- All workers use thread pools (not processes) — this is why Celery time limits don't work (see below).
- Multi-tenant: a middleware layer automatically resolves the tenant ID when sending tasks via Celery Beat.
- Tasks use High/Medium/Low priority queues; Redis coordinates inter-process communication; task state
  and metadata live in PostgreSQL.

#### Important Notes

**Defining Tasks**:

- Always use `@shared_task` rather than `@celery_app`
- Put tasks under `background/celery/tasks/` or `ee/background/celery/tasks`
- Never enqueue a task without an expiration. Always supply `expires=` when
  sending tasks, either from the beat schedule or directly from another task. It
  should never be acceptable to submit code which enqueues tasks without an
  expiration, as doing so can lead to unbounded task queue growth.

**Defining APIs**:
When creating new FastAPI APIs, do NOT use the `response_model` field. Instead, just type the
function.

**Testing Updates**:
If you make any updates to a celery worker and you want to test these changes, you will need
to ask the user to restart the celery worker. There is no auto-restart on code-change mechanism.

**Task Time Limits**:
Since all tasks are executed in thread pools, the time limit features of Celery are silently
disabled and won't work. Timeout logic must be implemented within the task itself.

### Code Quality

```bash
# Install and run pre-commit hooks
pre-commit install
pre-commit run --all-files

# Faster: run only on the files you touched
pre-commit run --files <path> [<path> ...]
```

NOTE: Always make sure everything is strictly typed (both in Python and Typescript).

NOTE: Keep comments brief and focused on information that stays relevant long-term. Don't write
comments that only describe the instantaneous change (e.g. what was just added/removed/refactored).

## Architecture Overview

### Technology Stack

- **Backend**: Python 3.13, FastAPI, SQLAlchemy, Alembic, Celery
- **Frontend**: Next.js 16, React 19, TypeScript, Tailwind CSS
- **Database**: PostgreSQL with Redis caching
- **Search**: OpenSearch-backed keyword and vector document index
- **Auth**: OAuth2, SAML, multi-provider support
- **AI/ML**: LangChain, LiteLLM, multiple embedding models

OpenSearch is the current document index backend for search and indexing. Some
legacy modules, Celery task names, and migration helpers still mention Vespa; treat
those as compatibility or migration artifacts unless the active `DocumentIndex`
factory/config path explicitly uses them.

### Directory Structure

A coarse map of the most load-bearing packages. `backend/onyx/` contains many more
(`deep_research`, `kg`, `indexing`, `mcp_server`, ...) — explore with `ls` rather than
relying on this list.

```
backend/
├── onyx/                        # Core application code (Community Edition)
│   ├── auth/                    # Authentication & authorization
│   ├── background/              # Celery apps & tasks
│   ├── chat/                    # Chat functionality & LLM interactions
│   ├── connectors/              # Data source connectors
│   ├── db/                      # Database models & operations
│   ├── document_index/          # OpenSearch-backed DocumentIndex integration
│   ├── llm/                     # LLM provider integrations
│   └── server/                  # API endpoints & routers
├── ee/                          # Enterprise Edition features (mirrors onyx/ layout)
├── alembic/                     # Database migrations
└── tests/                       # Test suites

web/                             # Next.js frontend (see web/AGENTS.md)
mobile/                          # React Native + Expo app (see mobile/AGENTS.md)
desktop/                         # Tauri desktop shell
```

## Frontend Standards

Frontend standards for the `web/` and `desktop/` projects live in `web/AGENTS.md`.

Standards for the **mobile** app (React Native + Expo) live in `mobile/AGENTS.md`. Mobile differs
from web on several points (no DOM, NativeWind instead of web Tailwind — e.g. spacing classes are
pixel-valued, not web's rem step scale — expo-router, RN primitives), so do **not** assume the web
rules apply when working in `mobile/`.

## Database & Migrations

Run all `alembic` commands from `backend/` (where `alembic.ini` lives) with the virtualenv active.

### Running Migrations

```bash
# Standard migrations
alembic upgrade head

# Multi-tenant (Enterprise)
alembic -n schema_private upgrade head
```

### Creating Migrations

```bash
# Create migration
alembic revision -m "description"

# Multi-tenant migration
alembic -n schema_private revision -m "description"
```

Write the migration manually and place it in the file that alembic creates when running the above command.

## Testing Strategy

First, activate the virtualenv: `source .venv/bin/activate`. If `.venv` doesn't exist yet, create it first with `uv sync --frozen`.

There are 4 main types of tests within Onyx:

### Model choice for tests that make real LLM calls

When a test makes a real LLM call (e.g. External Dependency Unit / integration tests
that hit a live provider), use the cheap-and-fast tier for each provider:

- **OpenAI**: `gpt-5-mini` (never `gpt-4o` / `gpt-4o-mini`)
- **Anthropic**: `claude-haiku-4-5`

### Unit Tests

These should not assume any Onyx/external services are available to be called.
Interactions with the outside world should be mocked using `unittest.mock`. Generally, only
write these for complex, isolated modules e.g. `citation_processing.py`.

To run them:

```bash
pytest -xv backend/tests/unit
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
python -m dotenv -f .vscode/.env run -- pytest backend/tests/external_dependency_unit
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
python -m dotenv -f .vscode/.env run -- pytest backend/tests/integration
```

### Playwright (E2E) Tests

These tests are an even more complete version of the Integration Tests mentioned above. Has all services of Onyx
running, _including_ the Web Server.

Use these tests for anything that requires significant frontend <-> backend coordination.

Tests are located at `web/tests/e2e`. Tests are written in TypeScript.

To run them:

```bash
bunx playwright test <TEST_NAME>
```

For shared fixtures, best practices, and detailed guidance, see `backend/tests/README.md`.

## Logs

When (1) writing integration tests or (2) doing live tests (e.g. curl / playwright) you can get access
to logs via the `backend/log/<service_name>_debug.log` file. All Onyx services (api_server, web_server, celery_X)
will be tailing their logs to this file.

## Security Considerations

- Never commit API keys or secrets to the repository
- Use the encrypted credential storage for connector credentials
- Follow existing RBAC patterns for new features

## AI/LLM Integration

LLM calls go through LiteLLM; models are configurable per feature (chat, search, embeddings).

### Tracing — every LLM invocation must be tagged

Every LLM, embedding, rerank, image-generation, voice (STT/TTS), and intent-classification call must open a generation span tagged with a value from the `LLMFlow` registry in `backend/onyx/tracing/flows.py`. Use one of:

- `llm_generation_span(llm=..., flow=LLMFlow.X, input_messages=...)` for calls going through an `LLM` subclass.
- `traced_llm_call(flow=LLMFlow.X, model=..., provider=..., input_messages=...)` for direct provider SDK / `litellm` / model_server HTTP calls that bypass the `LLM` abstraction.

Rules:

1. Add a new `LLMFlow` enum value before instrumenting a new operation. Don't pass raw strings.
2. Flow tags name the **operation** (e.g. `IMAGE_EDIT`, `RERANK`) — not the provider. Provider lives in `model_config["model_provider"]`.
3. The auto-wrap fallback in `onyx/llm/tracing_wrap.py` emits `LLMFlow.UNTAGGED_INVOKE` / `UNTAGGED_STREAM` for calls that reach `LLM.invoke` / `LLM.stream` without an explicit span. These sentinels are visible in dashboards and indicate missing instrumentation — fix the call site, don't rely on the fallback.

## Creating a Plan

When creating a plan in the `plans` directory (gitignored — create it if it doesn't exist), make sure to
include at least these elements:

**Issues to Address**
What the change is meant to do.

**Important Notes**
Things you come across in your research that are important to the implementation.

**Implementation strategy**
How you are going to make the changes happen. High level approach.

**Tests**
What unit (use rarely), external dependency unit, integration, and playwright tests you plan to write to
verify the correct behavior. Don't overtest. Usually, a given change only needs one type of test.

Do NOT include these: _Timeline_, _Rollback plan_

This is a minimal list - feel free to include more. Do NOT write code as part of your plan.
Keep it high level. You can reference certain files or functions though.

Before writing your plan, make sure to do research. Explore the relevant sections in the codebase.

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

**Upstream service errors:** When forwarding errors from an upstream service where the HTTP
status code is dynamic (comes from the upstream response), use `status_code_override`:

```python
raise OnyxError(OnyxErrorCode.BAD_GATEWAY, detail, status_code_override=e.response.status_code)
```

## Best Practices

In addition to the other content in this file, best practices for contributing
to the codebase can be found in the "Engineering Best Practices" section of
`CONTRIBUTING.md`. Understand its contents and follow them.
