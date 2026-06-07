# Phase 1 — Egress Interception Proxy (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture rationale.

## Scope

**Kubernetes sandbox backend in this phase; docker-compose support
lands in [Phase 5](./phase-5-docker.md).** The infrastructure layer
(iptables installation, CA distribution, identity resolution, proxy
delivery) is K8s-native here. The proxy core, addons, Approval
Service, chat UI, and policy are backend-agnostic.

Phase 1 lands the backend-swappable interfaces (`SandboxIPLookup`
in T1.4, `CAStore` in T1.2, and the env-driven mode switch in
`firewall-init.sh` in T1.3) with K8s implementations as the concrete
instances.

## Goal

Stand up `sandbox_proxy` as cluster infrastructure in **pass-through mode**:

- All sandbox HTTPS traffic routes through it (in-pod iptables egress
  lockdown plus `HTTPS_PROXY` env in sandbox pods).
- HTTPS is MITM'd using an auto-generated CA distributed via ConfigMap.
- The proxy resolves source IP to session via the K8s API with an
  informer-backed cache, then via DB lookup for the active `BuildSession`.
- No gating logic yet. Every request is logged and forwarded transparently.

When this phase ends, the proxy is a working chokepoint we can layer behavior
onto in Phase 2.

## Module layout

New package `backend/onyx/sandbox_proxy/`. The proxy image bundles the
backend module tree; the proxy calls into backend code via in-process
Python imports, with no HTTP hop between proxy and api-server.

```
sandbox_proxy/
├── server.py              # mitmproxy entrypoint, addon chain
├── ca.py                  # CABootstrap + CAStore Protocol
├── ca_k8s.py              # K8sSecretCAStore (this phase); Phase 5 adds ca_docker.py
├── identity.py            # src-IP → session resolution + SandboxIPLookup Protocol
├── identity_k8s.py        # K8sInformerLookup (this phase); Phase 5 adds identity_docker.py
├── cache.py               # placeholder; Phase 2 wires Redis BLPOP/RPUSH here
├── addons/
│   └── passthrough.py         # pass-through addon that logs identified flows
├── Dockerfile
└── requirements.txt
```

Config constants live in `backend/onyx/server/features/build/configs.py`
under the `SANDBOX_PROXY_*` namespace. The api-server (constructing
sandbox pod specs) and the proxy itself both read from this same
source of truth.

The shared sandbox bootstrap script lives in the sandbox image dir:

```
backend/onyx/server/features/build/sandbox/image/
└── firewall-init.sh       # runs as the K8s initContainer command
                            # in this phase; Phase 5 reuses it as the
                            # docker-compose entrypoint wrapper. Mode
                            # is selected via SANDBOX_PROXY_BOOTSTRAP_MODE.
```

It's colocated with the sandbox Dockerfile so it's auto-pulled into
the build context.

K8s resources under `deployment/helm/charts/onyx/templates/sandbox-proxy/`:
`deployment.yaml`, `rbac.yaml`, `ca-secret.yaml`, `ca-configmap.yaml`.

Sandbox pod modifications (existing helm chart):

- **One consolidated initContainer** (`sandbox-init`) that does all the
  pre-startup security setup: CA trust-store population, in-pod iptables
  egress lockdown, writing the proxy IP into `/etc/hosts`, and a
  self-verification step that fails the init if the lockdown isn't
  actually in effect. Uses the existing sandbox image with a different
  command; `iptables` gets installed into that image. Init container
  runs as root with `CAP_NET_ADMIN`; main container is unchanged
  (UID 1000, no caps).
- New env vars on the main sandbox container: `HTTPS_PROXY`, `HTTP_PROXY`,
  plus a documented set of SDK-specific CA env vars for libraries that
  ignore the system trust store.
- The existing `sandbox_daemon` sidecar is unchanged and stays
  unprivileged.

## Tasks

### T1.1 — Repo scaffolding

- Create `backend/onyx/sandbox_proxy/` package.
- Add `Dockerfile`. Base image is the existing Onyx backend image
  (same image celery workers consume, different entrypoint). Install
  `mitmproxy` on top, set the entrypoint to
  `python -m onyx.sandbox_proxy.server`. Inheriting from the backend
  image gives the proxy `onyx.db`, `onyx.cache`, etc. without a
  separate dependency graph.
- Add image build and push to CI alongside the existing backend image.

### T1.2 — CA bootstrap

CA generation and rotation policy is backend-agnostic; **persistence**
is backend-specific (K8s Secret here, named volume in Phase 5). Split
`sandbox_proxy/ca.py` along that line:

```python
class CAStore(Protocol):
    """Persistence backend for the proxy CA.

    `persist` must be idempotent under concurrent callers: if two
    proxy replicas race on a cold cluster, exactly one write wins
    and the loser's next `load()` returns the winner's CA. K8s
    achieves this via conditional create on the Secret (resourceVersion="");
    docker volumes use the same load-then-create-with-O_EXCL pattern.
    """
    def load(self) -> tuple[bytes, bytes] | None: ...
    def persist(self, cert: bytes, key: bytes) -> None: ...

class CABootstrap:
    def __init__(self, store: CAStore): ...
    def ensure_ca(self) -> tuple[bytes, bytes]: ...
    def _generate_ca(self) -> tuple[bytes, bytes]: ...
```

Phase 1 ships `K8sSecretCAStore`. The bootstrap orchestration
(load-or-generate, key params, rotation hooks) lives in `CABootstrap`
and is unchanged across backends.

`CABootstrap.ensure_ca` retries on `persist` conflict: re-`load()`,
return the winner's CA. K8s `persist` translates a `409 Conflict`
from the conditional create into a no-op so the next `load()`
succeeds.

Invariants for the K8s store:

- The Secret is the source of truth. The ConfigMap is derived from it.
- On startup: load if the Secret exists, otherwise generate and persist
  both. Persist uses a conditional create (`resourceVersion=""`) so
  two replicas racing on a cold cluster don't double-write — the loser
  of the race reads back the winner's CA.
- ConfigMap lives in the **sandbox** namespace so sandbox pods can mount it
  without cross-namespace ConfigMap mounting.
- RBAC: proxy SA gets `get,create` on its own Secret; `get,create,update` on
  the sandbox-namespace ConfigMap.
- Key params (defined on `CABootstrap`, shared across stores):
  5-year RSA-4096 (or ECDSA P-256) via `cryptography`.

### T1.3 — Sandbox bootstrap initContainer

The bootstrap (CA trust-store population, iptables egress lockdown,
proxy address resolution, self-verify) is implemented as a **single
shared script** — `firewall-init.sh`, baked into the sandbox image.
The sandbox image picks up `iptables` and `gosu` as new dependencies
(`gosu` is consumed by Phase 5; Phase 1 ignores it). Phase 1 runs the
script as the K8s initContainer command;
[Phase 5](./phase-5-docker.md) runs the same script as the docker
container's entrypoint, ending in `exec gosu` to drop privileges. The
two modes share steps 1–2 (CA + iptables) and step 4 (self-verify);
they diverge only on step 3 and on what the script does after step 4:

| Env var | K8s value | Docker value (Phase 5) |
|---|---|---|
| `SANDBOX_PROXY_HOST` | proxy ClusterIP | `sandbox-proxy` (compose DNS) |
| `SANDBOX_PROXY_PORT` | proxy port | proxy port |
| `SANDBOX_PROXY_BOOTSTRAP_MODE` | `initcontainer` | `entrypoint` |

`initcontainer` mode:
- Step 3: write `<proxy_ip> sandbox-proxy` to `/etc/hosts` so the
  main container's `HTTPS_PROXY` resolves without DNS.
- Post-step-4: `exit 0`; the main container starts unchanged.

`entrypoint` mode (Phase 5):
- Step 3: skipped — docker-compose service DNS resolves `sandbox-proxy`
  without `/etc/hosts` injection.
- Post-step-4: `exec gosu 1000:1000 <real-entrypoint>`.

In Phase 1, the script runs in an initContainer using the existing
sandbox image, as root with `CAP_NET_ADMIN`. Sequentially before the
main sandbox container starts:

1. **CA trust-store population.** Mount the CA ConfigMap read-only, copy
   the cert into `/usr/local/share/ca-certificates/sandbox-proxy.crt`, run
   `update-ca-certificates`, write the resulting bundle into a shared
   `emptyDir` volume mounted into the main container.
2. **In-pod egress lockdown via iptables.** Default-deny `OUTPUT`; allow
   loopback, conntrack-established, and TCP to the sandbox-proxy IP + port
   only. Drop all DNS (the proxy resolves external hostnames; the sandbox
   doesn't need DNS — see step 3). Drop all IPv6 egress via `ip6tables`.
   Pattern adapted from agent-vault's init-firewall script.
3. **Pre-resolve the proxy.** Write `<proxy_ip> sandbox-proxy` to
   `/etc/hosts` (proxy IP injected via the pod spec at provisioning time).
   The main container's `HTTPS_PROXY` then resolves to the right IP
   without needing DNS.
4. **Self-verify the lockdown.** Attempt one egress that should be
   blocked (e.g., `curl --max-time 2 https://1.1.1.1`). If it succeeds,
   exit non-zero — the rules aren't actually in effect and the pod must
   not start. If it fails as expected, exit 0. This catches the
   "iptables rules silently didn't install" case at the only moment we
   can act on it (the pod won't start; an operator gets a clear init
   failure).

Then on the main container:

- `HTTPS_PROXY` / `HTTP_PROXY` point at `http://sandbox-proxy:<port>`
  (resolved via `/etc/hosts`).
- Fan out CA env vars to cover SDKs that bypass the system trust store:
  `NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`,
  `AWS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `GIT_SSL_CAINFO`. All point at the
  shared bundle file.

**JVM out of scope.** Java SDKs use their own truststore (`cacerts`,
PKCS12) and require a separate `keytool -importcert` step. Out of v0
scope; any JVM-based gated app fails closed at the iptables lockdown.

### T1.4 — Identity resolver

The K8s informer is the IP-to-sandbox lookup *source*; the rest of
identity resolution (sandbox → user → active session) is backend-
agnostic. `sandbox_proxy/identity.py` is split along that line:

```python
@dataclass
class SessionContext:
    session_id: UUID
    user_id: UUID
    sandbox_id: UUID
    tenant_id: str
    sandbox_name: str   # pod name in K8s; container name in docker
    sandbox_ip: str

@dataclass
class SandboxIdentity:
    sandbox_id: UUID
    tenant_id: str
    sandbox_name: str
    sandbox_ip: str

class SandboxIPLookup(Protocol):
    """Backend-specific IP → SandboxIdentity resolver.
    K8s = informer-backed cache; docker = events-stream-backed cache."""
    def lookup(self, src_ip: str) -> SandboxIdentity | None: ...

class IdentityResolver:
    def __init__(self, ip_lookup: SandboxIPLookup, db_factory): ...
    def resolve(self, src_ip: str) -> SessionContext | None: ...
```

Phase 1 ships `K8sInformerLookup`. The sandbox-row read, user lookup,
and active-session resolution (steps 2–4 below) live on
`IdentityResolver` and are unchanged across backends.

Sandbox → session resolution rule:

1. Map `src_ip` to a sandbox via `SandboxIPLookup`. The K8s impl reads
   the pod from the informer-backed cache and returns
   `{sandbox_id, tenant_id, sandbox_name}` from labels.
2. The lookup reads `onyx.app/sandbox-id` and `onyx.app/tenant-id` —
   identical label keys are set by both backends
   (`kubernetes_sandbox_manager._create_sandbox_pod`
   and `docker_sandbox_manager` on container creation).
   `tenant_id` is sourced from the label, not from the DB —
   the `Sandbox` model does not carry one.
3. Look up the `Sandbox` row by id to read `sandbox.user_id`.
4. Resolve the active `BuildSession`: most-recent row where
   `user_id == sandbox.user_id AND user_id IS NOT NULL AND
   status == BuildSessionStatus.ACTIVE`, ordered by `last_activity_at desc`.
   If none, return `None` (unidentified).

Concurrent sessions on the same sandbox are prevented upstream by the
scheduled-task executor (serializes cron-fired sessions against the
sandbox's interactive session — see Phase 2 deliverable), so step 4
yields a single unambiguous match.

Identity edge cases / preconditions:

- **No SNAT** on the sandbox-to-proxy path. SNAT would mask the
  sandbox source IP.
- **No service-mesh sidecar** (Istio/Linkerd) on sandbox pods, which
  would rewrite the source IP at the proxy. Document this as a K8s
  prerequisite.
- Startup self-check: if the lookup source can't be reached on boot, or
  if the initial sandbox list reveals duplicate IPs, fail loud and
  exit non-zero. Don't silently serve traffic with broken identity.

`K8sInformerLookup`:

- Watches pods in the sandbox namespace.
- Evicts cache entries on `DELETED` or on `MODIFIED` with an IP change.
- Background thread; reconnects with exponential backoff on K8s API blips.

### T1.5 — Pass-through addon

`sandbox_proxy/addons/passthrough.py`:

```python
class PassthroughAddon:
    def __init__(self, identity: IdentityResolver, metrics: Metrics): ...

    async def request(self, flow):
        src_ip = flow.client_conn.peername[0]
        ctx = self._identity.resolve(src_ip)
        if ctx is None:
            # Phase 1 is pass-through: log loudly and forward.
            # Phase 2's GateAddon will hard-reject unidentified flows.
            logger.warning("unidentified_egress src_ip=%s host=%s",
                           src_ip, flow.request.host)
            self._metrics.unidentified_passthrough.inc()
        else:
            logger.info("egress session_id=%s host=%s path=%s",
                        ctx.session_id, flow.request.host,
                        flow.request.path)
            self._metrics.identified_passthrough.inc()
```

### T1.6 — Operational

**Two replicas.** The Deployment runs `replicas: 2`. The proxy is
stateless across the wire (per-flow state lives in the accepting
replica's memory; durable state lives in the DB and Redis), so replicas
operate independently and the K8s Service load-balances new connections
across them. CA bootstrap is idempotent (T1.2). No cross-replica
coordination is required.

**Graceful drain.** On SIGTERM the proxy stops accepting new connections,
keeps existing flows running until `terminationGracePeriodSeconds` (set
generously, ~200s — comfortably above the Phase 2 180s wait) expires,
then exits. The readiness probe flips to not-ready on SIGTERM so the
Service stops sending it traffic; new connections route to the surviving
replica during rolling deploys. On hard crash (OOM, process kill), all
in-flight flows on the crashed replica drop with TCP RST to the
sandbox; new connections still succeed via the survivor. Cross-replica
flow resumption is not supported (out of scope for v0).

**Health endpoint** `GET /healthz`: returns 200 once the
`SandboxIPLookup` source has finished its initial sync and the CA is
loaded.

**Metrics — deferred.** v0 ships with no Prometheus surface. Add the
metrics module and wire counters when we move toward a production
environment with observability.

## Testing

- **Unit**: `CABootstrap.ensure_ca()` idempotency; `IdentityResolver` cache
  hit / miss / eviction on simulated pod events; sandbox → active-session
  resolution including the "no active session" branch.
- **Integration cluster** (dev):
  - From inside a sandbox, `curl -v https://example.com` succeeds and the
    chain shows the proxy CA.
  - From inside a sandbox, `curl -v https://example.com --noproxy '*'`
    fails (in-pod iptables denies).
  - Delete and recreate the sandbox pod; verify the cache evicts and the
    new pod IP resolves correctly.

## Dependencies

- **Deployment target accepts `CAP_NET_ADMIN` on the initContainer.**
  PSS Baseline disallows added capabilities outside
  `NET_BIND_SERVICE`, so strict Baseline admission will reject the
  init container as-written; deployments must allow the capability
  via namespace-level policy carve-out or run under a less
  restrictive profile. The main container itself stays restricted
  (UID 1000, no added caps). PSS Restricted is incompatible.
- K8s ServiceAccount and RBAC for the proxy.
- DB read access from the proxy pod (Sandbox, BuildSession, User tables);
  same Postgres credential pattern as api-server.

## Open during phase

- Final `terminationGracePeriodSeconds` value (200s starting point).
- JVM SDK trust-store onboarding path if a JVM-based gated action lands in
  v0 (currently none planned).
- Whether the proxy's `values.yaml` lives in the existing Onyx chart
  or as a sub-chart (T1.1 currently assumes the existing chart).

## Definition of done

- `curl https://api.slack.com/...` from inside a sandbox succeeds, is MITM'd
  with leaf cert signed by our CA, and the proxy logs the flow with a
  resolved `SessionContext`.
- `curl https://example.com --noproxy '*'` from inside a sandbox fails
  (in-pod iptables denies).
- Init container self-verification catches a deliberately broken
  iptables setup: deploy a sandbox whose init script skips the lockdown,
  verify the pod fails to start with a clear init-container error.
- `nslookup example.com` from inside a sandbox fails — DNS is closed.
- IPv6 egress (`curl -6 ...`) from inside a sandbox fails.
- Recreating a sandbox pod evicts the cache entry and the new IP resolves
  on next request.
- Common SDKs accept the proxy CA: Python `requests`, Node `fetch`, `curl`,
  `git clone https://...`.
