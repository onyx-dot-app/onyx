# Supplemental dev containers

This directory holds **opt-in** Docker Compose stacks that a developer can stand up
*alongside* the normal Onyx dev services for local testing. They are not part of any
Onyx deployment — bring them up only when you need them.

| Stack | File | What it gives you |
| --- | --- | --- |
| Langfuse | `docker-compose.langfuse.yml` | A local, self-hosted [Langfuse](https://langfuse.com) v3 instance for viewing LLM traces |

---

## Langfuse (LLM tracing)

Onyx already emits LLM/embedding/rerank traces (see `backend/onyx/tracing/`). When
`LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` are set, `setup_tracing()`
(`backend/onyx/tracing/setup.py`) ships those traces to Langfuse. This stack gives you a
local Langfuse to send them to instead of Langfuse Cloud.

It runs the full Langfuse **v3** stack (required by the pinned `langfuse==3.10.0` SDK):
`langfuse-web`, `langfuse-worker`, and namespaced Postgres / ClickHouse / Redis / MinIO.
These are isolated on a private `langfuse-internal` network and do **not** touch Onyx's
own `relational_db` / `cache` / `minio`. Only `langfuse-web` is additionally attached to
Onyx's `onyx_default` network so the backend can reach it by hostname.

### 1. Start it

Run from the **host** (there is no Docker daemon inside the dev container). The Onyx dev
services must already be up, since this attaches to their `onyx_default` network:

```bash
docker compose -f deployment/docker_compose/dev/docker-compose.langfuse.yml up -d --wait
```

First boot takes a minute or two while ClickHouse migrations run. On first boot Langfuse
is seeded (headless init) with a deterministic org, project, user, and API keys so there
is nothing to click through.

### 2. Point the Onyx backend at it

Add these to `.vscode/.env` (the env the in-container backend reads):

```bash
LANGFUSE_HOST=http://langfuse-web:3000
LANGFUSE_PUBLIC_KEY=pk-lf-onyx-local-dev
LANGFUSE_SECRET_KEY=sk-lf-onyx-local-dev
```

Then **restart `ods backend api`** — tracing is initialized once at startup, so a restart
is required to pick up the new env. For traces from background (Celery) LLM calls, restart
the relevant worker too. On success the backend log
(`backend/log/api_server_debug.log`) prints:

```
Tracing initialized with providers: langfuse
```

> If you run the backend on the **host** rather than in the dev container, use
> `LANGFUSE_HOST=http://localhost:3001` instead.

### 3. View traces

Open the UI at <http://localhost:3001> and log in with the seeded credentials:

- **Email:** `dev@onyx.app`
- **Password:** `onyxlocaldev`

Trigger an LLM call (e.g. send a chat at <http://localhost:3000>) and the corresponding
trace/generation appears under the **Onyx Local Dev** project within a few seconds.

### Ports

| Host port | Service | Notes |
| --- | --- | --- |
| `3001` | `langfuse-web` | Langfuse UI + ingestion API |
| `9090` / `9091` | `langfuse-minio` | Blob store API / console (browser-facing media links) |

Postgres / ClickHouse / Redis are intentionally **not** published to the host — they're
only reachable inside the `langfuse-internal` network, avoiding conflicts with Onyx's dev
ports (5432, 6379, 9000, …).

### Teardown / reset

```bash
# Stop, keep data (and the seeded keys):
docker compose -f deployment/docker_compose/dev/docker-compose.langfuse.yml down

# Stop and wipe all Langfuse data (re-seeds keys on next boot):
docker compose -f deployment/docker_compose/dev/docker-compose.langfuse.yml down -v
```

### ⚠️ Local-dev only

Every credential and key baked into `docker-compose.langfuse.yml` (the API keys, the
`ENCRYPTION_KEY`, DB passwords, etc.) is a hardcoded local-dev default. Never reuse any of
them outside local development.
