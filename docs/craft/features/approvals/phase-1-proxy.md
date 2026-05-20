# Phase 1 — Egress Interception Proxy (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture rationale.

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

New package `backend/onyx/sandbox_proxy/` (the proxy image bundles the backend
module tree; no HTTP hop between proxy and api-server):

```
sandbox_proxy/
├── server.py              # mitmproxy entrypoint, addon chain
├── ca.py                  # CA bootstrap + persist
├── identity.py            # pod-IP → session resolution + K8s informer
├── cache.py               # placeholder; Phase 2 wires Redis BLPOP/RPUSH here
├── config.py              # env-driven config (listen port, namespace, etc.)
├── addons/
│   └── passthrough.py         # pass-through addon that logs identified flows
├── Dockerfile
└── requirements.txt
```

K8s resources under `deployment/helm/charts/onyx/templates/sandbox-proxy/`:
`deployment.yaml`, `rbac.yaml`, `ca-secret.yaml`, `ca-configmap.yaml`.

Sandbox pod modifications (existing helm chart):

- **One consolidated initContainer** (`sandbox-init`) that does all the
  pre-startup security setup: CA trust-store population, in-pod iptables
  egress lockdown, writing the proxy IP into `/etc/hosts`, and a
  self-verification step that fails the init if the lockdown isn't
  actually in effect. **Uses the existing sandbox image** with a
  different command (no second image to maintain); `iptables` gets
  installed into that image. Init container runs as root with
  `CAP_NET_ADMIN`; main container is unchanged (UID 1000, no caps).
- New env vars on the main sandbox container: `HTTPS_PROXY`, `HTTP_PROXY`,
  plus a documented set of SDK-specific CA env vars for libraries that
  ignore the system trust store.
- The existing `sandbox_daemon` sidecar is **unchanged** — stays
  unprivileged. Init work doesn't belong there: it's one-shot, needs
  sequenced ordering before the main container starts, and would force
  the daemon to hold `CAP_NET_ADMIN` for its entire lifetime.

## Tasks

### T1.1 — Repo scaffolding

- Create `backend/onyx/sandbox_proxy/` package.
- Add `Dockerfile`. Base image is the existing Onyx backend image (the same
  image celery workers consume — different entrypoint, same install). Install
  `mitmproxy` on top, set the entrypoint to `python -m onyx.sandbox_proxy
  .server`. Inheriting from the backend image gives us `onyx.db`,
  `onyx.cache`, etc. with no separate dependency-graph maintenance.
- Add image build and push to CI alongside the existing backend image.

### T1.2 — CA bootstrap

`sandbox_proxy/ca.py`:

```python
class CABootstrap:
    def __init__(self, k8s, secret_name: str, configmap_name: str,
                 sandbox_namespace: str): ...

    def ensure_ca(self) -> tuple[bytes, bytes]: ...
    def _generate_ca(self) -> tuple[bytes, bytes]: ...
    def _persist(self, cert: bytes, key: bytes) -> None: ...
```

Invariants:

- The Secret is the source of truth. The ConfigMap is derived from it.
- On startup: load if the Secret exists, otherwise generate and persist
  both. Persist uses a conditional create (`resourceVersion=""`) so two
  replicas racing on a cold cluster don't double-write — the loser of
  the race reads back the winner's CA. Idempotent.
- ConfigMap lives in the **sandbox** namespace so sandbox pods can mount it
  without cross-namespace ConfigMap mounting.
- RBAC: proxy SA gets `get,create` on its own Secret; `get,create,update` on
  the sandbox-namespace ConfigMap.
- Key params: 5-year RSA-4096 (or ECDSA P-256) via `cryptography`.

### T1.3 — Sandbox bootstrap initContainer

A single `sandbox-init` initContainer using the **existing sandbox image**
(no separate image to maintain — we install `iptables` into that image),
running as root with `CAP_NET_ADMIN`, does four things sequentially before
the main sandbox container starts:

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
scope; documented so any JVM-based gated app fails closed at the iptables
lockdown with a clear diagnostic rather than silently misbehaving.

**Why only in-pod iptables, not also a NetworkPolicy?** iptables-in-pod
has strong fail-closed semantics — if the init container's setup fails,
the pod doesn't start. A K8s NetworkPolicy as a second layer would fail
*open* if the cluster's CNI ever stops enforcing (a silent failure
mode). The single-layer in-pod approach is the stronger of the two and
closes DNS + IPv6 that NetworkPolicy didn't cover anyway. The
self-verification in step 4 catches the deploy-time mistake (someone
changes the init script and removes the lockdown) that NetworkPolicy
would otherwise backstop.

### T1.4 — Identity resolver

`sandbox_proxy/identity.py`:

```python
@dataclass
class SessionContext:
    session_id: UUID
    user_id: UUID
    sandbox_id: UUID
    tenant_id: str
    pod_name: str
    pod_ip: str

class IdentityResolver:
    def resolve(self, src_ip: str) -> SessionContext | None: ...
    def _resolve_pod_to_session(self, pod) -> SessionContext | None: ...
    def _start_informer(self, namespace: str): ...
```

Sandbox → session resolution rule:

1. Map `src_ip` to a sandbox pod via the K8s informer-backed cache.
2. Read `onyx.app/sandbox-id` and `onyx.app/tenant-id` from the pod labels.
   Both are set by `kubernetes_sandbox_manager.py` at pod creation
   (`_create_sandbox_pod`, lines 508-514). `tenant_id` is sourced from the
   pod label, not from the DB — the `Sandbox` model does not carry one.
3. Look up the `Sandbox` row by id to read `sandbox.user_id`.
4. Resolve the active `BuildSession`: most-recent row where
   `user_id == sandbox.user_id AND user_id IS NOT NULL AND
   status == BuildSessionStatus.ACTIVE`, ordered by `last_activity_at desc`.
   If none, return `None` (unidentified).

**Concurrent sessions on the same sandbox are prevented upstream by the
scheduled-task executor** (serializes cron-fired sessions against the
sandbox's interactive session — see Phase 2 deliverable). That guarantees
step 4 yields a single unambiguous match. `BuildSession.origin`
(`INTERACTIVE` / `SCHEDULED`) remains available as a future discriminator
if we ever loosen the serialization rule.

Identity edge cases / preconditions:

- **No SNAT** on the pod-to-proxy path. SNAT would mask the sandbox pod IP.
- **No service-mesh sidecar** (Istio/Linkerd) on sandbox pods, which would
  rewrite the source IP at the proxy. Document this as a prerequisite.
- Startup self-check: if the proxy cannot reach the K8s API on boot, or if
  the sandbox-namespace pod list reveals duplicate pod IPs, fail loud and
  exit non-zero. Don't silently serve traffic with broken identity.

The informer:

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

**Health endpoint** `GET /healthz`: returns 200 once the informer has
synced and the CA is loaded.

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

- Deployment target allows PSS Baseline (`CAP_NET_ADMIN` on the
  initContainer; main container stays restricted). PSS Restricted is
  incompatible.
- K8s ServiceAccount and RBAC for the proxy.
- DB read access from the proxy pod (Sandbox, BuildSession, User tables);
  same Postgres credential pattern as api-server.

## Open during phase

- Exact sandbox-id label key set by the K8s sandbox manager (see T1.4 TODO).
- Final `terminationGracePeriodSeconds` value (200s starting point).
- JVM SDK trust-store onboarding path if a JVM-based gated action lands in
  v0 (currently none planned).

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
