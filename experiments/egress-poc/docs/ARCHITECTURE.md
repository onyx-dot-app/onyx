# Architecture

This document is the technical companion to the top-level [README](../README.md).
It explains the layered defense, why each layer is necessary, the explicit
vs. transparent comparison, and the load-bearing pieces of each component.

## Three enforcement layers

We do not pick a single mechanism. We stack three so that any single failure
gets caught by another:

| Layer | Mechanism | What it catches |
|-------|-----------|-----------------|
| **L1** | Docker `internal: true` network (Compose) / K8s NetworkPolicy (V1) | Code that ignores `HTTPS_PROXY` and tries raw TCP/UDP to anywhere |
| **L2** | `HTTPS_PROXY` env vars (Variant A) OR iptables OUTPUT DNAT (Variant B) | Cooperative HTTP clients (A) or any HTTP client whether cooperative or not (B) |
| **L3** | mitmproxy + addon stack | All HTTP semantics: authn, classification, policy, credential injection, audit |

L1 is the load-bearing layer in Variant A. Code that ignores
`HTTPS_PROXY` and opens a raw socket simply has no path: there is no route
to anything except the proxy.

L2/Variant B is the load-bearing layer if you assume the workload is
actively hostile (not just careless). DNAT redirects traffic *regardless*
of whether the client tries to use the proxy or not.

L3 is where every credential decision and audit event lives. L1 and L2
get traffic to the proxy; L3 decides what the proxy does with it.

## Why ship both Variant A and Variant B

Industry survey, summarized:

- **Anthropic Managed Agents** ships Variant A (explicit + TCP firewall). Ten
  env vars, blocked direct egress, vault outside the sandbox. Same
  architecture as our default.
- **Cloudflare Sandboxes** (GA April 2026) ships Variant B (transparent
  TPROXY/nftables), with per-sandbox ephemeral CAs.
- **E2B, Modal, Daytona** vary in fidelity. None mediate credentials inside
  TLS the way Anthropic and Cloudflare do.
- **Stripe Smokescreen** is SNI-only ACL, no MITM. Built for SSRF prevention
  not credential mediation; different problem.

The legacy Onyx plan lands on Variant A. The new draft argues for Variant B
on the premise that we cannot trust the code to cooperate. Both are
defensible. Rather than relitigate, this PoC ships both as compose overlays
and lets the team A/B them empirically before committing for V1.

My prior: Variant A wins on operational simplicity for the same security
guarantee (because L1 already delivers "workload can't bypass"). Variant B
wins if your runtime ships binaries that ignore `HTTPS_PROXY` *and* hit
addresses outside your `internal: true` network's reach (e.g., something
breaks out of the namespace). The team gets to decide after seeing both
run.

## Component deep dives

### proxy/

mitmproxy used as a **library**, not the CLI. We import
`mitmproxy.options.Options` and `mitmproxy.tools.dump.DumpMaster`, attach a
single composed addon (`EgressAddon`), and run the asyncio loop ourselves.

Three listeners, one process:
- `regular@0.0.0.0:8444` — explicit-mode HTTP proxy
- `transparent@0.0.0.0:8443` — transparent-mode TLS
- `transparent@0.0.0.0:8081` — transparent-mode plain HTTP

The addon implements the seven-step pipeline:

1. `tls_clienthello` — extract + validate SNI. Empty / control-char SNI →
   `ignore_connection`, audit `denied: no_sni`.
2. `http_connect` — parse `Proxy-Authorization` for explicit-mode CONNECTs.
   Bad token → 407, terminate tunnel. Good token → bind to client_conn.
3. `request` — host validation (parser-diff defense), authn (transparent
   mode synthesizes a default token), strip `Proxy-Authorization`, audit
   `received`, call broker for decision.
4. Strip headers (per broker response) — always, even on passthrough — then
   inject the broker-supplied headers.
5. Upstream override — if the broker returned `upstream_url`, rewrite
   `flow.request.host` / `port` / `scheme` while preserving the original
   `Host` header so the upstream sees what the client intended.
6. mitmproxy forwards to the (possibly rewritten) upstream.
7. `response` — close the audit trail.

Cache: two `TTLCache`s, one for allow (30s) and one for deny (5s), keyed by
`(session_token, scheme, host, method, path_prefix_8_segments)`. Conservative
to absorb chatty agents without staleness.

CA: generated once by `ca/gen-ca.sh`. Private key Fernet-encrypted at rest;
the Fernet key is derived from `ENCRYPTION_KEY_SECRET` via SHA-256. The
proxy decrypts on boot, writes the combined PEM to mitmproxy's confdir, and
mitmproxy mints leaf certs per host from that anchor.

### broker/

A ~150-line FastAPI service. One endpoint: `POST /policy/evaluate`. Reads
`services.yaml` at startup, looks up the requested host, optionally reads
a secret from `secrets/<file>`, returns the contract.

The broker is the *only* component that reads the secrets directory. The
proxy gets back already-rendered `inject_headers`; it never sees the raw
secret.

Frozen contract — see the README in [`../broker/main.py`](../broker/main.py)
for the exact `EvaluateRequest` / `EvaluateResponse` shapes.

The PoC adds one field (`upstream_url`) that the legacy plan didn't have:
it lets the proxy route mock hostnames (`api.allowed.example`) to the
mock-upstream container without needing real DNS. In V1 this field is
optional; the proxy can resolve normally if it isn't set.

### sandbox/

One Debian-based image, two entrypoints (`entrypoint-explicit.sh`,
`entrypoint-transparent.sh`). The image installs:

- OS trust store: `update-ca-certificates` after dropping `ca.crt` into
  `/usr/local/share/ca-certificates/`.
- certifi bundle patch: append our PEM to the file `certifi.where()` returns,
  with a runtime assertion that the patch survives Python version drift.
- Node, Java, etc.: not installed in v0 — Node trust comes from
  `NODE_EXTRA_CA_CERTS` env var (set in compose), Java is absent.

Capabilities: `cap_drop: [ALL]` on both sandboxes. IPv6 disabled via
sysctls. Mock hostnames resolve to TEST-NET-3 IPs (RFC 5737) via
`extra_hosts` so direct-connect demos can fail at routing, not DNS.

### iptables-init/

Alpine + iptables + ip6tables. `setup.sh` shares the sandbox's netns
(via `network_mode: "service:sandbox-transparent"`), installs DNAT
REDIRECT for TCP/80→proxy:8081 and TCP/443→proxy:8443, allows loopback
and DNS, rejects everything else, blocks IPv6 outright. Writes
`/state/ready` to a shared volume; the workload entrypoint waits for that
file before exec'ing the real workload.

This pattern (init container does the privileged thing; main container
has no privileges) mirrors how Kubernetes does it. Compose's equivalent
is `depends_on` with `network_mode: "service:X"`.

### Demo scripts

Each demo is ~20 lines, takes the sandbox short name as `$1`, sources
`_lib.sh` for shared helpers, and exits 0 (PASS), 2 (SKIP), or anything
else (FAIL).

The runner iterates over both sandboxes per demo and prints a results
matrix. The two columns are independent — failures in one mode don't
affect the other.

## Mode comparison (the question that prompted both variants)

| Property | Explicit | Transparent |
|----------|----------|-------------|
| Cooperative HTTP clients honor proxy | yes (via env vars + trust-store wiring) | yes (via DNAT, regardless of env) |
| Non-cooperative binaries that ignore env | blocked by L1 (no route) | redirected by L2 (DNAT) |
| Raw TCP to random IPs | blocked by L1 | redirected by L2 → proxy denies on missing SNI |
| UDP / QUIC / HTTP/3 | blocked by L1 | blocked by L2 reject rule |
| IPv6 | blocked by sysctl + L1 (no v6 net) | blocked by sysctl + ip6tables |
| Requires `NET_ADMIN` in cluster | no | yes (init container only) |
| Works on EKS Fargate / GKE Autopilot | yes | no (no `NET_ADMIN`) |
| Auth model | `Proxy-Authorization: Basic session:<token>` | source-IP / pod identity (V1 design) |
| Operational complexity | low (env vars + trust store) | higher (DNAT + init container + workload identity) |

## Where this lands vs. the new doc

| New doc proposal | This PoC | Reason |
|---|---|---|
| Transparent iptables REDIRECT only | Both — explicit + L1 is default; transparent ships as a parallel overlay | Explicit + L1 already delivers "can't bypass" with less operational complexity. Transparent is shipped so the team can A/B. |
| MITM-failure fallback: SNI-only opaque tunnel | Block, always | SNI-only tunnel requires the sandbox to hold the credential, defeating the design. |
| Authz inline in the proxy addon | Separate broker service | Single-purpose: the broker is the only decrypter. Easier to lock down. |
| "~40 lines of async Python" | ~250-line addon + ~150-line broker + tests | Realistic. |
| Tenant attribution undefined | Session token in `Proxy-Authorization`; tenant_hint field in broker request | Same shape Anthropic and the legacy Onyx plan use. |
| Single mitmproxy pod scaled horizontally | Same, but documented that long-lived TCP from a single sandbox pins to one pod | Honest about scaling profile; sufficient for V1 with throughput data later. |
