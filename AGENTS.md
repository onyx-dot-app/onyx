# PROJECT KNOWLEDGE BASE

This file provides guidance to AI agents when working with code in this repository.

## KEY NOTES

- Python deps live in a `uv`-managed virtualenv at `.venv` (repo root). If it doesn't exist yet, create it
  with `uv sync --frozen`, then `source .venv/bin/activate`.
- Test secrets (API keys etc.) are resolved by `backend/tests/utils/aws_secrets.py`, in order: process
  env vars → the gitignored `.vscode/.env` (also used by the pytest commands in `backend/AGENTS.md`;
  create it by copying `.vscode/env_template.txt`) → AWS Secrets Manager (requires `aws sso login`).
  Tests declare what they need via `@pytest.mark.secrets(TestSecret.X)`. If a key you need still can't
  be resolved, ask the user rather than skipping tests.
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

## Project Overview

**Onyx** (formerly Danswer) is an open-source Gen-AI and Enterprise Search platform that connects to company documents, apps, and people. It features a modular architecture with both Community Edition (MIT licensed) and Enterprise Edition offerings.

### Technology Stack

- **Backend**: Python 3.13, FastAPI, SQLAlchemy, Alembic, Celery
- **Frontend**: Next.js 16, React 19, TypeScript, Tailwind CSS
- **Database**: PostgreSQL with Redis caching
- **Search**: OpenSearch-backed keyword and vector document index
- **Auth**: OAuth2, SAML, multi-provider support
- **AI/ML**: LangChain, LiteLLM, multiple embedding models

### Repository Layout & Sub-project Guides

Each sub-project has its own agents file with the standards for that area — read it before working
there:

- `backend/` — FastAPI app + Celery workers. `onyx/` is the Community Edition core, `ee/` mirrors its
  layout for Enterprise features, `alembic/` holds migrations, `tests/` the test suites. Standards
  (Celery, migrations, testing, error handling, LLM tracing): `backend/AGENTS.md`.
- `web/` — Next.js frontend. Standards (also cover `desktop/`, the Tauri shell): `web/AGENTS.md`.
- `mobile/` — React Native + Expo app. Standards: `mobile/AGENTS.md`. Mobile differs from web on
  several points (no DOM, NativeWind, expo-router), so do **not** assume the web rules apply there.

Explore the tree with `ls` rather than relying on docs for the full package list.

## Code Quality

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

## Testing

There are 4 main types of tests: unit, external dependency unit, integration, and playwright e2e
(`web/tests/e2e`). Commands and guidance for all four live in `backend/AGENTS.md`; shared fixtures
and deeper detail in `backend/tests/README.md`. Prefer integration tests over the other types.

## Logs

When (1) writing integration tests or (2) doing live tests (e.g. curl / playwright) you can get access
to logs via the `backend/log/<service_name>_debug.log` file. All Onyx services (api_server, web_server, celery_X)
will be tailing their logs to this file.

## Security Considerations

- Never commit API keys or secrets to the repository
- Use the encrypted credential storage for connector credentials
- Follow existing RBAC patterns for new features

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

## Best Practices

In addition to the other content in this file, best practices for contributing
to the codebase can be found in the "Engineering Best Practices" section of
`CONTRIBUTING.md`. Understand its contents and follow them.
