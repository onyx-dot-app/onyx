# DEVCONTAINER OVERLAY

Running **inside the Onyx dev container**. These notes are additive to the root
`/workspace/CLAUDE.md`; on conflict with a host-oriented instruction there, prefer these.

## No Docker daemon in here

Don't use `docker` / `docker exec` / `docker compose`. Onyx services run as sibling
containers on the `onyx_default` network, reachable directly by hostname — the root
guide's `psql` command works as-is here (the env vars below plus `POSTGRES_PASSWORD`
are exported); its `docker exec` fallback won't.

## Service hostnames (`onyx_default` network)

Each is also exported as an env var:

- Postgres: `relational_db` (`POSTGRES_HOST`)
- Redis: `cache` (`REDIS_HOST`)
- Vespa: `index` (`VESPA_HOST`)
- Model server: `inference_model_server` (`MODEL_SERVER_HOST`)
- OpenSearch: `opensearch` (`OPENSEARCH_HOST`)
- MinIO / S3: `minio:9000` (`S3_ENDPOINT_URL=http://minio:9000`)

## Running the app (web UI + API)

The supporting services above run as sibling containers, but the **frontend and backend are not
started for you** — run them in this container (both hot-reload):

- `ods web dev` — Next.js frontend on `localhost:3000`
- `ods backend api` — FastAPI backend (uvicorn) on `localhost:8080`

In dev mode the frontend proxies `/api/*` straight to the backend (the dev-only catch-all route
handler at `web/src/app/api/[...path]/route.ts`), so **`localhost:3000` serves both the UI and
`/api`** — no reverse proxy needed. You can also hit the backend directly at `localhost:8080` (note:
**no** `/api` prefix there — e.g. `/health`, `/auth/type`).

`ods web dev` runs `bun install --frozen-lockfile` first, but only when `web/node_modules` is
missing or empty. Two gaps to know about:

- A **stale** install (lockfile drifted since node_modules was populated) is not detected — if the
  dev server fails on missing packages, run `cd web && bun install` yourself.
- The workspace packages `@onyx-ai/shared` and `@onyx-ai/opal` are symlinks into `web/lib/*` whose
  exports point at `dist/`, and `bun install` does not build them. If the dev server dies with an
  export error like `Package path ./root.css is not exported`, build them (in this order):
  `cd web/lib/shared && bun run build && cd ../opal && bun run build`.

**Stop the dev servers when you're finished with them** (backgrounded processes outlive your
task otherwise):

- frontend: `pkill -f "next dev"; pkill -f next-server`
- backend: `pkill -f "uvicorn onyx.main:app"`

## Playwright / browser access

- **Playwright MCP browser tools** (`browser_navigate` etc.) drive the `chrome` channel — Google
  Chrome is baked into the image at `/opt/google/chrome/chrome`. If it's missing (container built
  from an older image), install it once: `cd web && npx playwright install chrome`.
- **Repo-pinned Playwright chromium** (the e2e runner in `web/tests/e2e`) is *not* baked — only its
  system libraries are — so the binary can track the lockfile. If a run reports the browser
  missing, install it with the Ubuntu 26.04 platform spoof (Playwright ships no 26.04 builds):
  `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-$(dpkg --print-architecture | sed s/amd64/x64/) npx playwright install chromium`
  (run from `web/`). The backend integration conftest already does this itself for
  playwright-python.

Login credentials for driving the UI are in the root guide's KEY NOTES.
