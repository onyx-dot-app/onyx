# Phase 1 — Egress Interception Proxy (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture rationale.

## Goal

Stand up `sandbox_proxy` as cluster infrastructure in **pass-through mode**:
- All sandbox HTTPS traffic routes through it (default-deny egress
  NetworkPolicy + `HTTPS_PROXY` env in sandbox pods).
- HTTPS is MITM'd using an auto-generated CA distributed via ConfigMap.
- The proxy resolves source IP → session via the K8s API with an
  informer-backed cache.
- No gating logic yet. Every request is logged and forwarded transparently.

When this phase ends, the proxy is a working chokepoint we can layer
behavior onto in Phase 2.

## Module layout

New package `backend/onyx/sandbox_proxy/`:

```
sandbox_proxy/
├── server.py              # mitmproxy entrypoint, addon chain
├── ca.py                  # CA bootstrap + persist
├── identity.py            # pod-IP → session resolution + K8s informer
├── cache.py               # (placeholder; Phase 2 wires Redis)
├── addons/
│   └── logging.py         # pass-through addon that logs identified flows
├── Dockerfile
└── requirements.txt
```

K8s resources in `deployment/helm/charts/onyx/templates/`:

```
sandbox-proxy/
├── deployment.yaml        # Deployment + Service + ServiceAccount
├── rbac.yaml              # ClusterRole + ClusterRoleBinding for pods/configmaps/secrets read
├── ca-secret.yaml         # Secret holding CA key (starts empty)
├── ca-configmap.yaml      # ConfigMap holding CA cert (starts empty)
└── network-policy-sandbox-egress.yaml  # default-deny + allow to proxy
```

Sandbox pod modifications (in the existing helm chart):
- New initContainer that mounts the CA ConfigMap, copies the cert, runs
  `update-ca-certificates`.
- New env vars on the main sandbox container: `HTTPS_PROXY`, `HTTP_PROXY`,
  and a documented set of SDK-specific CA env vars for libraries that
  ignore the system trust store.

## Tasks

### T1.1 — Repo scaffolding

- Create `backend/onyx/sandbox_proxy/` package.
- Add `Dockerfile` (base: `mitmproxy/mitmproxy` or pin to a specific
  version; install Python deps).
- Add image build + push to CI (mirror the pattern used for
  `model_server`).

### T1.2 — CA bootstrap

`sandbox_proxy/ca.py` implements the lifecycle:

```python
class CABootstrap:
    def __init__(self, k8s, secret_name: str, configmap_name: str,
                 sandbox_namespace: str):
        ...

    def ensure_ca(self) -> tuple[bytes, bytes]:
        """Return (cert_pem, key_pem). Generates on first call;
        loads from K8s Secret on subsequent calls."""

    def _generate_ca(self) -> tuple[bytes, bytes]:
        """5-year RSA-4096 (or ECDSA P-256) CA pair via `cryptography`."""

    def _persist(self, cert: bytes, key: bytes) -> None:
        """Write Secret in proxy ns + ConfigMap in sandbox ns."""
```

Invariants:
- The Secret is the source of truth. The ConfigMap is derived from it.
- On startup, if Secret exists, load. If not, generate and persist both.
- The ConfigMap lives in the **sandbox** namespace (so sandbox pods can
  mount it without cross-namespace ConfigMap mounting).
- RBAC: proxy SA gets `get,create` on its own Secret; `get,create,update`
  on the sandbox-namespace ConfigMap.

### T1.3 — Sandbox pod CA integration

In the sandbox pod template:

```yaml
initContainers:
  - name: install-sandbox-ca
    image: <small base with update-ca-certificates>
    command: ["/bin/sh", "-c"]
    args:
      - cp /sandbox-ca/ca.crt /usr/local/share/ca-certificates/sandbox-proxy.crt
        && update-ca-certificates
        && cp /etc/ssl/certs/ca-certificates.crt /shared/ca-certificates.crt
    volumeMounts:
      - name: sandbox-ca
        mountPath: /sandbox-ca
      - name: shared-trust
        mountPath: /shared

containers:
  - name: sandbox
    env:
      - name: HTTPS_PROXY
        value: http://sandbox-proxy.onyx.svc.cluster.local:8080
      - name: HTTP_PROXY
        value: http://sandbox-proxy.onyx.svc.cluster.local:8080
      - name: NODE_EXTRA_CA_CERTS
        value: /shared/ca-certificates.crt
      - name: REQUESTS_CA_BUNDLE
        value: /shared/ca-certificates.crt
      - name: SSL_CERT_FILE
        value: /shared/ca-certificates.crt
      - name: AWS_CA_BUNDLE
        value: /shared/ca-certificates.crt
    volumeMounts:
      - name: shared-trust
        mountPath: /shared

volumes:
  - name: sandbox-ca
    configMap:
      name: sandbox-proxy-ca-cert
  - name: shared-trust
    emptyDir: {}
```

The shared `emptyDir` is because the initContainer needs to write to the
trust file (root in init, non-root in main).

### T1.4 — Identity resolver

`sandbox_proxy/identity.py`:

```python
class SessionContext:
    session_id: UUID
    user_id: UUID
    sandbox_id: UUID
    pod_name: str
    pod_ip: str

class IdentityResolver:
    def __init__(self, k8s, sandbox_namespace: str,
                 db_session_factory):
        self._cache: dict[str, SessionContext] = {}
        self._k8s = k8s
        self._db = db_session_factory
        self._start_informer(sandbox_namespace)

    def resolve(self, src_ip: str) -> SessionContext | None:
        if hit := self._cache.get(src_ip):
            return hit
        pod = self._k8s.find_pod_by_ip(src_ip)
        if pod is None:
            return None
        ctx = self._resolve_pod_to_session(pod)
        if ctx:
            self._cache[src_ip] = ctx
        return ctx

    def _resolve_pod_to_session(self, pod) -> SessionContext | None:
        """Map pod metadata to (sandbox, active session, user)."""
        # Sandbox.user_id is unique; look up via pod label/annotation
        # that identifies the sandbox.
        ...

    def _start_informer(self, namespace: str):
        """K8s pod watch; evict cache on pod deletion / IP change."""
```

The informer should:
- Watch pods in the sandbox namespace.
- On `DELETED` or `MODIFIED` (with IP change): evict cache entry.
- Background thread; survives K8s API blips with backoff.

### T1.5 — NetworkPolicy

`deployment/helm/charts/onyx/templates/sandbox-proxy/network-policy-sandbox-egress.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "onyx.fullname" . }}-sandbox-egress
  namespace: {{ $sandboxNs }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: sandbox
  policyTypes: [Egress]
  egress:
    # DNS
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # sandbox-proxy only
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: {{ $.Release.Namespace }}
          podSelector:
            matchLabels:
              app: sandbox-proxy
      ports:
        - protocol: TCP
          port: 8080
```

### T1.6 — Pass-through addon

`sandbox_proxy/addons/logging.py`:

```python
class LoggingAddon:
    def __init__(self, identity: IdentityResolver):
        self._identity = identity

    async def request(self, flow):
        src_ip = flow.client_conn.peername[0]
        ctx = self._identity.resolve(src_ip)
        logger.info(
            "egress",
            session_id=str(ctx.session_id) if ctx else None,
            method=flow.request.method,
            host=flow.request.host,
            path=flow.request.path,
        )
        # no modification; mitmproxy forwards as-is
```

### T1.7 — Operational

- Health endpoint: `GET /healthz` on a non-proxy port returning the
  state of the K8s informer + last successful CA load.
- Resource requests: small to start; revisit when Phase 2 adds Redis I/O.
- Logging: structured JSON to stdout, picked up by existing log pipeline.

## Pseudocode: entrypoint

```python
# sandbox_proxy/server.py
from mitmproxy.tools.main import mitmdump

def main():
    k8s = load_k8s_client()
    ca = CABootstrap(k8s, ...).ensure_ca()
    identity = IdentityResolver(k8s, SANDBOX_NS, db_session_factory)

    mitmdump([
        "--listen-port", "8080",
        "--certs", f"*={write_combined_pem(ca)}",
        "-s", "sandbox_proxy/server_addons_entry.py",
        # addon entry registers LoggingAddon(identity)
    ])
```

## Testing

- **Unit**: `CABootstrap.ensure_ca()` idempotency; `IdentityResolver`
  cache hit / miss / eviction on simulated pod events.
- **Integration cluster** (staging):
  - Deploy proxy, deploy a test sandbox.
  - From inside sandbox: `curl -v https://example.com` succeeds; cert
    chain shows the proxy CA.
  - From inside sandbox: `curl -v https://example.com --noproxy '*'`
    fails (NetworkPolicy blocks).
  - Delete and recreate the sandbox pod; verify the cache evicts.

## Dependencies

- EKS VPC CNI native NetworkPolicy enforcement enabled (confirmed).
- K8s ServiceAccount + RBAC for proxy.
- DB read access from proxy pod (for `_resolve_pod_to_session`); use the
  same Postgres credentials pattern as api-server.

## Open during phase

- Exact placement of `sandbox_proxy/` — root under `backend/`, or alongside
  `backend/onyx/` as a sibling package? Confirm with monorepo conventions.
- Pin mitmproxy version (latest stable, ~12.x).
- Pod selector for the proxy egress NetworkPolicy needs to handle the
  case where a sandbox pod has multiple containers — `app.kubernetes
  .io/component: sandbox` should already be on the pod; verify.

## Definition of done

- `curl https://api.slack.com/...` from inside a sandbox succeeds and is
  logged by the proxy.
- `curl https://example.com` from inside a sandbox with NetworkPolicy
  proxy-bypass attempt fails (RST or denied).
- Recreating a sandbox doesn't break identity resolution.
- mitmproxy serves leaf certs signed by our CA; sandbox SDKs (Python
  `requests`, Node `fetch`) accept them.
- Staging smoke test green.
