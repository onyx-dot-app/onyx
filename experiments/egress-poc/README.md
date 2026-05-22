# Egress Interception PoC for the Craft Sandbox

A v0 proof-of-concept for Craft's egress story: arbitrary code in a sandbox
can reach the external services Onyx has credentials for, **without ever
holding those credentials itself**, and cannot bypass the proxy that does the
mediation.

This is a *scratch experiment*: dummy containers talking to each other, no
Onyx integration yet. The goal is to prove the architecture end-to-end so
the V1 integration into Craft can lift it with confidence.

The full plan that produced this PoC lives at
[`~/.claude/plans/breezy-leaping-marble.md`](../../../.claude/plans/breezy-leaping-marble.md)
(in the operator's home, not the repo).

## What this proves

1. **L1: TCP-level isolation works.** A workload joined only to an
   `internal: true` Docker network cannot reach anything but the proxy.
   Direct-connect attempts fail at routing in explicit mode.
2. **L2: Two steering mechanisms.**
   - *Explicit:* `HTTPS_PROXY` env vars across ten siblings + trust-store
     wiring (OS + certifi + Node) get every cooperative HTTP client to
     transit the proxy.
   - *Transparent:* iptables OUTPUT-chain DNAT redirects TCP/80 and TCP/443
     to the proxy from outside the workload's control, and rejects
     everything else. Installed by an init container with `NET_ADMIN`;
     workload has no `NET_ADMIN` so the rules are tamper-resistant.
3. **L3: TLS MITM + credential injection.** mitmproxy generates a leaf cert
   per host signed by the Onyx CA. The credential broker is the only
   component that reads the secrets directory; the proxy gets back
   `{allow, inject_headers, strip_headers, upstream_url}` per request.
4. **Fail-closed:** missing/invalid SNI, broker timeout, cert pinning on the
   client side, and unregistered host with default-deny all result in blocks,
   not silent allows.
5. **Side-by-side A/B.** Both steering variants ship as compose overlays so
   the team can compare operational and security deltas directly before
   choosing one for V1.

## What this does NOT prove (out of scope for v0)

See [`docs/KNOWN-GAPS.md`](./docs/KNOWN-GAPS.md) for the full list. Highlights:

- No Onyx integration (CraftSecret table, alembic migration, sandbox-manager
  wiring) — V1 work.
- No HTTP/2, gRPC, or WebSocket demo scenarios.
- No approval workflow (pause / resume / replay).
- No per-sandbox ephemeral CAs (Cloudflare-style; v0 uses a shared Onyx CA).
- No gVisor / Firecracker sandbox boundary — orthogonal, not in this PoC.

A Kubernetes port lives under [`k8s/`](./k8s/). It deploys the same five
images into a `kind` cluster and re-runs the same 9 demos with the same
result. See [`k8s/README.md`](./k8s/README.md) for the manifest layout,
the `SO_ORIGINAL_DST` monkey-patch we needed, and the kindnet caveat.

## Architecture (90-second tour)

```
┌──────────────────────────────────┐  ┌──────────────────────────────────┐
│ sandbox-explicit                 │  │ sandbox-transparent              │
│                                  │  │                                  │
│ env HTTPS_PROXY=...:8444 + 9     │  │ no proxy env vars                │
│ trust: Onyx CA in OS + certifi   │  │ iptables (init container,        │
│        + NODE_EXTRA_CA_CERTS     │  │   NET_ADMIN, runs once):         │
│                                  │  │   nat OUTPUT 80→proxy:8081       │
│ no NET_ADMIN, no DB, no secrets  │  │   nat OUTPUT 443→proxy:8443      │
│ net: sandbox-explicit-net        │  │   REJECT everything else         │
│      (internal: true)            │  │ net: sandbox-transparent-net     │
└─────────────────┬────────────────┘  └─────────────────┬────────────────┘
                  │ proxy:8444                          │ proxy:8443 / 8081
                  └────────────────────┬────────────────┘
                                       ▼
       ┌─────────────────────── proxy ─────────────────────────────┐
       │ mitmproxy library, three listeners, shared addon stack:   │
       │   - SNI / Host validation (parser-diff defense)           │
       │   - Proxy-Authorization (explicit only)                   │
       │   - broker call: decision + inject_headers + upstream_url │
       │   - strip-then-inject header pipeline                     │
       │   - on-the-fly leaf certs signed by Onyx CA               │
       │   - CA private key Fernet-encrypted at rest               │
       │   - audit: one JSON event per lifecycle transition        │
       └─────────────────┬─────────────────────────┬───────────────┘
                         │                         │
                         ▼                         ▼
              ┌────────────────────┐      ┌──────────────────────┐
              │ broker (FastAPI)   │      │ upstream (FastAPI)   │
              │ services.yaml +    │      │ ~30-line echo;       │
              │ secrets/ dir       │      │ proves injection by  │
              │ POST /policy/      │      │ echoing headers back │
              │      evaluate      │      │                      │
              └────────────────────┘      └──────────────────────┘
```

Three Docker networks. The two sandbox nets are `internal: true` (no egress
to anything but the proxy). The proxy is on all three; the broker and
upstream are only on `egress-net`.

## Running

```bash
# 1. Generate CA + build + start
make up

# 2. Run all 9 demos against both sandboxes (about 30 seconds)
make demo

# 3. Interactive poking
make shell-explicit
make shell-transparent

# 4. Watch the audit stream
make logs-proxy

# 5. Tear down
make down
```

Expected `make demo` output (this is the actual output as of the last run):

```
Demo                                          EXPLICIT    TRANSPARENT
----                                          --------    -----------
01 allowed host + credential injection        PASS        PASS
02 denied host                                PASS        PASS
03 unregistered host passthrough              PASS        PASS
04 cert-pinned client fails closed            PASS        PASS
05 direct TCP (--noproxy)                     PASS        PASS
06 raw socket to random IP                    PASS        PASS
07 bad session token -> 407                   PASS        SKIP
08 missing SNI blocked                        SKIP        PASS
09 transparent DNAT works                     SKIP        PASS
```

13 PASS, 5 intentional SKIPs, 0 FAIL. `make demo` exits 0.

`SKIP` in transparent mode for demo 07 is intentional: transparent mode
doesn't use Proxy-Authorization (auth is by source identity, designed in V1).
`SKIP` in explicit mode for demos 08/09 is similarly intentional — they
exercise transparent-only code paths.

Manual smokes (also passing, run after `make up`):

```bash
# Python requests honors the proxy and the patched certifi bundle.
docker exec egress-poc-sandbox-explicit python3 -c "
import requests, json
r = requests.get('https://api.allowed.example/v1/whoami')
print(r.json()['headers']['authorization'])
"
# -> Bearer poc-secret-allowed-service-bearer-token   (broker-injected)

# Sandbox sees Onyx-issued leaf cert, not the real cert.
docker exec egress-poc-sandbox-explicit sh -c \
    "curl -v https://api.allowed.example/ 2>&1 | grep -E 'subject:|issuer:'"
# -> subject: CN=api.allowed.example
# -> issuer:  O=Onyx; CN=Onyx Egress PoC TLS Inspection CA
```

## Repository layout

```
egress-poc/
  README.md                          <- this file
  docker-compose.yml                 <- base (proxy + broker + upstream + nets)
  docker-compose.explicit.yml        <- overlay: sandbox-explicit
  docker-compose.transparent.yml     <- overlay: sandbox-transparent + iptables-init
  Makefile                           <- up / down / demo / shell / logs targets
  ca/
    gen-ca.sh                        <- one-shot CA generator, idempotent
    .gitignore                       <- ignores ca.crt / ca.key.enc
  proxy/                             <- mitmproxy + addon stack
  broker/                            <- FastAPI policy + secrets store
  sandbox/                           <- shared sandbox image + two entrypoints
  iptables-init/                     <- transparent-mode init container
  upstream/                          <- mock upstream (echoes request back)
  demos/                             <- 9 demo scripts + runner.sh
  k8s/                               <- Kubernetes port (mirrors compose stack)
    README.md                        <- K8s-specific docs + kindnet caveat
    Makefile                         <- up / down / demo / shell / logs targets
    *.yaml                           <- Namespace / Deployments / Pods / NetworkPolicies
  docs/
    ARCHITECTURE.md                  <- detailed design notes + mode comparison
    KNOWN-GAPS.md                    <- everything we know we don't handle
    GLOSSARY.md                      <- networking / TLS jargon used here
```

## Pointers

- Plan that produced this: `~/.claude/plans/breezy-leaping-marble.md`
- Legacy in-repo design: `backend/.../docs/craft/legacy/interception.md`
- New draft design: `~/Downloads/egress-interception-design.md`
- This PoC's deeper design notes: [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)
- Known limitations: [`docs/KNOWN-GAPS.md`](./docs/KNOWN-GAPS.md)
- Networking / TLS jargon used in this PoC: [`docs/GLOSSARY.md`](./docs/GLOSSARY.md)
