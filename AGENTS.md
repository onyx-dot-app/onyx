# PROJECT KNOWLEDGE BASE

This file provides guidance to AI agents when working with code in this repository.

## KEY NOTES

- If you run into any missing python dependency errors, try running your command with `source .venv/bin/activate` \
  to assume the python venv.
- To make tests work, check the `.env` file at the root of the project to find an OpenAI key.
- If using `playwright` to explore the frontend, you can usually log in with username `a@example.com` and password
  `a`. The app can be accessed at `http://localhost:3000`.
- You should assume that all PrivateGPT services are running. To verify, you can check the `backend/log` directory to
  make sure we see logs coming out from the relevant service.
- To connect to the Postgres database, use: `docker exec -it onyx-relational_db-1 psql -U postgres -c "<SQL>"`
- When making calls to the backend, always go through the frontend. E.g. make a call to `http://localhost:3000/api/persona` not `http://localhost:8080/api/persona`
- Put ALL db operations under the `backend/onyx/db` / `backend/ee/onyx/db` directories. Don't run queries
  outside of those directories.

## Project Overview

**PrivateGPT** (formerly Danswer) is an open-source Gen-AI and Enterprise Search platform that connects to company documents, apps, and people. It features a modular architecture with both Community Edition (MIT licensed) and Enterprise Edition offerings.

### Background Workers (Celery)

PrivateGPT uses Celery for asynchronous task processing with multiple specialized workers:

#### Worker Types

1. **Primary Worker** (`celery_app.py`)
   - Coordinates core background tasks and system-wide operations
   - Handles connector management, document sync, pruning, and periodic checks
   - Runs with 4 threads concurrency
   - Tasks: connector deletion, vespa sync, pruning, LLM model updates, user file sync

2. **Docfetching Worker** (`docfetching`)
   - Fetches documents from external data sources (connectors)
   - Spawns docprocessing tasks for each document batch
   - Implements watchdog monitoring for stuck connectors
   - Configurable concurrency (default from env)

3. **Docprocessing Worker** (`docprocessing`)
   - Processes fetched documents through the indexing pipeline:
     - Upserts documents to PostgreSQL
     - Chunks documents and adds contextual information
     - Embeds chunks via model server
     - Writes chunks to Vespa vector database
     - Updates document metadata
   - Configurable concurrency (default from env)

4. **Light Worker** (`light`)
   - Handles lightweight, fast operations
   - Tasks: vespa operations, document permissions sync, external group sync
   - Higher concurrency for quick tasks

5. **Heavy Worker** (`heavy`)
   - Handles resource-intensive operations
   - Primary task: document pruning operations
   - Runs with 4 threads concurrency

6. **KG Processing Worker** (`kg_processing`)
   - Handles Knowledge Graph processing and clustering
   - Builds relationships between documents
   - Runs clustering algorithms
   - Configurable concurrency

7. **Monitoring Worker** (`monitoring`)
   - System health monitoring and metrics collection
   - Monitors Celery queues, process memory, and system status
   - Single thread (monitoring doesn't need parallelism)
   - Cloud-specific monitoring tasks

8. **User File Processing Worker** (`user_file_processing`)
   - Processes user-uploaded files
   - Handles user file indexing and project synchronization
   - Configurable concurrency

9. **Beat Worker** (`beat`)
   - Celery's scheduler for periodic tasks
   - Uses DynamicTenantScheduler for multi-tenant support
   - Schedules tasks like:
     - Indexing checks (every 15 seconds)
     - Connector deletion checks (every 20 seconds)
     - Vespa sync checks (every 20 seconds)
     - Pruning checks (every 20 seconds)
     - KG processing (every 60 seconds)
     - Monitoring tasks (every 5 minutes)
     - Cleanup tasks (hourly)

#### Key Features

- **Thread-based Workers**: All workers use thread pools (not processes) for stability
- **Tenant Awareness**: Multi-tenant support with per-tenant task isolation. There is a
  middleware layer that automatically finds the appropriate tenant ID when sending tasks
  via Celery Beat.
- **Task Prioritization**: High, Medium, Low priority queues
- **Monitoring**: Built-in heartbeat and liveness checking
- **Failure Handling**: Automatic retry and failure recovery mechanisms
- **Redis Coordination**: Inter-process communication via Redis
- **PostgreSQL State**: Task state and metadata stored in PostgreSQL

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
to ask me to restart the celery worker. There is no auto-restart on code-change mechanism.

**Task Time Limits**:
Since all tasks are executed in thread pools, the time limit features of Celery are silently 
disabled and won't work. Timeout logic must be implemented within the task itself.

### Code Quality

```bash
# Install and run pre-commit hooks
pre-commit install
pre-commit run --all-files
```

NOTE: Always make sure everything is strictly typed (both in Python and Typescript).

## Architecture Overview

### Technology Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy, Alembic, Celery
- **Frontend**: Next.js 15+, React 18, TypeScript, Tailwind CSS
- **Database**: PostgreSQL with Redis caching
- **Search**: Vespa vector database
- **Auth**: OAuth2, SAML, multi-provider support
- **AI/ML**: LangChain, LiteLLM, multiple embedding models

### Directory Structure

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
│   └── server/                  # API endpoints & routers
├── ee/                          # Enterprise Edition features
├── alembic/                     # Database migrations
└── tests/                       # Test suites

web/
├── src/app/                     # Next.js app router pages
├── src/components/              # Reusable React components
└── src/lib/                     # Utilities & business logic
```

## Frontend Standards

Frontend standards for the `web/` and `desktop/` projects live in `web/AGENTS.md`.

## Database & Migrations

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

First, you must activate the virtual environment with `source .venv/bin/activate`.

There are 4 main types of tests within PrivateGPT:

### Unit Tests

These should not assume any PrivateGPT/external services are available to be called.
Interactions with the outside world should be mocked using `unittest.mock`. Generally, only
write these for complex, isolated modules e.g. `citation_processing.py`.

To run them:

```bash
pytest -xv backend/tests/unit
```

### External Dependency Unit Tests

These tests assume that all external dependencies of PrivateGPT are available and callable (e.g. Postgres, Redis,
MinIO/S3, Vespa are running + OpenAI can be called + any request to the internet is fine + etc.).

However, the actual PrivateGPT containers are not running and with these tests we call the function to test directly.
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

Standard integration tests. Every test in `backend/tests/integration` runs against a real PrivateGPT deployment. We cannot
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

These tests are an even more complete version of the Integration Tests mentioned above. Has all services of PrivateGPT
running, _including_ the Web Server.

Use these tests for anything that requires significant frontend <-> backend coordination.

Tests are located at `web/tests/e2e`. Tests are written in TypeScript.

To run them:

```bash
npx playwright test <TEST_NAME>
```

For shared fixtures, best practices, and detailed guidance, see `backend/tests/README.md`.

## Logs

When (1) writing integration tests or (2) doing live tests (e.g. curl / playwright) you can get access
to logs via the `backend/log/<service_name>_debug.log` file. All PrivateGPT services (api_server, web_server, celery_X)
will be tailing their logs to this file.

## Security Considerations

- Never commit API keys or secrets to repository
- Use encrypted credential storage for connector credentials
- Follow RBAC patterns for new features
- Implement proper input validation with Pydantic models
- Use parameterized queries to prevent SQL injection

## AI/LLM Integration

- Multiple LLM providers supported via LiteLLM
- Configurable models per feature (chat, search, embeddings)
- Streaming support for real-time responses
- Token management and rate limiting
- Custom prompts and agent actions

## Creating a Plan

When creating a plan in the `plans` directory, make sure to include at least these elements:

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
to the codebase can be found at `contributing_guides/best_practices.md`.
Understand its contents and follow them.
