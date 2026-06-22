# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## KEY NOTES

- This repo is **GlomiAI**, a hard fork of Onyx. **Never click GitHub "Sync fork"** — the fork is intentionally diverged.
- Python deps live in a `uv`-managed virtualenv at `.venv` (repo root). If it doesn't exist yet, create it with `uv sync --frozen`, then `source .venv/bin/activate`.
- To make tests work, check the `.env` file at the root of the project to find an OpenAI key.
- If using `playwright` to explore the frontend, you can usually log in with username `a@example.com` and password `a`. The app can be accessed at `http://localhost:3000`.
- You should assume that all Onyx services are running. To verify, you can check the `backend/log` directory to make sure we see logs coming out from the relevant service.
- To connect to the Postgres database, use: `docker exec -it onyx-relational_db-1 psql -U postgres -c "<SQL>"`
- When making calls to the backend, always go through the frontend. E.g. make a call to `http://localhost:3000/api/persona` not `http://localhost:8080/api/persona`
- Put ALL db operations under the `backend/onyx/db` / `backend/ee/onyx/db` directories. Don't run queries outside of those directories.

## Common Commands

### Backend

```bash
# Activate virtualenv (always do this first)
source .venv/bin/activate

# Run unit tests
pytest -xv backend/tests/unit

# Run a single test file
pytest -xv backend/tests/unit/path/to/test_file.py

# Run external dependency tests (requires running services)
python -m dotenv -f .vscode/.env run -- pytest backend/tests/external_dependency_unit

# Run integration tests
python -m dotenv -f .vscode/.env run -- pytest backend/tests/integration

# Type checking
uv run ty check backend/

# Linting / formatting
uv run pre-commit run --all-files
```

### Frontend

```bash
# Install deps
cd web && bun install

# Start dev server
cd web && bun dev

# Type checking
cd web && npm run types:check

# Linting
cd web && npm run lint

# Run a specific test
cd web && bun test <path/to/test>

# E2E tests
bunx playwright test <TEST_NAME>
```

## Project Overview

**GlomiAI** is a C-end consumer AI agent platform (Chinese market), built on Onyx (MIT). It features deep research, super-conversation with tool use, and Craft (code/artifact generation sandbox).

Current phase: **Phase B** — Craft as delivery runtime + share pages + orchestrator routing.

### Architecture Overview

**Technology Stack**

- **Backend**: Python 3.13, FastAPI, SQLAlchemy, Alembic, Celery
- **Frontend**: Next.js 15+, React 18, TypeScript, Tailwind CSS
- **Database**: PostgreSQL with Redis caching
- **Search**: Vespa vector database + Glomi Search Gateway (proxies to Tavily)
- **Auth**: OAuth2, SAML, multi-provider support
- **AI/ML**: LangChain, LiteLLM, multiple embedding models

**Directory Structure**

```
backend/
├── onyx/
│   ├── auth/                    # Authentication & authorization
│   ├── chat/                    # Chat functionality & LLM interactions
│   ├── connectors/              # Data source connectors
│   ├── db/                      # Database models & operations
│   ├── document_index/          # Vespa integration
│   ├── federated_connectors/    # External search connectors
│   ├── llm/                     # LLM provider integrations
│   ├── search_gateway/          # Glomi Search Gateway (FastAPI, proxies Tavily)
│   └── server/                  # API endpoints & routers
│       └── features/build/      # Craft sandbox feature
├── ee/                          # Enterprise Edition features
├── alembic/                     # Database migrations
└── tests/                       # Test suites

web/
├── lib/opal/src/                # Opal design system (preferred for all new components)
├── src/app/                     # Next.js app router pages
├── src/refresh-components/      # Production components (not yet in Opal)
├── src/sections/                # Feature-specific composite components
├── src/layouts/                 # Page-level layout components
├── src/components/              # LEGACY — do not use
└── src/lib/                     # Utilities & business logic
```

### Background Workers (Celery)

Onyx uses Celery for asynchronous task processing with multiple specialized workers:

1. **Primary Worker** (`celery_app.py`) — connector management, document sync, pruning, periodic checks; 4 threads
2. **Docfetching Worker** — fetches documents from external sources; spawns docprocessing tasks
3. **Docprocessing Worker** — indexes pipeline: upsert to PG → chunk → embed → write to Vespa
4. **Light Worker** — vespa metadata sync, connector deletion, permissions upsert, cleanup
5. **Heavy Worker** — connector pruning, permissions sync, external group sync, CSV generation; 4 threads
6. **Monitoring Worker** — health monitoring and metrics; single thread
7. **User File Processing Worker** — user-uploaded file indexing
8. **Beat Worker** — Celery scheduler using DynamicTenantScheduler; fires indexing checks every 15s, connector checks every 20s

**Celery Task Rules**:
- Always use `@shared_task` (not `@celery_app`)
- Put tasks under `background/celery/tasks/` or `ee/background/celery/tasks`
- Always supply `expires=` when enqueuing — never enqueue without expiration
- Time limit features are silently disabled (thread pools); implement timeouts within the task itself
- To test celery changes, ask the user to restart the worker (no auto-restart)

## Frontend Standards

Full standards live in `web/AGENTS.md`. Key rules:

### Component Hierarchy (most → least preferred)
1. `web/lib/opal/src/` — Opal design system; use for all new components
2. `web/src/refresh-components/` — production components not yet migrated to Opal
3. **Never use `web/src/components/`** — legacy, being phased out

### Colors
Always use custom Tailwind overrides from `web/tailwind-themes/tailwind.config.js` — never standard Tailwind colors. They use CSS variables that handle dark mode automatically.

```typescript
// ✅ Good
<div className="bg-background-neutral-01 border border-border-02 text-text-01" />

// ❌ Bad
<div className="bg-gray-100 border border-gray-300 text-gray-600" />
```

### Other Key Rules
- **Imports**: always use absolute `@/` prefix, not relative paths
- **Components**: regular `function` syntax, not arrow functions
- **Props**: extract into a named interface in the same file; shared types go in `interfaces.ts`
- **Class names**: use `cn()` utility, not template strings
- **Data fetching**: prefer `useSWR`; load data at the component level, not at the top and passed down
- **Spacing**: prefer `padding` over `margin`; use component `padding` prop when available
- **Hooks**: one hook per file in `web/src/hooks/`
- **Settings pages**: use `SettingsLayouts.Root/Header/Body` from `@/layouts/settings-layouts`

## Database & Migrations

```bash
# Run migrations
alembic upgrade head

# Multi-tenant (Enterprise)
alembic -n schema_private upgrade head

# Create migration (write migration content manually in the generated file)
alembic revision -m "description"
alembic -n schema_private revision -m "description"
```

## Testing Strategy

First, activate the virtualenv: `source .venv/bin/activate`. If `.venv` doesn't exist yet, run `uv sync --frozen` first.

### Model choice for tests that make real LLM calls

- **OpenAI**: `gpt-5-mini` (never `gpt-4o` / `gpt-4o-mini`)
- **Anthropic**: `claude-haiku-4-5`

### Test Types (in preference order)

1. **Integration tests** — run against real Onyx deployment, no mocks; preferred for most features
   - Check root `conftest.py` for fixtures; use `common_utils/` Manager classes over raw `requests`
   - Example: `backend/tests/integration/tests/streaming_endpoints/test_chat_stream.py`

2. **External Dependency Unit tests** — real external services (Postgres, Redis, etc.) but Onyx containers not running; allows targeted mocking
   - Example: `backend/tests/external_dependency_unit/connectors/confluence/test_confluence_group_sync.py`

3. **Unit tests** — no external services; mock everything with `unittest.mock`; only for complex isolated modules

4. **Playwright (E2E)** — full stack including web server; tests in `web/tests/e2e`

For shared fixtures and best practices, see `backend/tests/README.md`.

## Logs

Access service logs at `backend/log/<service_name>_debug.log` (api_server, web_server, celery_X).

## API & Error Handling

**Defining APIs**: Do NOT use the `response_model` field on FastAPI routes — just type the function.

**Error handling**: Always raise `OnyxError` instead of `HTTPException`:

```python
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

# ✅ Good
raise OnyxError(OnyxErrorCode.NOT_FOUND, "Session not found")
raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
raise OnyxError(OnyxErrorCode.BAD_GATEWAY, detail, status_code_override=upstream_status)

# ❌ Bad
raise HTTPException(status_code=404, detail="Session not found")
```

Add new error codes to `backend/onyx/error_handling/error_codes.py` — don't invent ad-hoc codes.

## AI/LLM Integration

### Tracing — every LLM invocation must be tagged

Every LLM, embedding, rerank, image-generation, voice (STT/TTS), and intent-classification call must open a generation span tagged with a value from the `LLMFlow` registry in `backend/onyx/tracing/flows.py`:

- `llm_generation_span(llm=..., flow=LLMFlow.X, input_messages=...)` for `LLM` subclass calls
- `traced_llm_call(flow=LLMFlow.X, model=..., provider=..., input_messages=...)` for direct SDK/litellm calls

Rules:
1. Add a new `LLMFlow` enum value before instrumenting a new operation.
2. Flow tags name the **operation** (e.g. `IMAGE_EDIT`, `RERANK`), not the provider.
3. `LLMFlow.UNTAGGED_INVOKE` / `UNTAGGED_STREAM` in dashboards means missing instrumentation — fix the call site.

## Creating a Plan

Plans go in `docs/superpowers/plans/`. Required sections:

**Issues to Address** — what the change is meant to do.

**Important Notes** — non-obvious findings from codebase research.

**Implementation strategy** — high-level approach; reference files/functions but no code.

**Tests** — which test type(s) and what to verify. Don't overtest; usually one type suffices.

Do NOT include: Timeline, Rollback plan.

## Code Quality

```bash
# Install and run pre-commit hooks (ruff / ruff format)
pre-commit install
pre-commit run --all-files
```

Everything must be strictly typed (Python and TypeScript). See `CONTRIBUTING.md` → "Engineering Best Practices" for full style and maintainability guidelines.

## Change Tracking

- All changes, pitfalls, and learnings must be recorded in `summary.md`.
- Product-related changes must also be reflected in `docs/GlomiAI.md`.
