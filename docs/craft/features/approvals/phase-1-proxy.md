# Phase 1 — Egress Interception Proxy (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture rationale.

## Goal

Stand up `sandbox_proxy` as cluster infrastructure in **pass-through mode**:

- All sandbox HTTPS traffic routes through it (default-deny egress
  NetworkPolicy plus `HTTPS_PROXY` env in sandbox pods).
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
├── cache.py               # (placeholder; Phase 2 wires Redis)
├── config.py              # env + ConfigMap-driven feature flags
├── metrics.py             # Prometheus counters / histograms
├── addons/
│   └── logging.py         # pass-through addon that logs identified flows
├── Dockerfile
└── requirements.txt
```

K8s resources under `deployment/helm/charts/onyx/templates/sandbox-proxy/`:
`deployment.yaml`, `rbac.yaml`, `ca-secret.yaml`, `ca-configmap.yaml`,
`network-policy-sandbox-egress.yaml`.

Sandbox pod modifications (existing helm chart):

- New initContainer that mounts the CA ConfigMap, copies the cert, runs
  `update-ca-certificates`. Init runs as root and writes to a shared
  `emptyDir` because the main sandbox container is non-root.
- New env vars on the main sandbox container: `HTTPS_PROXY`, `HTTP_PROXY`,
  plus a documented set of SDK-specific CA env vars for libraries that
  ignore the system trust store.

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
- On startup: load if the Secret exists, otherwise generate and persist both.
- ConfigMap lives in the **sandbox** namespace so sandbox pods can mount it
  without cross-namespace ConfigMap mounting.
- RBAC: proxy SA gets `get,create` on its own Secret; `get,create,update` on
  the sandbox-namespace ConfigMap.
- Key params: 5-year RSA-4096 (or ECDSA P-256) via `cryptography`.

### T1.3 — Sandbox pod CA integration

Patch the sandbox pod template:

- Add an `install-sandbox-ca` initContainer using `debian:stable-slim`
  (ships `update-ca-certificates`). It mounts the CA ConfigMap read-only,
  copies into `/usr/local/share/ca-certificates/sandbox-proxy.crt`, runs
  `update-ca-certificates`, and writes the resulting bundle into a shared
  `emptyDir` volume. The initContainer runs as root; the main container
  reads the bundle as non-root from the shared volume.
- Add `HTTPS_PROXY` / `HTTP_PROXY` on the main container pointing at
  `http://sandbox-proxy.<proxy-ns>.svc.cluster.local:8080`.
- Fan out CA env vars to cover SDKs that bypass the system trust store:
  `NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`,
  `AWS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `GIT_SSL_CAINFO`. All point at the
  shared bundle file.

**JVM out of scope.** Java SDKs use their own truststore (`cacerts`, PKCS12)
and require a separate `keytool -importcert` step. Out of v0 scope; document
so any JVM-based gated app fails closed at the NetworkPolicy with a clear
diagnostic rather than silently misbehaving.

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

### T1.5 — NetworkPolicy

`network-policy-sandbox-egress.yaml` selects sandbox pods by their existing
component label and is `policyTypes: [Egress]` only. Two egress rules:
DNS (UDP/TCP 53 to `kube-dns`), and TCP 8080 to pods labeled
`app: sandbox-proxy` in the proxy namespace. Everything else is denied by
default.

### T1.6 — Pass-through addon

`sandbox_proxy/addons/logging.py`:

```python
class LoggingAddon:
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

### T1.7 — Operational

**Feature flag / kill switch.** `SANDBOX_PROXY_MODE` env var with values
`passthrough` (default in Phase 1) and `enforce` (Phase 2). Sourced from a
ConfigMap mounted into the pod so it can be flipped without a rebuild;
reload on SIGHUP if the operator restart cost is unacceptable. The flag is
independent of the gate addon's wiring — `passthrough` means LoggingAddon
only, even if the gate addon module is present. This is the "turn it off
in prod" lever.

**Graceful drain.** On SIGTERM the proxy stops accepting new connections,
keeps existing flows running until `terminationGracePeriodSeconds` (set
generously, ~200s — comfortably above the Phase 2 180s wait) expires, then
exits. The readiness probe flips to not-ready on SIGTERM so the Service
stops sending it traffic. On hard crash (OOM, process kill), all in-flight
flows drop with TCP RST to the sandbox and there is no resumption — single
replica, no state persistence. Acceptable for v0.

**Metrics** (Prometheus, exposed on a non-proxy port alongside `/healthz`):

- Request rate, labeled by status (`passthrough` / `gated` / `blocked`).
- Identity-resolution cache hit / miss counter.
- K8s informer reconnect counter.
- CA load failure alert counter (should stay at zero post-bootstrap).
- TLS handshake failure counter, labeled by destination host. This is the
  SDK-bypass canary — a spike means some SDK is hitting upstream with a
  trust store that doesn't include our CA.
- Request-path latency histogram.

**Health endpoint** `GET /healthz`: returns 200 once the informer has
synced and the CA is loaded.

### T1.8 — Rollout staging

The risk this addresses is "NetworkPolicy misconfig breaks egress for the
entire sandbox fleet." Roll out in three stages, each verified before the
next:

1. **Proxy + CA + sandbox env vars, no NetworkPolicy.** Proxy is deployed,
   sandboxes have `HTTPS_PROXY` set, traffic flows through the proxy. With
   no NetworkPolicy, a misconfigured proxy still lets traffic out directly
   so sandboxes keep working. Verify logs show identified flows.
2. **NetworkPolicy with per-namespace opt-in label.** Apply the policy only
   to namespaces tagged `sandbox-proxy-egress: enforced`. Tag one staging
   sandbox namespace, verify, watch metrics.
3. **Expand to all sandbox namespaces.** Tag remaining namespaces. The
   feature flag from T1.7 remains available as a kill switch.

### T1.9 — Self-hosted documentation

- Update the helm chart README: NetworkPolicy egress enforcement requires
  a CNI that enforces egress policies (Cilium, Calico, or AWS VPC CNI with
  `enableNetworkPolicy: true`). Plain kindnet / flannel will not enforce
  and the proxy chokepoint becomes advisory.
- One-paragraph runbook stubs for "sandbox-proxy is down" (flip
  `SANDBOX_PROXY_MODE=passthrough`, or remove the NetworkPolicy label from
  affected namespaces) and "approvals not working" (check informer
  reconnect counter, CA load metric, identity-cache hit rate).

## Testing

- **Unit**: `CABootstrap.ensure_ca()` idempotency; `IdentityResolver` cache
  hit / miss / eviction on simulated pod events; sandbox → active-session
  resolution including the "no active session" branch.
- **Integration cluster** (staging):
  - From inside a sandbox, `curl -v https://example.com` succeeds and the
    chain shows the proxy CA.
  - From inside a sandbox, `curl -v https://example.com --noproxy '*'`
    fails (NetworkPolicy blocks).
  - Delete and recreate the sandbox pod; verify the cache evicts and the
    new pod IP resolves correctly.
  - Flip the kill switch to `passthrough` mid-traffic; verify gate path is
    inert (no behavioral change in Phase 1, but the wiring should hold).

## Dependencies

- CNI enforces egress NetworkPolicies (EKS VPC CNI confirmed).
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
  (NetworkPolicy denies).
- Recreating a sandbox pod evicts the cache entry and the new IP resolves
  on next request.
- Common SDKs accept the proxy CA: Python `requests`, Node `fetch`, `curl`,
  `git clone https://...`.
- Kill switch verified: setting `SANDBOX_PROXY_MODE=passthrough` is a no-op
  in Phase 1 but the flag wiring is exercised end-to-end.
- Prometheus scrape returns the metrics listed in T1.7; each counter
  increments under a corresponding test action.
- Rollout staging verified: deployed to one opt-in staging sandbox
  namespace, observed for at least one business day, before any broader
  rollout.
