# Phase 5 — Docker-compose backend support (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Reference: [phase-1-proxy.md](./phase-1-proxy.md) for the K8s baseline
this phase mirrors.
Depends on Phase 1 (proxy core, gate addon, service, identity-resolver
interface). Phases 2–4 are backend-agnostic and apply to docker
unchanged once Phase 5 lands.

## Goal

Run the egress proxy against the docker-compose sandbox backend
(`SANDBOX_BACKEND=docker`) with the **same fail-closed posture** as the
K8s deployment. The proxy core, Approval Service, chat UI, and policy
layer are unchanged — this phase is exclusively the infrastructure
delta: how iptables get installed inside a docker sandbox, how
identity resolves, how the CA is distributed, and how the proxy ships
in the compose stack.

The pattern matches agent-vault's docker container mode: container
starts as root with `CAP_NET_ADMIN`, an entrypoint wrapper installs
the firewall, then drops to UID 1000 via `gosu` before `exec`-ing
the real entrypoint. After the UID transition the process's
permitted/effective capability sets are cleared (Linux default on
UID change), so the agent's process runs without `NET_ADMIN`.
`no-new-privileges` stays on the container: it blocks privilege gain
via `execve` of setuid/file-cap binaries, but does **not** block a
root process calling `setuid()` directly, which is what gosu does.
The iptables rules installed in step 1 persist in the container's
network namespace for the container's lifetime regardless of which
UID the agent runs as.

## Module layout

```
backend/onyx/sandbox_proxy/
├── identity_docker.py           # new: DockerEventsLookup (impls SandboxIPLookup)
├── ca_docker.py                 # new: VolumeCAStore (impls CAStore)
├── config.py                    # +"docker" branch in backend dispatch
└── scripts/
    └── firewall-init.sh         # Phase 1; Phase 5 adds the `entrypoint`
                                 # mode branch (gosu drop + exec real entrypoint;
                                 # /etc/hosts step skipped)

backend/onyx/server/features/build/sandbox/docker/
└── docker_sandbox_manager.py    # drop user="1000:1000", add cap_add[NET_ADMIN],
                                 # expand env allowlist, mount CA volume,
                                 # add ContainerCreateKwargs.cap_add field

backend/tests/external_dependency_unit/server/features/build/sandbox/
└── test_docker_manager_config.py  # update locked-down assertions
                                   # for the new caps + env allowlist

deployment/docker_compose/
└── docker-compose.craft.yml     # +sandbox-proxy service, +onyx-craft-ca volume
```

## Tasks

### T5.1 — Sandbox image: `entrypoint` mode

Phase 1 lands `firewall-init.sh` and the two-mode env-var switch (see
[Phase 1 T1.3](./phase-1-proxy.md#t13--sandbox-bootstrap-initcontainer)
for the mode table). Phase 5 only adds the **`entrypoint` mode branch**:

- Skip step 3 (the `/etc/hosts` write — docker-compose service DNS
  resolves `sandbox-proxy` on the bridge without it).
- After step 4 (self-verify), `exec gosu 1000:1000 <real-entrypoint>`
  instead of `exit 0`.

Image changes for docker:

- Install `gosu` in the sandbox image build (Phase 1 already added
  `iptables`).
- The image's docker-mode entrypoint is `firewall-init.sh`; the real
  entrypoint is invoked via `gosu` from inside the script.

### T5.2 — Docker sandbox manager changes

`docker_sandbox_manager.py` modifications:

- **Drop `user="1000:1000"`** from `ContainerCreateKwargs`. The
  container must start as root so `firewall-init.sh` can install
  iptables; gosu then drops to UID 1000 before exec'ing the agent.
  Without this change the entrypoint runs as 1000 and the firewall
  install fails.
- **`cap_add=["NET_ADMIN"]`** on the sandbox container (alongside the
  existing `cap_drop=["ALL"]` — Docker applies `cap_add` after
  `cap_drop`, so the net effect is `NET_ADMIN`-only at startup). Add
  `cap_add` as a new field on `ContainerCreateKwargs` (the TypedDict
  doesn't have it today).
- **`security_opt=["no-new-privileges:true"]` stays** — see the
  Goal section for why gosu doesn't conflict.
- **Env allowlist expansion** (currently `ONYX_PAT` + `ONYX_SERVER_URL`
  only): add the agent-runtime vars `HTTPS_PROXY`, `HTTP_PROXY`,
  `NO_PROXY`, `NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`,
  `SSL_CERT_FILE`, `AWS_CA_BUNDLE`, `CURL_CA_BUNDLE`,
  `GIT_SSL_CAINFO`. The bootstrap-only vars (`SANDBOX_PROXY_HOST`,
  `SANDBOX_PROXY_PORT`, `SANDBOX_PROXY_BOOTSTRAP_MODE`) are read by
  `firewall-init.sh` before the gosu drop and could either stay in
  the agent's env (harmless) or be `unset` at the bottom of the
  script before exec — pick the latter to keep the agent's runtime
  env minimal.
- **CA volume mount**: read-only mount of the `onyx-craft-ca` named
  volume into `/etc/onyx/ca/` so the entrypoint can populate
  `/usr/local/share/ca-certificates/sandbox-proxy.crt` and run
  `update-ca-certificates`.
- **Network**: container still joins only `onyx_craft_sandbox`. The
  proxy joins the same bridge so `sandbox-proxy` resolves by service
  DNS.

`test_docker_manager_config.py` codifies today's locked-down posture
(cap_drop=ALL, no env beyond the two allowed, user 1000:1000). Each
of the changes above needs a matching assertion update in that test.

### T5.3 — `DockerEventsLookup` (implements `SandboxIPLookup`)

`identity_docker.py` adds a docker-events-driven implementation of
the [`SandboxIPLookup`](./phase-1-proxy.md#t14--identity-resolver)
Protocol that Phase 1 lands. The shared `IdentityResolver` consumes
it unchanged; only the IP-to-sandbox lookup differs from K8s.

```python
class DockerEventsLookup:
    """Implements SandboxIPLookup against the Docker Engine API.

    On startup: list containers with label
    `onyx.app/component=craft-sandbox`. For each, read
    `onyx.app/sandbox-id` + `onyx.app/tenant-id` from labels,
    `Name` from the container attrs (sandbox name is NOT a label —
    it's the container's `Name` field), and
    `NetworkSettings.Networks["onyx_craft_sandbox"].IPAddress` for
    the bridge IP. Build src_ip → SandboxIdentity map.

    Then: docker events stream (filtered to container start/die)
    keeps the cache fresh. Reconnect with exponential backoff on
    stream drop. Initial sync must complete before /healthz returns
    200 (T5.7).
    """

    def lookup(self, src_ip: str) -> SandboxIdentity | None: ...
```

### T5.4 — `VolumeCAStore` (implements `CAStore`)

`ca_docker.py` adds a named-volume-backed implementation of the
[`CAStore`](./phase-1-proxy.md#t12--ca-bootstrap) Protocol that
Phase 1 lands. `CABootstrap` orchestration is unchanged.

- Named volume `onyx-craft-ca` is mounted **read-write** into the
  proxy container at `/var/lib/onyx/ca/`, and **read-only** into every
  sandbox container at `/etc/onyx/ca/`.
- `VolumeCAStore.persist` uses `O_CREAT | O_EXCL` so the cold-start
  path is idempotent if (somehow) two proxies race; with the
  single-replica deployment (T5.5) this is belt-and-suspenders.
- The proxy writes to the volume only on cold-start; at steady state
  it's read-only from the proxy's perspective. Sandboxes only read.
- The bootstrap script reads the cert from
  `/etc/onyx/ca/sandbox-proxy.crt` instead of from a ConfigMap mount.

### T5.5 — Proxy delivery via docker-compose

Add a `sandbox-proxy` service to `deployment/docker_compose/docker-compose.craft.yml`:

- Image: the same proxy image built in Phase 1 T1.1.
- Networks: `default` (for Postgres/Redis access — the proxy bundles
  the backend module tree and calls the Approval Service via
  in-process Python imports, so it needs DB/Redis reachability the
  same way api-server does) **and** `onyx_craft_sandbox` (so
  sandboxes reach it by service name). Sandboxes never join
  `default`; existing isolation preserved.
- Volumes: `onyx-craft-ca:/var/lib/onyx/ca/` (read-write); Docker
  socket (`/var/run/docker.sock`) for the identity resolver to query
  the Docker Engine API.
- `restart: unless-stopped` so a crash restarts the proxy
  automatically.
- `SANDBOX_BACKEND=docker` env so the proxy boots the docker
  lookup and CA store.
- **Single instance** — docker-compose has no native equivalent of
  K8s Service load balancing, and the docker-compose target is
  smaller installs. Trade-offs vs the K8s two-replica deploy:
  - A proxy crash drops all in-flight flows with TCP RST.
  - During the restart window, the iptables lockdown means sandboxes
    get `connection refused` on `sandbox-proxy:<port>` until the
    proxy is back. With `restart: unless-stopped` this is typically
    sub-second but the failure mode is real.
  Documented as a known limitation; revisit if docker-compose
  installs grow.

**Docker socket exposure is a real security delta vs K8s.** The
Engine API over the socket is not scope-limited the way K8s RBAC is
(`get,list,watch` on pods in one namespace) — anyone with the
socket can do anything the daemon can do, including launch
privileged containers. A read-only mount of the socket file (`:ro`)
does **not** make the API read-only; it only prevents writing to
the socket inode. Acceptable given the proxy container is built
from our own image and operated as infrastructure, but worth flagging
as a deployment posture choice, not a parity with K8s RBAC.

### T5.6 — Backend selection in proxy

Phase 1's `config.py` reads `SANDBOX_BACKEND` and instantiates the
K8s implementations of `SandboxIPLookup` and `CAStore`. Phase 5 adds
the `docker` branch:

```python
if SANDBOX_BACKEND == "kubernetes":
    ip_lookup = K8sInformerLookup(...)
    ca_store = K8sSecretCAStore(...)
elif SANDBOX_BACKEND == "docker":
    ip_lookup = DockerEventsLookup(...)
    ca_store = VolumeCAStore(...)
else:
    raise ConfigError(f"Unsupported SANDBOX_BACKEND: {SANDBOX_BACKEND}")
```

No silent fallback. `SANDBOX_BACKEND=local` is rejected — the proxy
isn't deployed against the local sandbox backend.

### T5.7 — Operational

- **Healthz** returns 200 once `DockerEventsLookup` has finished its
  initial container list (sync the cache before serving traffic) and
  the CA is loaded — the docker equivalent of Phase 1's "informer
  has synced" condition.
- **Graceful drain** simplified vs K8s: on SIGTERM the proxy stops
  accepting new connections and finishes in-flight flows up to a
  bounded grace period (~200s, matching the Phase 2 wait), then
  exits. There's no rolling-deploy survivor to flip readiness for.

## Testing

- **External-dependency-unit** —
  - `DockerIdentityResolver.resolve()` against a real Docker daemon:
    start a labeled container, verify the resolver returns the
    expected `SessionContext`; stop the container, verify the cache
    evicts.
  - CA volume bootstrap: cold start writes the CA; warm start loads
    it without rewriting.
- **Integration (docker-compose dev stack)** —
  - From inside a sandbox, `curl -v https://example.com` succeeds and
    the chain shows the proxy CA (parallel to Phase 1's K8s test).
  - From inside a sandbox, `curl -v https://example.com --noproxy '*'`
    fails (iptables denies — verifies the entrypoint wrapper installed
    the firewall before the agent ran).
  - Deliberately break `firewall-init.sh` so self-verify exits
    non-zero; verify the sandbox container fails to start with a
    clear error.
  - `nslookup example.com` from inside a sandbox fails — DNS closed.
  - IPv6 egress fails — `ip6tables` lockdown active.
  - Recreate a sandbox container; verify the identity cache evicts on
    the `die` event and the new container's IP resolves on next
    request.
- **Integration (gating end-to-end)** — Phase 2's existing tests
  re-run against `SANDBOX_BACKEND=docker` and pass without
  modification. This is the proof that backend-agnostic gating works.

## Dependencies

- Phase 1 merged.
- Sandbox image build pipeline can take new tooling (`gosu`,
  `iptables`).
- Docker socket exposure to the proxy container is acceptable in the
  deployment (it's the docker-compose equivalent of the proxy's
  K8s API RBAC).

## Open during phase

- Whether the docker-events stream needs surfacing in monitoring /
  dashboards (likely punt; align with Phase 1's metrics-deferred
  posture).

## Definition of done

- `SANDBOX_BACKEND=docker` boots the full stack with the proxy as a
  compose service; sandboxes route HTTPS through the proxy with the
  proxy CA accepted.
- Egress lockdown is fail-closed under docker: a broken
  `firewall-init.sh` causes the sandbox to fail to start (parity with
  the K8s init-container failure mode).
- Inside the agent process, `id` shows `uid=1000` and
  `/proc/self/status` reports empty `CapEff` — verifies the gosu
  drop cleared NET_ADMIN from the running process.
- Identity resolution works against the Docker Engine API; cache
  invalidates on container `die`.
- Phases 2–4 (gating, chat UI, policy) run unmodified against the
  docker backend and pass their existing tests.
- `test_docker_manager_config.py` updated and green for the new
  posture.
