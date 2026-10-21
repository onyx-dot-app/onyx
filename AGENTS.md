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
- If `.agents-local.md` exists at the repo root and its rules are not already in your context,
  read and follow it. It carries developer-local agent guidance and is never committed.
- Before you start work, check that your branch does not need a rebase on `origin/main`.
  Rebase if the branch has merge conflicts with main.
  Rebase if the branch is stale: more than 3 days since it diverged from or last synced with main.
  Keeping a branch current prevents a much more involved conflict resolution later.
  The Onyx agent context hooks run this check at session start (see "Onyx agent context").
  Without them, run `git fetch origin +refs/heads/main:refs/remotes/origin/main`.
  Check for conflicts with `git merge-tree --write-tree HEAD origin/main`.
  Exit status 1 means conflicts. Other non-zero codes are errors, not conflicts.
  Check the age with `git show -s --format=%cr $(git merge-base HEAD origin/main)`.
  To update, run `git rebase origin/main`. Use `git merge origin/main` for a shared branch.
  On `main`, run `git pull --ff-only origin main`.
  If a merge or rebase is already in progress, finish it or abort it first.
  Never discard uncommitted changes to do this.

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

### Skills

Shared agent skills live in `.agents/skills/`. `.claude/skills`, `.cursor/skills` and
`.codex/skills` are symlinks to it, so add or edit skills only in `.agents/skills/`.

### Onyx agent context

Onyx staff keep a private `onyx-agent-context` repo with more skills and knowledge for agents.
Look for a folder that has its `AGENTS.md`, in this order:

1. The path in `$ONYX_AGENT_CONTEXT`. When it is set, do not look anywhere else.
2. `onyx-agent-context/` next to the main onyx checkout. The main checkout is the first path that
   `git worktree list` prints, so this works from a worktree too.
3. `.agent-context/` at the root of this checkout, then at the root of the main checkout.

If you find it, read its `AGENTS.md` and follow it. If you do not find it, continue without it.
It holds the feature map and the agent session hooks. When its hooks are set up, the session
starts with a line that begins with `[agent-context]`.

Claude Code, Codex, and Cursor run `.agents/hooks/bootstrap_agent_context.py` at session start
until those hooks are set up. For a git email at `onyx.app`, it clones the repo when it is missing,
at most once a week. It then tells you where the repo is and to offer its setup skill.

## Code Quality

```bash
# Install and run pre-commit hooks
pre-commit install
pre-commit run --all-files

# Faster: run only on the files you touched
pre-commit run --files <path> [<path> ...]
```

Before you finish, run pre-commit on the files you changed and fix what it reports.
The Onyx agent context hooks do this automatically when they are set up.

NOTE: Always make sure everything is strictly typed (both in Python and Typescript).

NOTE: Keep code comments brief and focused on information that stays relevant long-term.

## Writing

These rules apply to all prose you write: docs, commit messages, PR descriptions, reports, and replies.

Follow ASD-STE100 Simplified Technical English for technical text:

- Use approved words only. Each word has one meaning.
- Use one word for one idea. Do not use two words for the same thing.
- Write short sentences. Use 20 words or less for instructions.
- Use active voice. Write "Turn the switch", not "The switch must be turned".
- Write short paragraphs. Keep one topic in each paragraph.
- Keep code comments focused on information that is relevant long-term or for future readers.

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

## Reuse Existing Standards

Before you add a helper, utility, pattern or convention, search the codebase for one that does
the same job, and use it. For example, use the existing rate limiting, caching, URL validation,
router and settings patterns. Do not invent a parallel mechanism. If the existing one does not
do enough, extend it so other callers get the change too. A new pattern needs a reason that the
existing ones cannot meet.

## Best Practices

In addition to the other content in this file, best practices for contributing
to the codebase can be found in the "Engineering Best Practices" section of
`CONTRIBUTING.md`. Understand its contents and follow them.
