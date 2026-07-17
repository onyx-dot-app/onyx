# Running Onyx Craft on Docker Compose

This guide walks through standing up Onyx Craft on the docker-compose
backend with the `opencode serve` HTTP transport (`AGENT_TRANSPORT=serve`).
It covers the happy path and every gotcha encountered during initial bring-up
on macOS, so an agent can follow it without re-discovering each issue.

If you only need the K8s path (cloud / kind), use the Kubernetes manager and
ignore this whole doc — the Docker backend exists for self-hosted
docker-compose deployers.

---

## TL;DR — Quick Start

```bash
# 1. Stage compose files (they're not in any release tag yet).
WT=/path/to/onyx/checkout            # this repo, checked out on a branch with the Docker backend
mkdir -p ~/onyx_data/deployment ~/onyx_data/data/nginx
cp "$WT"/deployment/docker_compose/docker-compose.yml          ~/onyx_data/deployment/
cp "$WT"/deployment/docker_compose/docker-compose.craft.yml    ~/onyx_data/deployment/
cp "$WT"/deployment/docker_compose/env.template                ~/onyx_data/deployment/
cp "$WT"/deployment/data/nginx/app.conf.template               ~/onyx_data/data/nginx/
cp "$WT"/deployment/data/nginx/run-nginx.sh                    ~/onyx_data/data/nginx/

# 2. Run installer in --local mode with craft.
bash "$WT"/deployment/docker_compose/install.sh --local --include-craft

# 3. Fix the .env (existing-env install path skips these; see "Required env vars" below).
cat >> ~/onyx_data/deployment/.env <<'ENV'
ENABLE_CRAFT=true
SANDBOX_BACKEND=docker
SANDBOX_API_SERVER_URL=http://host.docker.internal:3001
HOST_PORT=3001
ENV

# 4. If running an unreleased PR (e.g. opencode-serve), build the backend
#    and sandbox images locally and point .env at them. See "Running an
#    unreleased PR" below.

# 5. Bring it up.
(cd ~/onyx_data/deployment && docker compose -f docker-compose.yml -f docker-compose.craft.yml up -d)

# 6. Configure an LLM provider via Admin UI at http://localhost:3001
#    (Craft will fail with "No default LLM model found" until you do this.)
```

---

## Prerequisites

- macOS with **Docker Desktop** (or OrbStack) — these provide `host.docker.internal`
  resolution from inside the `onyx_craft_sandbox` bridge network, which the
  sandbox container needs to reach api_server.
- On Linux, replace `http://host.docker.internal:3001` with your machine's
  reachable address (or use `--add-host` workarounds). Native Linux Docker
  does *not* resolve `host.docker.internal` by default.
- ~80 GB free Docker disk. Onyx's full stack pulls ~30 GB; local image
  builds add another 10–15 GB; build cache balloons to 40+ GB if you let
  it. See [OpenSearch read-only block](#opensearch-flipped-into-read-only-mode-disk-full) below.
- An LLM API key (Anthropic / OpenAI / etc).

---

## Required env vars

These must end up in `~/onyx_data/deployment/.env` after install:

| Variable | Required? | Notes |
|---|---|---|
| `ENABLE_CRAFT=true` | yes | `--include-craft` sets this (fresh installs and existing `.env`). |
| `SANDBOX_BACKEND=docker` | yes | `--include-craft` sets this alongside `ENABLE_CRAFT`. |
| `SANDBOX_API_SERVER_URL=http://host.docker.internal:3001` | yes | Provision raises `ValueError("SANDBOX_API_SERVER_URL must be set")` without it. Must be a URL the sandbox container can reach **from the `onyx_craft_sandbox` bridge** — compose-internal hostnames (`api_server`, `nginx`) won't resolve there. Match the port to `HOST_PORT`. |
| `HOST_PORT=3001` | only if 3000 conflicts | Default is 3000; nginx binds this on the host. Free up 3000 or change here. |
| `IMAGE_TAG` | optional | Uses the normal compose default (`latest`) unless set. Craft uses this same tag for the sandbox image, so do not set a separate sandbox image for normal deployments. There are **no** Craft-specific app/backend images — Craft is enabled at runtime via `ENABLE_CRAFT=true` (above). See [image architecture](../infra/image-architecture.md). |
| `ONYX_BACKEND_IMAGE` | only when running unreleased PRs | Lets you override just the backend image without forcing model-server / web-server to the same tag. |
| `AGENT_TRANSPORT=serve` | for serve transport | `docker-compose.craft.yml` defaults this to `serve` (post-#11402); override to `acp` for the rollback path. Reaches the sandbox container via env passthrough. |
| `ENABLE_OPENCODE_DEBUGGING=true` | optional | Dev-only pod-log viewer button in Craft UI. Default `false`. |

`OPENCODE_SERVER_PASSWORD` / `OPENCODE_CONFIG_CONTENT` / `OPENCODE_SERVE_PORT`
are **not** set by you — `DockerSandboxManager.provision()` mints the
password (`secrets.token_urlsafe(32)`) and the config content per sandbox
and injects them into the container env at create time.

---

## Setup flow in detail

### 1. Stage compose files

The install script normally downloads `docker-compose.yml` /
`docker-compose.craft.yml` / `env.template` from the latest GitHub
release. `docker-compose.craft.yml` doesn't exist in any release tag yet
— craft is `main`-only. Pre-stage from a checkout:

```bash
WT=/path/to/onyx
mkdir -p ~/onyx_data/deployment ~/onyx_data/data/nginx
cp "$WT"/deployment/docker_compose/docker-compose.yml          ~/onyx_data/deployment/
cp "$WT"/deployment/docker_compose/docker-compose.craft.yml    ~/onyx_data/deployment/
cp "$WT"/deployment/docker_compose/env.template                ~/onyx_data/deployment/
cp "$WT"/deployment/data/nginx/app.conf.template               ~/onyx_data/data/nginx/
cp "$WT"/deployment/data/nginx/run-nginx.sh                    ~/onyx_data/data/nginx/
```

### 2. Run the installer

```bash
bash "$WT"/deployment/docker_compose/install.sh --local --include-craft
```

`--local` skips downloads and uses the pre-staged files. `--include-craft`
opts into the Docker sandbox backend.

The installer is **interactive** — it reads prompts directly from `/dev/tty`,
so piping `2\n\n` as stdin does not work. Either run it from a terminal or
adapt the prompts (Standard mode = `2`, keep existing env = blank).

`--no-prompt` defaults to **Lite mode**, which is mutually exclusive with
`--include-craft`. Don't combine them.

### 3. Fix the .env

On an existing `.env`, `--include-craft` writes `ENABLE_CRAFT=true` and
`SANDBOX_BACKEND=docker` for you (on both the update and restart paths). It
does **not** set the host-specific values, so append those yourself:

```bash
cat >> ~/onyx_data/deployment/.env <<'ENV'
SANDBOX_API_SERVER_URL=http://host.docker.internal:3001
HOST_PORT=3001
ENV
```

If you also build local images for an unreleased PR, append the override
vars (see next section).

### 4. Bring up the stack

```bash
cd ~/onyx_data/deployment
docker compose -f docker-compose.yml -f docker-compose.craft.yml up -d
```

The compose file references the `onyx_craft_sandbox` network as
`external: true`. The installer creates it *only on the fresh-install
path*. If you're updating an existing install with `--include-craft`,
create it manually:

```bash
docker network create onyx_craft_sandbox
```

### 5. Configure an LLM provider

Open <http://localhost:3001>, log in, go to **Admin Panel → Language
Models**, and add a provider (Anthropic / OpenAI / OpenRouter). Until you
do this, every Craft prompt fails with:

```
ValueError: No default LLM model found
```

### 6. Try a prompt in Craft

Click **Craft** in the sidebar, send a prompt. Watch the api_server logs:

```bash
docker logs -f onyx-api_server-1 2>&1 | grep -E "SANDBOX-SERVE|SESSION-LIFECYCLE"
```

You should see:

- `[SESSION-LIFECYCLE] sandbox.ensure_opencode_session: build_session=… directory=/workspace/sessions/…`
- `[SANDBOX-SERVE] Created PodEventBus for sandbox … dir=/workspace/sessions/…`
- `[SANDBOX-SERVE] opencode-serve ready for sandbox …`
- `[SESSION-LIFECYCLE] _send_message_via_serve: build_session=… caller-supplied opencode_session_id=…`
- `[SANDBOX-SERVE] send_message completed: session=… events=… got_prompt_response=True`

---

## Running an unreleased PR (local image builds)

Published `edge` is built from `main`. If you're testing a PR that
isn't merged yet, the published images **will not contain your code**.
Build the affected images locally.

### Backend image

```bash
cd /path/to/onyx
docker build \
    -t onyxdotapp/onyx-backend:craft-pr<N> \
    -f backend/Dockerfile \
    backend/
```

~10–20 min. Craft is enabled at runtime with `ENABLE_CRAFT=true`; there is
no Craft-specific backend image flavor.

Then in `.env`:

```
ONYX_BACKEND_IMAGE=onyxdotapp/onyx-backend:craft-pr<N>
```

**Do not** change `IMAGE_TAG` to point at your PR build — `IMAGE_TAG`
applies to *every* image referenced in the compose file (model-server,
web-server, etc.), and Docker will try to pull
`onyxdotapp/onyx-model-server:craft-pr<N>` and fail. `ONYX_BACKEND_IMAGE`
is a backend-only override.

### Sandbox image

The sandbox container has its own image, but normal deployments use the
app-aligned sandbox tag selected by `IMAGE_TAG`. If you're testing a PR with
unreleased sandbox image changes, build a local override. This is for PR and
internal testing only, not normal customer deployments.

Build the sandbox image:

```bash
docker build --network=host \
    -t onyxdotapp/sandbox:pr<N> \
    -f backend/onyx/server/features/build/sandbox/image/Dockerfile \
    backend/onyx/server/features/build/sandbox/image/
```

`--network=host` bypasses Docker Desktop's HTTP proxy if `deb.debian.org`
returns `Connection refused` during apt-get. Without it, the build can fail
with "Unable to locate package python3-venv" / "Connection refused" against
the Debian apt mirror.

Then in `.env`:

```
SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:pr<N>
```

After updating `.env`, force-recreate api_server + background so they
pick up the new env:

```bash
cd ~/onyx_data/deployment
docker compose -f docker-compose.yml -f docker-compose.craft.yml \
    up -d --no-build --force-recreate api_server background
```

`--no-build` is important — without it, compose tries to *build* the
image (using the `build:` directive that's also in the compose file), and
fails because the relative `../../backend` build context doesn't resolve
from `~/onyx_data/deployment`.

---

## Issues you will hit (in roughly the order I hit them)

### macOS bash 3.2: install script aborts with `unbound variable`

Symptom (running `curl -fsSL …/install_onyx.sh | bash`):

```
/bin/bash: DOCKER_SUDO[@]: unbound variable
```

Cause: macOS still ships bash 3.2.57. Under `set -u`, expanding
`"${arr[@]}"` from an empty `arr=()` errors out — even though the array
was explicitly declared.

Fix: ship a `run_docker()` wrapper that branches on
`${#DOCKER_SUDO[@]} > 0` so the array splat only executes when
populated. See PR #11424.

### macOS bash 3.2: `HOST_PORT=3000: command not found`

Symptom: after dropping `set -u`, install still fails:

```
install.sh: line 371: HOST_PORT=3000: command not found
```

Cause: bash 3.2's parser is single-pass — when a possibly-empty
expansion sits in command position (`"${DOCKER_SUDO[@]}" VAR=val cmd`),
the parser classifies `VAR=val` as a positional argument at parse time,
not as an env-var prefix. When the array later expands to zero words,
`VAR=val` ends up being interpreted as the command name. bash 4+
re-evaluates after expansion, so Linux/CI never sees this. **Dropping
`set -u` does not fix this.**

Fix: same `run_docker()` wrapper — the call site becomes
`VAR=val run_docker $cmd …`, where the leading token is now a literal
env-var prefix on a function call (parser is happy), and the array splat
is inside the function body away from command position.

### Sudo path: env_reset strips inline VAR=val (open P1)

Greptile flagged this on PR #11424 and the user merged before
addressing it. When `DOCKER_SUDO=(sudo)` (Linux freshly-added-to-docker-
group path), `run_docker` ends up calling `sudo docker compose`. sudo's
default `env_reset` strips the inline `HOST_PORT=…` / `IMAGE_TAG=…`
prefix because those reach sudo via the parent process's *environment*,
not as positional arguments.

Pre-PR-11424 the call form was
`"${DOCKER_SUDO[@]}" VAR=val cmd`, which passes `VAR=val` as a sudo
positional argument — sudo honors that even with `env_reset` active.

Fix (not yet shipped): re-inject the relevant vars via explicit `env`
inside the sudo branch of `run_docker`:

```bash
run_docker() {
    if [ ${#DOCKER_SUDO[@]} -gt 0 ]; then
        local env_args=()
        [ -n "${HOST_PORT-}" ] && env_args+=("HOST_PORT=$HOST_PORT")
        [ -n "${IMAGE_TAG-}" ] && env_args+=("IMAGE_TAG=$IMAGE_TAG")
        "${DOCKER_SUDO[@]}" env ${env_args[@]+"${env_args[@]}"} "$@"
    else
        "$@"
    fi
}
```

### Install script skips network creation on existing-.env path

Symptom:

```
network onyx_craft_sandbox declared as external, but could not be found
✗ Failed to start Onyx services
```

Cause: install.sh's `docker network create onyx_craft_sandbox` runs
only inside the fresh-install branch (`if [ ! -f $ENV_FILE ]`). When
the script detects an existing `.env` it takes the update path and skips
network creation entirely.

Fix (PR #11402): move the network-create block out of the fresh-install
gate so it runs whenever `--include-craft` is set:

```bash
if [ "$INCLUDE_CRAFT" = true ]; then
    SANDBOX_NET="${SANDBOX_DOCKER_NETWORK:-onyx_craft_sandbox}"
    if ! run_docker docker network inspect "$SANDBOX_NET" >/dev/null 2>&1; then
        run_docker docker network create "$SANDBOX_NET" >/dev/null
    fi
fi
```

Workaround until fixed: `docker network create onyx_craft_sandbox` manually.

### `docker-compose.craft.yml` doesn't pass AGENT_TRANSPORT through (pre-#11402)

Symptom: setting `AGENT_TRANSPORT=serve` in `.env` has no effect — the
api_server container's env doesn't have it.

Cause: docker-compose only passes vars listed in a service's
`environment:` block. Variables in `.env` feed compose *interpolation*
but don't auto-propagate to containers.

Fix (PR #11402): add explicit passthrough to both `api_server` and
`background` services in `docker-compose.craft.yml`:

```yaml
environment:
  - AGENT_TRANSPORT=${AGENT_TRANSPORT:-serve}
  - ENABLE_OPENCODE_DEBUGGING=${ENABLE_OPENCODE_DEBUGGING:-false}
```

### Image staleness: published tags lag main

Symptom A: api_server crashes on boot with
`ValueError: 'docker' is not a valid SandboxBackend`. Cause: you're on a
release image older than the Docker sandbox backend (PR #11222, May 20) —
its `SandboxBackend` enum only has `LOCAL`/`KUBERNETES`.

Fix: use an image tag new enough to include it:

```
IMAGE_TAG=latest
```

Symptom B: `edge` works for the Docker backend but is missing PR
#11402's serve transport additions. `ensure_opencode_session()`
returns `None` because base.py's stub never gets overridden by
`DockerSandboxManager` (which doesn't implement `_serve_base_url` /
`_read_opencode_password` in the published image).

Fix: build the backend image locally. See "Running an unreleased PR" above.

Symptom C: `opencode-serve never became ready for sandbox … after 30s
(last error: ConnectError: [Errno 111] Connection refused)`. Cause:
your app image and sandbox image are from different source versions, or
you're testing unreleased sandbox image changes without a matching local
sandbox image.

Fix: deploy matching app/sandbox tags, or build the sandbox image locally too.
See "Running an unreleased PR".

### `IMAGE_TAG` applies to every image

Symptom: pulling fails with `No such image:
onyxdotapp/onyx-model-server:craft-pr<N>` after setting
`IMAGE_TAG=craft-pr<N>`.

Cause: `IMAGE_TAG` is referenced by the compose file's `image:` lines
for *all* services, not just the backend.

Fix: use `ONYX_BACKEND_IMAGE` to override just the backend image.

### `compose up --force-recreate` triggers a build

Symptom: `unable to prepare context: path "/path/to/Desktop/backend"
not found` when the image-tag points at a local-only tag.

Cause: when `image:` lookup fails to pull from registry, compose falls
back to the `build:` directive in the compose file. The build context
(`../../backend`) is relative to the compose file's directory, which
won't resolve from `~/onyx_data/deployment`.

Fix: pass `--no-build` to `docker compose up`.

### `compose down/up` leaves orphan containers

Symptom: `Conflict. The container name "/onyx-cache-1" is already in
use by container "…"` even though `down` reported it was removed.

Cause: a previous `up --force-recreate` interleaved with a partial
build, leaving named containers in an inconsistent state.

Fix:

```bash
docker compose -f docker-compose.yml -f docker-compose.craft.yml down
docker compose -f docker-compose.yml -f docker-compose.craft.yml up -d --no-build
```

### OpenSearch flipped into read-only mode (disk full)

Symptom: api_server crashes with:

```
TransportError(429, 'cluster_block_exception',
    'index [danswer_chunk_…] blocked by:
     [TOO_MANY_REQUESTS/12/disk usage exceeded flood-stage watermark,
      index has read-only-allow-delete block];')
```

Cause: Docker Desktop's virtual disk hit the 95% flood-stage watermark.
On macOS, the Docker VM has a fixed-size disk; image pulls + builds eat
into it. OpenSearch sees the VM disk, not the host disk.

Fix:

```bash
docker builder prune -af              # build cache is often 40+ GB
docker image prune -af --filter "until=24h"
```

After freeing enough space, OpenSearch lifts the block automatically
when disk drops below the low watermark. Restart api_server to retry.

### Port 3000 already in use

Symptom: nginx fails to bind: `bind: address already in use`.

Cause: another process (often a Node dev server) holds port 3000.

Fix:

```bash
lsof -nP -iTCP:3000 -sTCP:LISTEN     # find PID
# either kill it, or:
echo "HOST_PORT=3001" >> ~/onyx_data/deployment/.env
# then bring up the stack; access at http://localhost:3001
```

### Sandbox image apt build fails

Symptom:

```
W: Failed to fetch http://deb.debian.org/debian/dists/bookworm/InRelease
   Could not connect to deb.debian.org:80 … (111: Connection refused)
E: Unable to locate package python3-venv
```

Cause: Docker Desktop sometimes routes buildkit's outbound HTTP through
a proxy (`http.docker.internal:3128`) that's unreachable or misbehaving.

Fix: build with host networking:

```bash
docker build --network=host -t … -f Dockerfile .
```

### "Finding sandbox..." stuck in UI

Symptom: Craft UI shows "Finding sandbox..." indefinitely; no provision
activity in api_server logs.

Cause: there's a stale `Sandbox` row in the DB pointing at a container
that's been removed. The UI is waiting on a sandbox the api_server
thinks exists but can't reach.

Fix:

```bash
docker exec onyx-relational_db-1 psql -U postgres -c \
    "DELETE FROM sandbox WHERE id = '<sandbox-uuid>';"
```

After delete, the next prompt in Craft triggers a fresh provision.

### Stale sandbox container running with old env

Symptom: a sandbox container exists from a previous install but lacks
the env vars the new code injects (no `AGENT_TRANSPORT`, no
`OPENCODE_SERVER_PASSWORD`, etc.).

Cause: the container was provisioned by a previous api_server image
that didn't know about those vars. Restarting api_server doesn't
rebuild existing containers.

Fix: kill the container + its volume:

```bash
docker rm -f sandbox-<id>
docker volume rm onyx-craft-sandbox-<id>
docker exec onyx-relational_db-1 psql -U postgres -c \
    "DELETE FROM sandbox WHERE id = '<full-uuid>';"
```

Next Craft prompt re-provisions with the current code's env injection.

---

## How to verify it's actually working

1. **API server has the serve methods** (post-#11402 code is loaded):
   ```bash
   docker exec onyx-api_server-1 grep -c "_serve_base_url\|_read_opencode_password" \
       /app/onyx/server/features/build/sandbox/docker/docker_sandbox_manager.py
   # Expected: 2
   ```

2. **`SandboxBackend.DOCKER` exists** (post-#11222 code is loaded):
   ```bash
   docker exec onyx-api_server-1 python -c \
       "from onyx.server.features.build.configs import SandboxBackend; print(list(SandboxBackend))"
   # Expected: [..., <SandboxBackend.DOCKER: 'docker'>]
   ```

3. **Sandbox image's entrypoint gates on AGENT_TRANSPORT** (post-#11402 image):
   ```bash
   docker run --rm --entrypoint cat <your-sandbox-image> /workspace/entrypoint.sh \
       | grep -E "AGENT_TRANSPORT|opencode serve"
   # Expected: lines referencing both
   ```

4. **After a prompt fires**, a sandbox container should exist:
   ```bash
   docker ps --filter "name=sandbox-" --format "{{.Names}} {{.Status}} {{.Ports}}"
   # Expected: one sandbox-<id8> Up, with port 4096 visible (internal)
   ```

5. **Inside that container**, opencode serve should be running:
   ```bash
   docker exec sandbox-<id8> ps auxw | grep opencode
   # Expected: an `opencode serve` process; NOT just `sleep infinity`
   ```

6. **opencode-serve is reachable** from api_server:
   ```bash
   docker exec onyx-api_server-1 curl -fsS \
       -u "opencode:$(docker inspect sandbox-<id8> --format '{{range .Config.Env}}{{println .}}{{end}}' \
                       | grep '^OPENCODE_SERVER_PASSWORD=' | cut -d= -f2-)" \
       http://sandbox-<id8>:4096/doc \
     | head -c 100
   # Expected: an OpenAPI / Swagger blob (non-empty)
   ```

7. **Logs show the full serve-transport sequence** when a prompt is sent:
   ```bash
   docker logs -f onyx-api_server-1 2>&1 | grep -E "SANDBOX-SERVE|SESSION-LIFECYCLE"
   ```
   You should see `ensure_opencode_session`, `Created PodEventBus`,
   `opencode-serve ready`, `_send_message_via_serve`, `send_message completed`
   — in that order, all within a few seconds of the prompt.

---

## Cleanup / teardown

```bash
# Stop the stack (keeps data):
cd ~/onyx_data/deployment
docker compose -f docker-compose.yml -f docker-compose.craft.yml down

# Or use the installer:
bash /path/to/install.sh --shutdown   # stop containers, keep volumes
bash /path/to/install.sh --delete-data # stop AND wipe all data

# Kill orphan sandbox containers:
docker ps --filter "name=sandbox-" -q | xargs -r docker rm -f

# Reclaim Docker disk after testing:
docker builder prune -af
docker image prune -af --filter "until=24h"
```

---

## Related references

- PR #11222 — `feat(craft): docker-compose sandbox backend` — added the
  Docker manager + craft compose file.
- PR #11334 — `feat(craft): opencode-serve transport with PodEventBus` —
  added the serve transport on K8s.
- PR #11402 — `feat(craft): port DockerSandboxManager to opencode-serve
  transport` — Docker side of the serve port (this work).
- PR #11424 — `fix(install): route DOCKER_SUDO via wrapper so bash 3.2
  parses empty arrays` — install.sh fix for macOS.
- `docs/craft/opencode-serve-migration.md` — design doc for the serve
  transport.
- `docs/craft/docker-opencode-serve.md` — design doc for the Docker
  serve port.
