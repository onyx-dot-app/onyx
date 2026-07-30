# Local Compose Development for Craft (Docker Backend)

How to iterate on Craft against the docker-compose sandbox backend
(`SANDBOX_BACKEND=docker`) with a local debugger attached.

## When to use this

You want to work on the **docker** sandbox path or the **sandbox-proxy**
service — typically because you're touching code under
`backend/onyx/sandbox_proxy/`,
`backend/onyx/server/features/build/sandbox/docker/`, or
`deployment/docker_compose/docker-compose.craft.yml`.

For day-to-day Craft work against the kubernetes backend (the canonical
dev path for non-docker-specific work), see
[local-kubernetes.md](./local-kubernetes.md) instead. Compose-side
iteration here is slower than the kind path for general Craft work; it's
the right tool when the docker plumbing itself is what you're changing.

## Prerequisites

- Docker Desktop running with at least 8 CPU / 16 GB allocated.
- The CONTRIBUTING.md prereqs (Python 3.13, uv, Node 22, the venv,
  `.vscode/.env`).
- A built `onyxdotapp/sandbox:dev` image. Build with:

  ```bash
  docker build \
    -t onyxdotapp/sandbox:dev \
    backend/onyx/server/features/build/sandbox/image
  ```

  The sandbox image is shared between K8s and compose; the same tag
  that `make craft-sandbox-image` builds for kind works here.

## One-time setup

Pre-create the compose-external resources the craft overlay references:

```bash
docker network create onyx_craft_sandbox
docker volume create sandbox_proxy_ca
```

These are the same resources `install.sh --include-craft` creates for
self-hosters. The local dev flow uses the same resources directly so
the manager mounts the same unprefixed names.

## Two recipes

### Recipe A — full stack in compose, no local debugger

Closest to what self-hosters get from `install.sh --include-craft`.
Useful for smoke-testing end-to-end behavior.

```bash
cd deployment/docker_compose
SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:dev \
docker compose \
  -f docker-compose.yml \
  -f docker-compose.craft.yml \
  --env-file env.template \
  up -d --wait
```

Proxy posture is mandatory under `SANDBOX_BACKEND=docker`: every sandbox
provisioned by api_server gets `firewall-init.sh` (iptables egress
lockdown + `setpriv` capability bounding) and routes HTTPS through
`sandbox-proxy`. `DockerSandboxManager._initialize` raises at api_server
startup if `SANDBOX_PROXY_HOST` is empty. To iterate without the proxy,
use the K8s recipe linked above (`SANDBOX_BACKEND=kubernetes`).

Why `${SANDBOX_PROXY_HOST-sandbox-proxy}` uses a single dash, not `:-`:
the dash form preserves an explicit empty string, which is what lets
the fail-loud check above fire. `${SANDBOX_PROXY_PORT:-8080}` uses
`:-` because empty there is just a typo, not a signal.

Tail proxy logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.craft.yml logs -f sandbox-proxy
```

### Recipe B — debugger-attached iteration on the proxy

Iterate on `sandbox_proxy/` code with the VSCode debugger attached.

1. **Bring up infra only.** Postgres + Redis are required by the proxy:

   ```bash
   ods compose dev --infra
   ods env
   ```

   `ods env` writes the resolved port mappings into `.vscode/.env` so
   anything you launch locally connects to the compose-side infra.

2. **Run the proxy locally** under the debugger. From the repo root:

   ```bash
   source .venv/bin/activate
   PYTHONPATH=./backend \
   SANDBOX_BACKEND=docker \
   SANDBOX_PROXY_LISTEN_PORT=8888 \
   python -m onyx.sandbox_proxy.server
   ```

   `PYTHONPATH=./backend` is required because the `onyx` package lives
   under `backend/`; running from the repo root without it raises
   `ModuleNotFoundError`. Same applies to step 3 below.

   Or add a VSCode launch config that points at
   `backend/onyx/sandbox_proxy/server.py` with the same env. The
   proxy reads `.vscode/.env` for Postgres + Redis hosts.

   The `SANDBOX_PROXY_LISTEN_PORT=8888` override is load-bearing for
   Recipe B: the proxy defaults to 8080, but api_server (step 3) also
   binds 8080 on the host, so we move the proxy elsewhere. Healthz
   stays on its 8081 default (free).

   The `FileCAStore` writes to `/var/lib/sandbox-proxy/ca/`. That path
   is hardcoded (`SANDBOX_PROXY_CA_VOLUME_PATH` in `configs.py` is a
   constant, not env-driven), so the local proxy needs write access
   there — either pre-create it with your uid (`sudo mkdir -p
   /var/lib/sandbox-proxy/ca && sudo chown $USER /var/lib/sandbox-proxy/ca`)
   or run the proxy via `sudo`.

3. **Run api_server locally** with the docker backend pointed at your
   local proxy:

   ```bash
   PYTHONPATH=./backend \
   SANDBOX_BACKEND=docker \
   SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:dev \
   SANDBOX_PROXY_HOST=host.docker.internal \
   SANDBOX_PROXY_PORT=8888 \
   uvicorn onyx.main:app --host 0.0.0.0 --port 8080
   ```

   The api_server provisions sandbox containers via the host docker
   socket. Each sandbox's `firewall-init.sh` resolves
   `host.docker.internal` to the host's IP and pins it in iptables;
   the locally-running proxy receives the traffic.

   *Caveat:* `host.docker.internal` works on Docker Desktop (Mac/Win).
   On Linux you'll need `--add-host=host.docker.internal:host-gateway`
   on the sandbox containers, which isn't currently plumbed — easier
   to use Recipe A on Linux.

4. **Provision a sandbox** via the API as you normally would, and
   trigger a gated action (e.g. a Slack `chat.postMessage`). Set
   breakpoints in `gate.py`, `addons/gate.py`, `identity_docker.py`,
   etc.

## Smoke-check commands

From inside a freshly-provisioned sandbox container:

```bash
docker exec -it sandbox-<id8> bash

# Egress through the proxy: succeeds, leaf cert signed by proxy CA.
curl -v https://example.com 2>&1 | grep -E '(Issuer|HTTP/)'

# Bypass attempt: blocked by iptables.
curl --noproxy '*' --max-time 5 https://example.com

# DNS closed.
nslookup example.com

# IPv6 dropped.
curl -6 --max-time 5 https://example.com

# Verify the agent runs with zero caps.
getpcaps $$
```

## Teardown

```bash
cd deployment/docker_compose
docker compose -f docker-compose.yml -f docker-compose.craft.yml down

# Optional: clear the proxy CA (forces regeneration on next start).
docker volume rm sandbox_proxy_ca

# Optional: clear sandbox state.
docker volume ls --filter "name=onyx-craft-sandbox-" -q | xargs -r docker volume rm
```

## Common issues

- **`firewall-init.sh: FATAL: CA source /sandbox-ca/ca.crt not present`** —
  the proxy hasn't bootstrapped the CA yet. Wait for `sandbox-proxy` to
  log "persisted proxy CA cert=..." (Recipe A) or for your local proxy
  to log the same (Recipe B), then re-provision the sandbox.

- **`firewall-init.sh: FATAL: could not resolve proxy host sandbox-proxy`** —
  the sandbox container can't resolve the proxy name. Check that the
  sandbox is on the `onyx_craft_sandbox` network (`docker inspect
  sandbox-<id8>`) and that the proxy is up on the same network.

- **All egress fails with 403 `unidentified_sandbox`** — the
  `DockerEventsLookup` doesn't see the sandbox container's labels.
  Verify the labels with `docker inspect sandbox-<id8> | grep onyx.app`;
  if missing, the manager wasn't running with `SANDBOX_BACKEND=docker`.

- **`docker volume inspect: No such volume: sandbox_proxy_ca`** — the
  pre-create step was skipped. Run `docker volume create sandbox_proxy_ca`.

- **Sandbox container fails to start with capability errors after
  proxy restart** — the proxy got a new IP on bridge restart but the
  sandbox's iptables rule still pins the old IP. Re-provision the
  sandbox.
