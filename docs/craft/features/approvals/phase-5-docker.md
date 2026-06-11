# Phase 5 -- Docker-compose backend support (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 1 (`SandboxIPLookup`, `CAStore`, `firewall-init.sh`
bootstrap-mode switch) and Phase 2 (gate addon, approval data layer,
decision API, chat-stream announce path).

## Scope

Bring the existing K8s sandbox-egress proxy + action-approval gate to
self-hosted docker-compose deployments (`SANDBOX_BACKEND=docker`).

The proxy core (`backend/onyx/sandbox_proxy/`), gate addon, action
matcher, approval data layer, decision API, chat-stream announce path,
and frontend wiring are **all unchanged**. This phase is exclusively
the docker-compose infrastructure delta:

- A backend dispatch in `server.py` that selects docker stores instead
  of K8s ones when `SANDBOX_BACKEND=docker`.
- A file-based `CAStore` over a shared compose-named volume.
- A docker-events-driven `SandboxIPLookup` watching sandbox containers.
- `DockerSandboxManager` changes to install the firewall init, mount
  the CA bundle, set `HTTPS_PROXY` + SDK CA env vars, and register the
  opencode session-tag plugin (currently K8s-only).
- A capability-bounding step in `firewall-init.sh`'s `entrypoint` mode
  so the agent process does not retain `CAP_NET_ADMIN` after init.
- A `sandbox-proxy` service in `docker-compose.craft.yml`.

Local sandbox backend (`SANDBOX_BACKEND=local`) is out of scope and
already removed in `configs.py::_parse_sandbox_backend`.

## Goal

After this phase ships, a docker-compose deployment with `--include-craft`
gets the same approval gating behavior as a Helm-deployed K8s cluster:

- All sandbox HTTPS egress routes through `sandbox-proxy:8080`.
- HTTPS is MITM'd using an auto-generated CA distributed via a shared
  named volume.
- The proxy resolves source-IP -> sandbox container by labels, then
  user + tenant by DB lookup, then session by the `Proxy-Authorization`
  tag the opencode plugin emits.
- Gated requests park on the same Redis wake channel, surface in the
  same chat UI, write the same `action_approval` rows, and forward or
  reject on the same APPROVED/REJECTED/EXPIRED logic.

## What is reused vs. what is new

**Reused unchanged.** The bulk of Phases 1 and 2 has nothing K8s-specific
in it:

- `backend/onyx/sandbox_proxy/addons/gate.py`
- `backend/onyx/sandbox_proxy/identity.py` (the Protocol + resolver)
- `backend/onyx/sandbox_proxy/ca.py` (the Protocol + bootstrap)
- `backend/onyx/sandbox_proxy/approval_cache.py`
- `backend/onyx/sandbox_proxy/action_matcher.py`
- `backend/onyx/server/features/build/db/action_approval.py`
- `backend/onyx/server/features/build/approvals/api.py`
- `backend/onyx/server/features/build/session/manager.py::_merge_acp_with_announces`
- `backend/onyx/server/features/build/sandbox/image/firewall-init.sh`
  (the `entrypoint` mode is already plumbed)
- `backend/onyx/server/features/build/sandbox/image/opencode-plugins/session-proxy-tag.ts`
- Frontend: `web/src/app/craft/hooks/useBuildStreaming.ts`,
  `parsePacket.ts`, `packetTypes.ts`, SWR keys.

**New.** Strictly the backend implementations of the Phase 1
interfaces plus the docker-side sandbox provisioning changes:

```
backend/onyx/sandbox_proxy/
+-- ca_docker.py                    # FileCAStore over a named volume
+-- identity_docker.py              # DockerEventsLookup over docker events
+-- backend.py                      # SANDBOX_BACKEND-driven dispatch helpers

backend/onyx/server/features/build/sandbox/docker/
+-- docker_sandbox_manager.py       # MODIFIED: proxy plumbing, security ctx, command

backend/onyx/server/features/build/sandbox/image/
+-- firewall-init.sh                # MODIFIED: drop CAP_NET_ADMIN before exec
+-- Dockerfile                      # MODIFIED: install libcap2-bin

deployment/docker_compose/
+-- docker-compose.craft.yml        # MODIFIED: add sandbox-proxy service + ca volume

backend/onyx/sandbox_proxy/server.py # MODIFIED: backend dispatch
backend/onyx/server/features/build/configs.py # MODIFIED: SANDBOX_PROXY_CA_VOLUME_PATH
backend/onyx/server/features/build/sandbox/util/opencode_config.py # MODIFIED: plugins= on single-provider config
```

No new DB tables. No new API endpoints. No new constants
in `approval_cache.py`. The whole feature surface is steady.

## Phase 1 / Phase 2 context relevant to this phase

- `CAStore` Protocol (`ca.py`) specifies `load` and `persist`, with
  `persist` raising `CAStoreConflictError` on a lost cold-start race.
  `K8sSecretCAStore` realises this via conditional create on a Secret;
  the docker impl realises it via `O_EXCL` on a file.
- `SandboxIPLookup` Protocol (`identity.py`) specifies `start`,
  `lookup`, `wait_for_initial_sync`, `is_synced`, `stop`. The K8s impl
  is informer-backed; the docker impl is `DockerClient.events()`-backed.
- `firewall-init.sh` already dispatches on `SANDBOX_PROXY_BOOTSTRAP_MODE`
  with `initcontainer` and `entrypoint` modes; only `entrypoint` runs
  in compose. The script ends in `exec gosu 1000:1000 "$@"` today --
  Task T5.5 changes that to bound capabilities.
- The K8s sandbox manager applies `_proxy_main_container_env_vars()`
  (HTTPS_PROXY + SDK CA env vars) and `_proxy_init_container()`
  (the firewall init) gated on `SANDBOX_PROXY_HOST`. The docker
  manager does neither today.
- `build_container_create_kwargs` in `docker_sandbox_manager.py`
  defines a fixed env allowlist that is **enforced by
  `tests/unit/onyx/server/features/build/sandbox/test_docker_manager_config.py`**.
  Widening it (necessary in this phase) requires updating that test
  alongside the code.

## Tasks

### T5.1 -- Backend dispatch in `sandbox_proxy/server.py`

Today `server.py` imports `K8sSecretCAStore` and `K8sInformerLookup`
directly at module level. Replace those with dispatch helpers in a new
module `backend/onyx/sandbox_proxy/backend.py`:

```python
from onyx.sandbox_proxy.ca import CAStore
from onyx.sandbox_proxy.identity import SandboxIPLookup
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend


def build_ca_store() -> CAStore:
    if SANDBOX_BACKEND is SandboxBackend.KUBERNETES:
        from onyx.sandbox_proxy.ca_k8s import K8sSecretCAStore
        return K8sSecretCAStore()
    if SANDBOX_BACKEND is SandboxBackend.DOCKER:
        from onyx.sandbox_proxy.ca_docker import FileCAStore
        return FileCAStore()
    raise RuntimeError(f"unsupported SANDBOX_BACKEND={SANDBOX_BACKEND!r}")


def build_ip_lookup() -> SandboxIPLookup:
    if SANDBOX_BACKEND is SandboxBackend.KUBERNETES:
        from onyx.sandbox_proxy.identity_k8s import K8sInformerLookup
        return K8sInformerLookup()
    if SANDBOX_BACKEND is SandboxBackend.DOCKER:
        from onyx.sandbox_proxy.identity_docker import DockerEventsLookup
        return DockerEventsLookup()
    raise RuntimeError(f"unsupported SANDBOX_BACKEND={SANDBOX_BACKEND!r}")
```

`server.py::main` calls `build_ca_store()` and `build_ip_lookup()`
instead of the direct constructors. `_bootstrap_ca` and `_build_lookup`
collapse into the dispatch calls. The signal handler, healthz server,
DumpMaster setup, drain logic, and identity factory are unchanged.

Lazy imports keep the K8s `kubernetes` client out of the docker
process's import graph and vice-versa (`kubernetes` is large and the
SDK opens config files at import time on some paths).

### T5.2 -- File-based `CAStore` for compose (`ca_docker.py`)

A shared named compose volume is the "source of truth" analogue of the
K8s Secret. Both the proxy and every sandbox container mount it; the
proxy at read-write so it can persist on cold start, sandboxes at
read-only so the `firewall-init.sh` can read `ca.crt` and install it
into the trust store.

```python
class FileCAStore(CAStore):
    """File-backed CA persistence over a shared compose volume.

    Layout on disk:
        $SANDBOX_PROXY_CA_VOLUME_PATH/
            ca.crt   # public cert; mounted into sandboxes
            ca.key   # private key; readable only by the proxy

    Cold-start race: `O_EXCL` create on `ca.crt` ensures exactly one
    writer wins. The loser sees EEXIST and re-loads -- the same
    semantics K8s gets from `409 Conflict` on conditional Secret
    create.
    """

    _CA_CERT_FILENAME = "ca.crt"
    _CA_KEY_FILENAME = "ca.key"

    def __init__(self, root: str | Path = SANDBOX_PROXY_CA_VOLUME_PATH) -> None: ...

    def load(self) -> tuple[bytes, bytes] | None: ...

    def persist(self, cert_pem: bytes, key_pem: bytes) -> None:
        """Atomic write: O_EXCL on cert first; on success write key next
        to it with 0o600. On EEXIST raise CAStoreConflictError so
        CABootstrap re-load()s the winner's CA."""
```

Implementation specifics:

- Persist order: cert first (the rendezvous file), key second. A
  crash between the two on a cold cluster leaves the cert without a
  key; the next boot fails loud with a clear error rather than
  silently regenerating (which would invalidate already-installed
  trust stores). Operator recovery is: delete `ca.crt`, restart proxy.
- `ca.key` is mode `0o600`; `ca.crt` is mode `0o644`.
- The mount volume is owned by root inside the proxy container; the
  proxy process runs as root inside its container (no security cost,
  it's a single-purpose container).
- The K8s store re-projects its ConfigMap on every `load()` so a
  deleted ConfigMap self-heals. The docker store has no analogue --
  the file IS the bundle, sandboxes mount the same volume directly.

Config:

```python
# configs.py
SANDBOX_PROXY_CA_VOLUME_PATH = os.environ.get(
    "SANDBOX_PROXY_CA_VOLUME_PATH", "/var/lib/sandbox-proxy/ca"
)
```

### T5.3 -- Docker-events-driven `SandboxIPLookup` (`identity_docker.py`)

The K8s informer maintains `{pod_ip: SandboxIdentity}` by watching pods
with the sandbox label selector. The docker analogue maintains
`{container_ip: SandboxIdentity}` by:

1. Initial sync: `client.containers.list(filters={"label":
   f"{LABEL_COMPONENT}={LABEL_COMPONENT_VALUE}"})` -- inspect each,
   pull labels (`onyx.app/sandbox-id`, `onyx.app/tenant-id`), pull IP
   from `NetworkSettings.Networks[<network>].IPAddress`. The network
   name is `SANDBOX_DOCKER_NETWORK`.
2. Background thread: `client.events(filters={"type": "container",
   "label": f"{LABEL_COMPONENT}={LABEL_COMPONENT_VALUE}"})` -- on
   `start` events, inspect and upsert; on `die`/`destroy`, evict by
   container id.

```python
class DockerEventsLookup(SandboxIPLookup):
    def __init__(
        self,
        docker_client: DockerClient | None = None,
        network: str = SANDBOX_DOCKER_NETWORK,
    ) -> None: ...

    def start(self) -> None: ...
    def lookup(self, src_ip: str) -> SandboxIdentity | None: ...
    def wait_for_initial_sync(self, timeout_seconds: float) -> bool: ...
    def is_synced(self) -> bool: ...
    def stop(self) -> None: ...
```

Implementation specifics:

- Mirror K8s "duplicate IP = fail loud": if two sandbox containers ever
  report the same IP on the sandbox network the initial sync raises,
  not warns. Exists because routing traffic with ambiguous identity is
  strictly worse than refusing to serve.
- Exclude the proxy's own container from the cache. The proxy has
  `LABEL_COMPONENT=sandbox-proxy` (distinct from
  `LABEL_COMPONENT_VALUE=craft-sandbox`), so the label filter already
  handles this -- belt and braces, double-check via assertion in
  `_identity_from_container`.
- Reconnect loop matches K8s: catch `docker.errors.APIError`,
  `requests.exceptions.ConnectionError`, generic `OSError`; backoff
  starts at 1s, caps at 30s. `_synced` clears on disconnect so
  `/healthz` flips to 503, matching K8s semantics.
- The docker socket access is the same trust boundary that
  `docker_sandbox_manager.py` already documents at the top of the
  module. No new trust elevation in this phase.
- `tenant_id` is read from the container label (set by
  `build_container_create_kwargs`), not from any DB lookup -- identical
  to the K8s path.

### T5.4 -- `DockerSandboxManager` proxy plumbing

The K8s manager has three pieces of proxy plumbing the docker manager
needs:

1. **`_proxy_main_container_env_vars()` equivalent.** Inject
   `HTTPS_PROXY`/`HTTP_PROXY` (lowercase + uppercase), `NO_PROXY`, and
   the SDK CA env vars: `NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`,
   `SSL_CERT_FILE`, `AWS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `GIT_SSL_CAINFO`.
   `SANDBOX_PROXY_HOST` is the compose service name `sandbox-proxy`
   (Docker's embedded DNS resolves it -- no `/etc/hosts` injection
   needed, unlike K8s).
2. **Bootstrap command swap.** Today
   `command=["/workspace/entrypoint.sh"]`. With the proxy enabled this
   becomes `command=["/workspace/firewall-init.sh",
   "/workspace/entrypoint.sh"]` with
   `SANDBOX_PROXY_BOOTSTRAP_MODE=entrypoint`. The script execs the
   second argument after setting up iptables + CA.
3. **Mounts.** The CA volume mounts read-only at the path
   `firewall-init.sh` reads from (`/sandbox-ca/ca.crt` by default,
   overridable via `SANDBOX_PROXY_CA_BUNDLE_SRC`). The materialised
   bundle output (`/etc/ssl/sandbox/ca-bundle.crt` by default) lives in
   the container's writable layer -- no shared volume needed, only one
   process reads it.

The big change is the env allowlist. Today
`build_container_create_kwargs` enforces a four-key allowlist that
`test_docker_manager_config.py` locks down. It must be widened to:

```python
env = {
    "ONYX_PAT": onyx_pat,
    "ONYX_SERVER_URL": api_server_url,
    OPENCODE_SERVER_PASSWORD: opencode_password,
    "OPENCODE_CONFIG_CONTENT": opencode_config_json,
}
if sandbox_proxy_host:
    env |= _proxy_env_vars(sandbox_proxy_host, sandbox_proxy_port,
                           api_server_url)
```

`_proxy_env_vars` lives in `docker_sandbox_manager.py` next to the
existing security-invariant code (it does not belong in the K8s
manager). The proxy-disabled posture (no `SANDBOX_PROXY_HOST`) keeps
the original 4-key allowlist intact for dev / tests that run without
the proxy.

`test_docker_manager_config.py` gets two new cases: with proxy
configured, the resulting env contains the expected proxy + CA keys
and nothing else; without proxy configured, the env is exactly the
four legacy keys.

Security context changes:

- `cap_add=["NET_ADMIN", "SETPCAP", "SETUID", "SETGID"]` only when
  proxy is enabled. `NET_ADMIN` runs `iptables`; `SETPCAP` authorises
  the `PR_CAPBSET_DROP` syscall that `setpriv --bounding-set=-all`
  uses to clear the bounding set; `SETUID`/`SETGID` gate `setpriv`'s
  `--reuid` / `--regid` / `--init-groups` calls (under `cap_drop=ALL`
  even root needs them). All four are dropped from the bounding set
  by setpriv before the agent execve, so the running container ends
  up with no caps at all. With proxy disabled, `cap_drop=ALL` stays
  in effect with no additions.

  Originally specced as just `NET_ADMIN` + `SETPCAP`; the smoke pass
  discovered that capsh/setpriv's user-switch needs SETUID + SETGID
  in the effective set even when invoked as UID 0, because
  cap_drop=ALL strips them from the inherited set Docker would
  otherwise grant. The bounding set still drops to empty before
  agent exec.
- `user` is dropped from the create kwargs when proxy is enabled. The
  container starts as root (uid 0) so `firewall-init.sh` can run
  iptables; the script's final `exec` drops to UID 1000 (see T5.5 for
  the capability-bounding wrinkle). With proxy disabled, the legacy
  `user="1000:1000"` stays.

The proxy-enabled / proxy-disabled split is gated on a single
`SANDBOX_PROXY_HOST` truthiness check, mirroring the K8s manager.
A dev who explicitly unsets `SANDBOX_PROXY_HOST` gets the pre-gate
posture, which matters for the existing test surface that runs without
the proxy stack up.

### T5.5 -- Capability bounding in `firewall-init.sh` (`entrypoint` mode)

Today the script ends in:

```bash
exec gosu 1000:1000 "$@"
```

`gosu` calls `setuid(1000)` then `execve()`. The kernel's `execve`
transition rules with no file capabilities (`fileP=0`, `fileI=0`)
compute the new process's Permitted set as zero, so in practice the
agent process runs with no caps in Effective/Permitted. **But the
Bounding set still contains `CAP_NET_ADMIN`.** This is a ceiling, not
an active grant -- the agent cannot run iptables -- but it represents
a weaker security argument than the K8s init-container model (where
`NET_ADMIN` is granted only to the init container's security context,
not to the running sandbox container at all).

Change the script's tail to explicitly clear the Bounding set before
exec, using `setpriv` from `util-linux`:

```bash
exec setpriv --reuid=1000 --regid=1000 --init-groups \
    --bounding-set=-all -- "$@"
```

(`util-linux` ships in the `node:20-slim` base, so no Dockerfile
dependency change is needed.) `setpriv` drops every capability from
the bounding set, switches UID/GID to 1000:1000 with the right
supplementary groups, then `execve`'s the target. The subsequent
execve has no file capabilities, so the agent process ends up with
zero caps in any set. After this:

- A process inside the running sandbox cannot acquire `NET_ADMIN` even
  if a setuid-NET_ADMIN binary somehow ended up in its filesystem.
- The egress lockdown is enforced by kernel netfilter state on the
  container's network namespace, which the agent cannot modify.
- The security argument matches the K8s posture: "the capability
  existed for the few hundred milliseconds of init, never since."

The K8s init path is unaffected: `initcontainer` mode exits before
the privilege-drop section.

**Why setpriv, not capsh.** Originally specced as `capsh --drop=all
--user=sandbox -- "$@"`. Smoke discovered that `capsh -- args`
actually invokes `/bin/bash` and treats the rest as
`script script-args` -- which works for the prod case (the entrypoint
IS a script) but silently breaks for any binary target and made the
local-dev smoke fail with "cannot execute binary file" on
non-script stand-ins. `setpriv`'s `--` directly `execve`'s the
target with no shell wrapper. Same security posture, cleaner
semantics, no extra package dependency.

### T5.5b -- mitmproxy confdir path

`server.py` originally hard-coded `/var/run/sandbox-proxy/mitmproxy-confdir`.
Make it env-tunable so local-dev runs (proxy under the user's venv,
no root) can point at `/tmp`:

```python
_MITM_CONFDIR = os.environ.get(
    "SANDBOX_PROXY_MITM_CONFDIR",
    "/var/run/sandbox-proxy/mitmproxy-confdir",
)
```

`_bootstrap_ca` passes `pem_path=f"{_MITM_CONFDIR}/mitmproxy-ca.pem"`
explicitly to `CABootstrap` so the CA-bootstrap path tracks the
confdir override. The default is unchanged for prod (K8s pods run
the proxy as root with the tmpfs-mounted `/var/run` location).

### T5.6 -- Single-provider opencode config with plugin support

The K8s path uses `build_multi_provider_opencode_config(..., plugins=
[_OPENCODE_SESSION_TAG_PLUGIN_PATH])` to register the session-tag
plugin. The docker path uses `build_opencode_config(...)` which does
not currently accept a `plugins` argument. Extend the single-provider
builder to accept `plugins: list[str] | None` and emit the same
`plugin` field opencode expects.

The docker manager mirrors the K8s gating ("only register when proxy
is deployed; otherwise it would no-op"):

```python
session_tag_plugins = (
    [_OPENCODE_SESSION_TAG_PLUGIN_PATH] if sandbox_proxy_host else None
)
opencode_config_json = json.dumps(
    build_opencode_config(
        provider=...,
        plugins=session_tag_plugins,
    )
)
```

`_OPENCODE_SESSION_TAG_PLUGIN_PATH` is a module-level constant in
`docker_sandbox_manager.py` matching the path the K8s manager uses
(`/workspace/opencode-plugins/session-proxy-tag.ts`). The plugin file
is already baked into the sandbox image and shared with K8s -- the path
exists today on the docker sandbox image too.

`tests/unit/onyx/server/features/build/sandbox/test_opencode_config.py`
gets a case verifying the docker single-provider builder emits the
plugin path when supplied.

### T5.7 -- `sandbox-proxy` compose service

Add to `deployment/docker_compose/docker-compose.craft.yml`:

```yaml
sandbox-proxy:
  image: ${ONYX_BACKEND_IMAGE:-onyxdotapp/backend:latest}
  command: ["python", "-m", "onyx.sandbox_proxy.server"]
  environment:
    - SANDBOX_BACKEND=docker
    - SANDBOX_PROXY_CA_VOLUME_PATH=/var/lib/sandbox-proxy/ca
    - SANDBOX_DOCKER_NETWORK=${SANDBOX_DOCKER_NETWORK:-onyx_craft_sandbox}
    # DB + Redis credentials (mirrors api_server's env)
    - POSTGRES_HOST=relational_db
    - POSTGRES_USER=${POSTGRES_USER:-postgres}
    - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
    - POSTGRES_DB=${POSTGRES_DB:-postgres}
    - REDIS_HOST=cache
    # Listen port matches default; healthz on 8081
  volumes:
    - sandbox_proxy_ca:/var/lib/sandbox-proxy/ca
    - ${SANDBOX_DOCKER_SOCKET:-/var/run/docker.sock}:/var/run/docker.sock:ro
  networks:
    - default              # reach relational_db, cache
    - onyx_craft_sandbox   # be reachable from sandboxes by name
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "wget", "-q", "-O-", "http://localhost:8081/healthz"]
    interval: 10s
    timeout: 3s
    retries: 3

api_server:
  environment:
    - SANDBOX_PROXY_HOST=sandbox-proxy
    - SANDBOX_PROXY_PORT=8080
    # (existing env unchanged)

background:
  environment:
    - SANDBOX_PROXY_HOST=sandbox-proxy
    - SANDBOX_PROXY_PORT=8080

volumes:
  sandbox_proxy_ca:
```

Notes:

- The proxy joins `default` (to reach postgres + redis by compose-DNS)
  and `onyx_craft_sandbox` (to be reachable from sandboxes by the name
  `sandbox-proxy`). Docker DNS resolves the service name to whichever
  interface IP is on the network the resolver runs on.
- Docker socket mount is read-only -- the proxy only inspects, it does
  not create or modify containers. The trust boundary is the same one
  `api_server` already crosses (mounted RW) for `docker exec`-driven
  sandbox control.
- No `replicas: 2`. Compose deployments are single-host; horizontal
  scaling of the proxy is a multi-host story we are not signing up for
  in this phase. The risk is documented in `approvals-plan.md` already.
- `install.sh --include-craft` already creates the
  `onyx_craft_sandbox` network and treats it as `external: true`. No
  install-flow change needed.
- The healthcheck consumes `/healthz` which the proxy already serves
  (Phase 1). Compose's healthcheck flips the container's health status
  to `unhealthy` on consecutive failures. Note: `restart:
  unless-stopped` does NOT auto-recover unhealthy containers --
  Docker only restarts on process exit, not on healthcheck failure
  (Swarm's `deploy.restart_policy` and third-party watchdogs like
  `autoheal` are the mechanisms that do). The `_run` loop's
  reconnect-with-backoff covers the common transient failures
  (daemon hiccup, stream EOF) and `/healthz` flips back to 200
  without intervention; truly stuck-unhealthy states would require
  an operator-initiated restart. Acceptable for the single-replica
  MVP; a self-crash on detected unrecoverable state is a Phase 6+
  follow-up if we see this in practice.

### T5.8 -- Sandbox image dependencies

No new packages needed. `setpriv` ships in `util-linux` which is in
the `node:20-slim` base image. The Dockerfile already installs
`iptables` (egress lockdown) and `ca-certificates` (trust-store
population); both are required regardless of backend. `gosu` is
retained for compatibility with any external tooling that still
expects it.

Originally specced to add `libcap2-bin` for `capsh`; dropped after
the smoke pass switched to `setpriv` (T5.5's "Why setpriv" note).

### T5.9 -- Operational posture

Compose deltas from the K8s posture:

- **Single replica.** A crash drops in-flight flows and briefly
  refuses new connections until `restart: unless-stopped` brings the
  proxy back. The risk is documented in `approvals-plan.md` § Risks.
  No HA story for compose.
- **Graceful drain.** SIGTERM handling in `server.py` is unchanged.
  Compose sends SIGTERM on `docker stop` with a configurable timeout
  (default 10s -- matches `_DRAIN_TIMEOUT_S` exactly, but worth
  setting `stop_grace_period: 20s` on the service to give the drain
  the same outer window K8s uses).
- **Cross-host.** Out of scope. Single-host compose is the supported
  shape for self-hosted Craft today.
- **Image build.** No new image: the proxy reuses the existing
  `onyxdotapp/backend` image. CI does not gain a sandbox-proxy build
  step.
- **Capacity.** The proxy's DB pool is `pool_size=4, max_overflow=4`
  (set in `server.py`). For single-host compose with a handful of
  active sandboxes this is comfortable. Promote to env-tunable if a
  real ops need surfaces.

## Testing

Test-tier conventions per CLAUDE.md. `WAIT_TIMEOUT_S` is
monkey-patched to <1s in tests where wall-clock waits would otherwise
poison CI.

**Unit** (`backend/tests/unit/sandbox_proxy/`):

- `test_backend_dispatch.py` -- `build_ca_store()` and
  `build_ip_lookup()` return the right type for each
  `SANDBOX_BACKEND` value; raise on unknown.
- `test_ca_docker.py` -- file persistence happy path; `O_EXCL`
  conflict path raises `CAStoreConflictError`; missing `ca.key`
  after a cold-cluster crash raises with a clear message rather
  than silently regenerating.
- `test_identity_docker.py` -- container labels parse correctly
  into `SandboxIdentity`; duplicate IPs on initial sync raise;
  reconnect-after-error path resets `_synced`.
- `test_docker_manager_config.py` -- existing test gains two cases:
  (a) with `SANDBOX_PROXY_HOST` set, env contains the expected proxy
  + CA keys and the security context has `NET_ADMIN`; (b) without
  `SANDBOX_PROXY_HOST` set, the env is exactly the legacy 4-key
  allowlist and `cap_drop=ALL` stands alone.
- `test_opencode_config.py` -- single-provider builder emits the
  plugin path when supplied.

**External-dependency unit**
(`backend/tests/external_dependency_unit/sandbox_proxy/`):

- `test_identity_docker_resolver.py` -- spin up real sandbox-labelled
  containers via `docker run`, assert `lookup` finds them, evicts on
  removal. Skip if `/var/run/docker.sock` is absent.

**Integration** (CI lane mirroring `pr-craft-k8s-tests.yml`): a new
`pr-craft-compose-tests.yml` lane stands up the docker-compose stack
with the `--include-craft` overlay, provisions a sandbox, triggers a
gated Slack request via a stand-in matcher, POSTs APPROVE via the
decision API, and asserts the upstream forward happened. The whole
test reuses `test_approval_gate.py`'s end-to-end shape -- the gate
logic is identical, only the infrastructure underneath differs.

**Smoke** (runbook, not automated): on a fresh compose deployment with
`--include-craft`, provision a sandbox, run `curl https://example.com`
from inside it and confirm the chain shows the proxy CA;
`curl --noproxy '*' https://example.com` fails (iptables denies);
`nslookup example.com` fails (DNS is closed); `curl -6 ...` fails
(IPv6 dropped); a real Slack send through the gate triggers an
approval card in the chat UI.

## Dependencies

- Phases 1 and 2 merged.
- A working docker-compose deployment with `--include-craft`
  (i.e. the `onyx_craft_sandbox` external network created and the
  Docker socket mounted into api_server / background).
- `cache` and `relational_db` reachable from the proxy on the `default`
  compose network. Already true.
- Sandbox image rebuilt with `libcap2-bin` (T5.8).

## Open during phase

- Whether to enforce single-replica via compose's `deploy.replicas: 1`
  or rely on the absence of a `deploy:` section. Cosmetic; pick one
  and document it.
- Whether `stop_grace_period: 20s` should also be backported onto
  api_server / background to give their celery beat workers a similar
  drain window (out of scope for this phase, but worth noting if
  the answer is "yes we should").
- Whether the proxy needs its own image build for a smaller surface,
  or whether the backend-image reuse stays. Reuse is the v0 answer
  (matches K8s); revisit if image pull time becomes a deployment
  concern.

## Definition of done

- A fresh docker-compose deployment with `--include-craft` brings up a
  `sandbox-proxy` service alongside the existing api_server /
  background / postgres / redis / minio / web_server.
- Sandbox containers provisioned by `DockerSandboxManager` run
  `firewall-init.sh` as their entrypoint, install the proxy CA into
  the trust store, lock down egress via iptables, self-verify the
  lockdown, drop to UID 1000 with **no capabilities in the bounding
  set**, and start the agent.
- `curl https://api.slack.com/...` from inside a sandbox succeeds, is
  MITM'd with a leaf cert signed by the proxy CA, and the proxy logs
  the flow with a resolved `SessionContext`.
- `curl https://example.com --noproxy '*'` from inside a sandbox fails
  (iptables denies). `nslookup example.com` fails. `curl -6` fails.
- Killing the sandbox container evicts the cache entry; a new sandbox
  container's IP is resolved on the next request without restarting
  the proxy.
- A gated Slack request triggers an `action_approval` row, an
  announce on `approval:announce:{session_id}`, an
  `ApprovalRequestedPacket` on the open chat SSE, and routes APPROVED
  forwards / REJECTED 403s identically to the K8s integration test.
- SIGTERM drain on the proxy terminalises in-flight approvals and
  exits within the compose `stop_grace_period`.
- `test_docker_manager_config.py` allowlist invariants hold for both
  proxy-enabled and proxy-disabled postures.
- The new compose CI lane is green.

## Risks

- **Capability bounding regression.** If `setpriv` is removed from
  the image (e.g. switching to a `-distroless` base that strips
  `util-linux`), the script's `setpriv` line fails and
  `firewall-init.sh` exits non-zero, taking the sandbox down at
  startup. This is the safe failure mode -- noisy, not silent. The
  earlier alternative ("just `gosu`, trust the kernel to drop caps
  on `execve`") is the unsafe failure mode: silently runs with
  `NET_ADMIN` in the bounding set and rests on kernel-transition
  subtleties for safety. Stick with `setpriv`.
- **Docker socket privilege.** The proxy mounts the docker socket
  (read-only) to drive its events watcher. This adds a second
  consumer of the socket trust boundary that `api_server` already
  crosses. Containers with socket access are root-equivalent on the
  host even with RO mode (RO blocks writes, not info disclosure that
  could enable lateral movement -- but the events API itself is the
  intended surface here). Documented as part of the existing trust
  posture; no new boundary.
- **Single-replica blast radius.** A proxy crash drops all in-flight
  flows on this host and refuses new connections until `restart:
  unless-stopped` brings it back. For compose this is acceptable;
  the K8s two-replica posture is the upgrade path if a self-hosted
  deployment ever needs higher availability.
- **Compose project DNS scope.** The `sandbox-proxy` name is
  resolvable only inside the `onyx_craft_sandbox` network. If a
  deployer ever runs multiple compose stacks side-by-side with
  different project names, the external network sharing requires
  care -- `external: true` keeps them on the same bridge by
  construction. Documented in `docker-compose.craft.yml`.
- **CA bundle on host filesystem.** The shared volume backing the CA
  store is a docker named volume on the host. The private key is
  mode-0600 inside the volume, but anyone with root on the host (or
  read access to the docker volumes path) can read it. This is the
  same trust posture as the K8s Secret (whoever has cluster admin
  reads the Secret); the docker analogue is "whoever has host root
  reads the volume." Documented; no mitigation in v0.

## Future work

- **CA rotation.** Both K8s and compose stores load-or-generate today.
  A real rotation flow (generate new, dual-publish, wait for sandboxes
  to pick up, retire old) is a future workstream and lands once we have
  a customer driver.
- **Multi-host compose proxy HA.** Out of scope. A swarm-mode or
  external-LB story is the right approach if it becomes necessary.
- **Removing gosu from the image.** Now that the compose entrypoint
  uses `setpriv` (in util-linux, always present), `gosu` is only
  retained for tooling compatibility. A follow-up image cleanup could
  drop it.
