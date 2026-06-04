# Known gaps

Things this PoC deliberately does not handle. Each entry includes the
reason it's deferred and where V1 will need to address it.

## Network / steering

### `NET_ADMIN` requirement (transparent mode only)

Many managed Kubernetes clusters disallow `NET_ADMIN` capabilities, including
EKS Fargate and GKE Autopilot. The transparent variant simply cannot run
there. **V1 action:** verify per-cluster before committing to transparent
mode. If the target environment doesn't permit `NET_ADMIN`, explicit mode is
the only option.

### IPv6 must be handled separately

`iptables` is IPv4-only. We disable IPv6 via two mechanisms:

1. `sysctl net.ipv6.conf.all.disable_ipv6=1` (in compose `sysctls:`)
2. `ip6tables -P OUTPUT DROP` (in `iptables-init/setup.sh`)

The sysctl is the load-bearing one; ip6tables is suspenders. **V1 action:**
in Kubernetes, ensure pod-level IPv6 disable + NetworkPolicy for v6 if the
cluster supports it.

### UDP / QUIC / HTTP/3 is rejected wholesale

We don't inspect QUIC. The transparent variant rejects all UDP except DNS.
The explicit variant blocks UDP because the L1 internal network has no
route. **User-facing impact:** HTTP/3 is unsupported. Document this in any
Craft user docs that mention which protocols agents can use.

### DNS for unregistered hosts

In the PoC, demos use mock hostnames (`api.allowed.example`) that resolve
via `extra_hosts` to TEST-NET-3 IPs. The broker has a fallback
`unregistered_upstream_url` so pass-through demos work. In V1, unregistered
hosts (with default-deny=false) need a real DNS path — the proxy will
resolve them normally. The PoC's `upstream_url` override field becomes
optional.

## Trust / TLS

### Single shared Onyx CA

The PoC mints one CA at boot and uses it across all sandboxes. Cloudflare
Sandboxes use a per-sandbox ephemeral CA; the blast radius is much better
(a leaked CA only compromises one sandbox). **V1 action:** worth
reconsidering for V1 production. Per-sandbox CA adds startup cost and
broker complexity; the trade-off is not clear without measured numbers.

### Cert pinning is fail-closed, no SNI-tunnel fallback

If a client pins to its own CA (demo 04), the handshake fails. We
deliberately do not implement the new doc's "SNI-only opaque tunnel"
fallback, because that path would require the sandbox to hold the upstream
credential — defeating the whole design (F5 in the legacy plan).

If a pinned upstream genuinely needs reach, that's a different mechanism:
per-service sidecar with the credential, or an MCP-style broker for that
one host. Out of scope here.

### CA rotation

Not implemented. The CA is generated once at first boot and persists. V1
will need to plan for rotation (rolling restarts with new CAs across the
sandbox fleet, or per-sandbox ephemeral CAs which sidestep the question).

## Authentication

### Transparent mode auth is a fixed token in v0

In v0, transparent-mode requests all use `TRANSPARENT_DEFAULT_TOKEN`
(env-configured). V1 must derive a session identity from source IP / pod
metadata / SPIFFE / similar. Demo 07 (bad session token) SKIPs in
transparent mode because of this.

### Session tokens are pre-shared in v0

The proxy has `VALID_SESSION_TOKENS` as a comma-separated env var. V1
replaces this with a lookup against Craft's session store.

## Protocol coverage

### HTTP/2, gRPC, WebSocket upgrade paths

mitmproxy handles all three, but we don't write demo scenarios for them
in v0. Anything beyond plain HTTP/1.1 + TLS is unverified.

### Body inspection / classification

Classification in v0 is method+path only. GraphQL operation-name inspection
and JSON body inspection are V1.

### File uploads / large bodies

Not exercised. mitmproxy by default buffers bodies; for streaming uploads
this could be a memory concern at scale.

## Operational

### Audit-log persistence

v0 emits JSON to stdout; `docker logs` is the only sink. V1 needs:

- Persistent storage (PostgreSQL or object store)
- Schema versioning
- Retention policy
- A way to correlate audit events with Craft session IDs

### No metrics / monitoring / alerting

v0 has no Prometheus / OpenTelemetry / etc. Operations on a v0 deployment
is "tail the proxy logs."

### Single proxy pod scaling profile

Long-lived TCP from a single sandbox pins to a single proxy pod. A
sandbox bursting against the broker hammers one pod, not the fleet.
Sufficient for V1 throughput envelopes; revisit with real numbers.

### Trust-store coverage in the image

The certifi monkey-patch is the highest-risk piece. Python version drift
could break the patch (certifi path changes, bundle format changes). We
have a build-time assertion (`install_ca.sh` greps for our CA in the
certifi bundle after patching), but V1 should keep watching for this
across Python upgrades.

## Code-class CVEs to keep in mind

### Parser-differential bypasses (Anthropic SOCKS5 CVE class)

Anthropic's sandbox-runtime had two CVEs in their SOCKS5 proxy. The notable
one: `endsWith(".google.com")` in JS, `getaddrinfo()` in C truncates on
`\x00`. Allowlist bypass via `evil.com\x00.google.com`.

We canonicalize hosts in `proxy/validators.py` before any policy
evaluation: reject control chars, `\x00`, CR/LF, percent-encoding, IDN
homographs. Single-language (Python) here, but defense in depth.

### Auth bypass via path traversal

Our broker keys policy on `host` only. If we ever add path-based
allowlists, validators must canonicalize the path (decode percent-encoding,
collapse `.` / `..`) before matching. The PoC doesn't do this because we
don't have path-based rules yet.

## Kubernetes-port-specific findings

The Compose stack was ported to K8s (see [`../k8s/`](../k8s/)). Both runs
end with the same 13 PASS / 5 SKIP / 0 FAIL summary, but two real frictions
showed up that matter for V1.

### `SO_ORIGINAL_DST` doesn't work cross-netns

mitmproxy's transparent mode reads the pre-DNAT destination via
`getsockopt(SOL_IP, SO_ORIGINAL_DST)`. That requires the conntrack entry
to live in the proxy's network namespace.

- In Compose with a shared docker bridge, the syscall happens to succeed
  (returns the proxy's local address). mitmproxy's bookkeeping is happy.
- In Kubernetes the DNAT is in the workload pod's netns and the proxy is a
  separate pod, so the syscall raises ENOENT. mitmproxy treats it as fatal.

We monkey-patched `mitmproxy.platform.original_addr` to fall back to
`csock.getsockname()` when the syscall fails (see
[`../proxy/server.py`](../proxy/server.py)). Our addon doesn't need the
original destination — SNI + broker `upstream_url` are sufficient — so the
fallback is safe.

**V1 action:** decide between the monkey-patch (small, ugly, works) and
running the proxy as a sidecar in the same pod as the workload (Istio's
pattern: shared netns means SO_ORIGINAL_DST works natively, with the cost
that every sandbox carries a proxy container). Sidecar is the cleaner
long-term answer.

### kindnet doesn't enforce NetworkPolicy

`kind`'s default CNI doesn't enforce NetworkPolicy. The policies in
[`../k8s/70-networkpolicies.yaml`](../k8s/70-networkpolicies.yaml) are
declarative but advisory under kindnet. Transparent mode is unaffected
(iptables is the enforcement layer); explicit mode in kindnet has only the
cooperative-client guarantee (HTTPS_PROXY env). Under any production CNI
(Calico / Cilium / AWS VPC CNI with policy mode), policies are enforced.

**V1 action:** confirm the target cluster's CNI enforces NetworkPolicy
before relying on explicit mode for L1 isolation.

### `kubectl exec` adds its own stderr line on non-zero

`docker exec`'s exit status is the inner command's, with no extra noise.
`kubectl exec` prints `command terminated with exit code N` to stderr on
any non-zero. The demo helper `dx_safe` had to be taught to drop the
runtime's stderr (workload commands that need their own stderr captured
do their own `2>&1` inside `sh -c`). No production V1 implication; just a
gotcha for anyone writing similar test runners.

## What V1 has to do

1. Wire `CraftInterceptedService` table + alembic migration.
2. Replace `services.yaml` + `secrets/` directory with DB-backed lookup
   (broker becomes thin shim over Onyx DB code under `backend/onyx/db/`).
3. Replace pre-shared `VALID_SESSION_TOKENS` with Craft session lookup.
4. Promote `k8s/` manifests into a Helm chart; pick sidecar-vs-deployment
   for the proxy based on the SO_ORIGINAL_DST decision above.
5. Approval workflow (pause/resume, idempotency-keyed replay,
   `CraftEgressApprovalSnapshot`).
6. Audit-log persistence.
7. Per-cluster decision on explicit vs. transparent based on `NET_ADMIN`
   availability.
8. Per-sandbox ephemeral CA evaluation.
