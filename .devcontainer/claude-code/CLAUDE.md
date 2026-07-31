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

`ods web <script>` self-heals its prerequisites before running: it runs
`bun install --frozen-lockfile` when `web/node_modules` is missing, empty, or was installed from a
different `bun.lock` (tracked via a hash stamp inside node_modules), and rebuilds the workspace
packages `web/lib/shared` / `web/lib/opal` when their `dist/` is missing or older than their
sources. If an older `ods` build (it's compiled into `.venv/bin` — refresh with `uv sync`) hits
these anyway, the symptoms and fixes: missing packages → `cd web && bun install`; export errors
like `Package path ./root.css is not exported` →
`cd web/lib/shared && bun run build && cd ../opal && bun run build`.

**Stop the dev servers when you're finished with them** (backgrounded processes outlive your
task otherwise):

- frontend: `pkill -f "next dev"; pkill -f next-server`
- backend: `pkill -f "uvicorn onyx.main:app"`

## Playwright / browser access

Browsers live in the shared cache at `/opt/ms-playwright` (`PLAYWRIGHT_BROWSERS_PATH`). Playwright
browser builds are revision-coupled to the playwright version that installs them, so "a" chromium
being present doesn't mean *your* playwright can see it — always install with the version that
will drive it:

- **Playwright MCP browser tools** (`browser_navigate` etc.) run playwright chromium, baked into
  the image for the `@playwright/mcp` version pinned in `.mcp.json`. If the tools report a missing
  browser (container from an older image), install the matching revision once:
  `npx -y playwright@"$(npm view @playwright/mcp@<pin from .mcp.json> dependencies.playwright)" install chromium`.
- **The e2e runner** (`web/tests/e2e`) tracks `web/package.json`'s playwright, so its chromium is
  installed at test time, not baked. If a run reports the browser missing:
  `cd web && npx playwright install chromium`. The backend integration conftest handles its own
  playwright-python install.

Login credentials for driving the UI are in the root guide's KEY NOTES.
