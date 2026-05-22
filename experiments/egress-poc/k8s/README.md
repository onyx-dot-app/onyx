# Egress PoC — Kubernetes Port

A K8s manifest layout that mirrors the Compose stack in the parent
directory. Same containers, same broker, same demos — different runtime.

This is what V1 will plug into: the actual Onyx Craft sandbox runs as a
Kubernetes pod (`SANDBOX_BACKEND=kubernetes`), so the egress story has to
work there.

## What's the same

- All five images (`proxy`, `broker`, `upstream`, `sandbox`, `iptables-init`)
  are unchanged from the Compose stack. We `kind load` the locally-built
  images directly into the cluster — no registry push.
- The CA artifacts (`ca/ca.crt`, `ca/ca.key.enc`) are generated once at the
  top level and shared. They get mounted into the proxy via a K8s Secret
  rather than a host volume; the sandbox image still bakes the cert in.
- The 9 demo scripts are unchanged in intent. `_lib.sh` learned an
  `EGRESS_POC_RUNTIME=kubernetes` switch so `dx`/`dx_safe`/`dx_real` resolve
  to `kubectl exec` instead of `docker exec`.

## What's different

| Compose construct                 | K8s analog                                                  |
|-----------------------------------|-------------------------------------------------------------|
| `internal: true` network          | `NetworkPolicy` (egress allowlist) — see kindnet caveat below |
| `service:sandbox-transparent` netns share | initContainer in the same pod (pods share netns by default) |
| `extra_hosts:`                    | `spec.hostAliases:`                                         |
| `cap_drop: [ALL]`                 | `securityContext.capabilities.drop: [ALL]`                  |
| Static IP on a bridge net         | `Service` ClusterIP (resolved at init time via `dig`)       |
| `depends_on`                      | initContainers + readiness probes                           |
| Host volume mount for CA          | `Secret` mounted at `/ca`                                   |

## The SO_ORIGINAL_DST monkey-patch (read this)

mitmproxy's transparent mode reads the original (pre-DNAT) destination of
every incoming TCP connection via `getsockopt(SOL_IP, SO_ORIGINAL_DST)`.
That syscall only works when the proxy's network namespace holds the
conntrack entry that recorded the DNAT — i.e. the DNAT and the listening
socket are in the same netns.

Docker Compose (with everything on one bridge) satisfies that incidentally:
the call succeeds and happens to return the proxy's own local address. K8s
does not: the DNAT happens in the workload pod's netns, the proxy lives in
a different pod, and the syscall raises ENOENT. mitmproxy treats that as
fatal and closes the connection before our addon runs.

[`proxy/server.py`](../proxy/server.py) monkey-patches
`mitmproxy.platform.original_addr` to fall back to `csock.getsockname()`
when the syscall fails. Our addon doesn't need the original destination
(SNI / Host header give it the workload's intended hostname, and the
broker provides the upstream URL), so the fallback is safe. The clean
fix — running the proxy as a sidecar in the workload pod (Istio's pattern)
so both share a netns — is left for V1 if we want it.

## Known kindnet limitation (read this)

`kind` ships with kindnet as its default CNI. **kindnet does not enforce
NetworkPolicy.** The policies in `70-networkpolicies.yaml` are still
declared (and will be enforced under any production CNI — Calico, Cilium,
AWS VPC CNI with policy mode, etc.) but in a stock kind cluster they're
advisory only.

What this means for the demos:

- **Transparent mode is unaffected.** iptables-init enforces at the pod's
  network namespace, independent of CNI. All transparent-mode demos behave
  the same as under Compose.
- **Explicit mode demo 05 (direct TCP --noproxy) is expected to FAIL in
  kindnet.** Without NetworkPolicy enforcement, the sandbox can talk to any
  pod / external IP. Under a policy-enforcing CNI it would PASS. The K8s
  demo runner reports this as `XFAIL` (expected fail under kindnet).
- All other explicit-mode demos PASS, because they exercise the
  cooperative-client path (HTTPS_PROXY env), which works regardless of CNI.

To exercise the explicit-mode L1 isolation in kind, swap kindnet for Calico:

```bash
# Replace kindnet with Calico (one-time, ~3 min to converge).
kubectl delete -n kube-system daemonset kindnet
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.27.0/manifests/calico.yaml
```

Out of scope for v0 — V1 will run on real EKS where this isn't a concern.

## Running

```bash
# 1. Bring up cluster + build + load + apply + wait
make up

# 2. Run the demo suite
make demo

# 3. Interactive shells
make shell-explicit
make shell-transparent

# 4. Watch proxy / broker logs
make logs-proxy
make logs-broker

# 5. Teardown
make down       # destroys the kind cluster entirely
```

## Manifest layout

```
k8s/
  README.md                     <- this file
  Makefile                      <- up / down / demo / shell / logs targets
  kind-config.yaml              <- single-node kind cluster spec
  setup-ca-secret.sh            <- creates egress-poc-ca Secret from ca/ files
  00-namespace.yaml             <- Namespace egress-poc
  20-broker.yaml                <- Deployment + Service
  30-upstream.yaml              <- Deployment + Service
  40-proxy.yaml                 <- Deployment + Service (mounts CA Secret)
  50-sandbox-explicit.yaml      <- Pod (HTTPS_PROXY env, hostAliases)
  60-sandbox-transparent.yaml   <- Pod (initContainer w/ NET_ADMIN, hostAliases)
  70-networkpolicies.yaml       <- per-sandbox egress allowlists
```

## What this lets V1 do

When the Craft sandbox-manager creates a sandbox pod, V1 can:

1. Inject the egress-poc init / NetworkPolicy pattern from `60-sandbox-transparent.yaml`.
2. Mount the per-tenant Onyx CA from a Secret.
3. Wire the proxy `BROKER_URL` to the real Onyx credential broker.
4. Configure `services.yaml` per the registered Craft connectors.

The pod spec is the integration surface. Everything else (broker, proxy,
upstream) is a separate workload that the sandbox doesn't see.

## Pointers

- Top-level architecture: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)
- Known limitations: [`../docs/KNOWN-GAPS.md`](../docs/KNOWN-GAPS.md)
- Networking / TLS jargon: [`../docs/GLOSSARY.md`](../docs/GLOSSARY.md)
- Existing Craft K8s dev workflow: [`/docs/dev/local-kubernetes.md`](/docs/dev/local-kubernetes.md)
