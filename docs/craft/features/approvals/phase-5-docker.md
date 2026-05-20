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
starts with `CAP_NET_ADMIN`, an entrypoint wrapper installs the
firewall as root, then drops to UID 1000 via `gosu` before exec'ing
the real entrypoint. Caps are tied to the process — once UID drops,
NET_ADMIN is gone and the agent runs as restricted as it does today.

## Module layout

```
backend/onyx/sandbox_proxy/
├── identity.py                  # Phase 1; now backend-dispatches
├── identity_docker.py           # new: docker-events-based resolver
├── ca.py                        # Phase 1; K8s Secret persistence
├── ca_docker.py                 # new: shared-volume persistence
├── config.py                    # +SANDBOX_BACKEND awareness
└── scripts/
    └── firewall-init.sh         # new: shared between K8s initContainer
                                 #   and docker entrypoint wrapper
                                 # (lives in the sandbox image build context)

backend/onyx/server/features/build/sandbox/docker/
└── docker_sandbox_manager.py    # cap_add, env allowlist, CA volume

deployment/docker_compose/
└── docker-compose.craft.yml     # +sandbox-proxy service
```

## Tasks

### T5.1 — Sandbox image: entrypoint wrapper + gosu

`firewall-init.sh` is the shared bootstrap script, used by both
backends (K8s runs it as the initContainer command; docker runs it as
the main container's entrypoint, ending in `exec gosu 1000:1000
<real-entrypoint>`). The script's contents are the four steps from
Phase 1 T1.3 — CA trust-store population, iptables egress lockdown,
`/etc/hosts` proxy entry, self-verify — exactly as documented there.

Image changes:

- Install `gosu` (docker only needs this; K8s ignores it).
- Install `iptables` (already required by Phase 1).
- Copy `firewall-init.sh` to `/usr/local/bin/`.
- Set entrypoint to `firewall-init.sh` when running under docker; the
  script's last line `exec gosu 1000:1000 /usr/local/bin/real-entrypoint`.
- Mode is selected via env var `SANDBOX_PROXY_BOOTSTRAP_MODE`
  (`initcontainer` for K8s — script exits 0 after self-verify;
  `entrypoint` for docker — script `exec`s into the real entrypoint).

The script reads the proxy address from env (`SANDBOX_PROXY_HOST`,
`SANDBOX_PROXY_PORT`) — no `/etc/hosts` injection needed for docker
since the proxy is reachable by service name on the
`onyx_craft_sandbox` bridge.

### T5.2 — Docker sandbox manager changes

`docker_sandbox_manager.py` modifications:

- **`cap_add: [NET_ADMIN]`** on the sandbox container (kept alongside
  the existing `cap_drop: ALL` — net effect is NET_ADMIN-only at
  startup; once the entrypoint drops to UID 1000, NET_ADMIN is gone).
- **`security_opt: [no-new-privileges:true]`** stays. It blocks
  setuid escalation; gosu doesn't conflict.
- **Env allowlist expansion** (currently `ONYX_PAT` + `ONYX_SERVER_URL`
  only): add `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`,
  `NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`,
  `AWS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `GIT_SSL_CAINFO`,
  `SANDBOX_PROXY_HOST`, `SANDBOX_PROXY_PORT`,
  `SANDBOX_PROXY_BOOTSTRAP_MODE`.
- **CA volume mount**: read-only mount of the `onyx-craft-ca` named
  volume into `/etc/onyx/ca/` so the entrypoint can populate
  `/usr/local/share/ca-certificates/sandbox-proxy.crt` and run
  `update-ca-certificates`.
- **Network**: container still joins only `onyx_craft_sandbox`. The
  proxy joins the same bridge so `sandbox-proxy` resolves by service
  DNS.

### T5.3 — Docker-events-based identity resolver

`identity_docker.py`:

```python
class DockerIdentityResolver:
    """Same interface as IdentityResolver (Phase 1) but backed by the
    Docker Engine API instead of a K8s informer.

    On startup: list containers with label
    `onyx.app/component=craft-sandbox`, build IP → {sandbox_id,
    tenant_id} map by reading container labels and
    NetworkSettings.Networks[onyx_craft_sandbox].IPAddress.

    Then: docker events stream (filtered to container start/die)
    keeps the cache fresh. Reconnect with exponential backoff on
    stream drop.
    """

    def resolve(self, src_ip: str) -> SessionContext | None: ...
```

`identity.py` becomes a thin dispatcher: imports
`SANDBOX_BACKEND` from config and instantiates either the K8s
informer-backed resolver (Phase 1) or `DockerIdentityResolver`.
Downstream addons (`PassthroughAddon`, `GateAddon`) consume the same
`SessionContext` shape regardless.

The session-resolution rule (sandbox → user → most-recent active
`BuildSession`) is identical to K8s; only the IP-to-sandbox-id lookup
differs.

### T5.4 — CA distribution via named volume

`ca_docker.py`:

- Named volume `onyx-craft-ca` is mounted **read-write** into the
  proxy container at `/var/lib/onyx/ca/`, and **read-only** into every
  sandbox container at `/etc/onyx/ca/`.
- Proxy startup: if the CA files exist in the volume, load them;
  otherwise generate and write them. Volume-level locking is
  unnecessary because docker-compose runs a single proxy replica
  (T5.5).
- The bootstrap script reads the cert from `/etc/onyx/ca/sandbox-proxy.crt`
  rather than from a ConfigMap mount.

### T5.5 — Proxy delivery via docker-compose

Add a `sandbox-proxy` service to `deployment/docker_compose/docker-compose.craft.yml`:

- Image: the same proxy image built in Phase 1 T1.1.
- Networks: `onyx_craft_sandbox` (so sandboxes reach it by service
  name) plus the api-server's network (so it can call into the
  Approval Service via in-process imports — same wheel as Phase 1).
- Volumes: `onyx-craft-ca:/var/lib/onyx/ca/`, Docker socket
  (`/var/run/docker.sock`) read-only for the identity resolver to
  query the Docker Engine API.
- `SANDBOX_BACKEND=docker` env so the proxy boots the docker
  identity resolver and CA backend.
- **`replicas: 1`** — docker-compose lacks a native equivalent of
  K8s Service load balancing, and the docker-compose deployment story
  targets smaller installs that don't need cross-replica HA. The HA
  trade-offs from K8s (in-flight flows drop on crash, survivor takes
  new connections) don't apply; instead, a proxy crash drops all
  in-flight flows until restart. Documented as a known limitation.

### T5.6 — Backend selection in proxy

`config.py` reads `SANDBOX_BACKEND` (`kubernetes` | `docker`) and
exposes it to `server.py`, `identity.py`, and `ca.py`. Each module
dispatches to the appropriate implementation. The proxy refuses to
boot if the env value is unrecognized — no silent fallback.

### T5.7 — Operational

- **Healthz** unchanged from Phase 1 T1.6: 200 once the resolver has
  done its initial sync and the CA is loaded.
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

- Whether `firewall-init.sh` lives in `sandbox_proxy/scripts/` or in
  the sandbox image's own build context. Sharing one source of truth
  is the goal; the file ultimately needs to be in the image either
  way.
- Whether to expose any of the proxy's docker-events stream to
  monitoring / dashboards (likely punt; align with Phase 1's
  metrics-deferred posture).
- Whether the api-server's existing `onyx_craft_sandbox` bridge
  membership is sufficient for the proxy to call into the in-process
  Approval Service, or whether a second bridge is needed.

## Definition of done

- `SANDBOX_BACKEND=docker` boots the full stack with the proxy as a
  compose service; sandboxes route HTTPS through the proxy with the
  proxy CA accepted.
- Egress lockdown is fail-closed under docker: a broken
  `firewall-init.sh` causes the sandbox to fail to start (parity with
  the K8s init-container failure mode).
- Identity resolution works against the Docker Engine API; cache
  invalidates on container `die`.
- Phases 2–4 (gating, chat UI, policy) run unmodified against the
  docker backend and pass their existing tests.
- Documentation in `approvals-plan.md` reflects that both backends
  are supported in v0.
