# Local Kubernetes Development

How to develop Onyx against a local Kubernetes cluster on your laptop, with the
vscode debugger attached to api_server / celery / web.

This is an alternative to the default dev path (docker-compose deps +
`SANDBOX_BACKEND=local`), not a replacement. Use it when you're working on code
that only makes sense inside a real cluster.

## When you need this

Most Onyx development does **not** require a local k8s cluster. The default
path in [CONTRIBUTING.md](../../CONTRIBUTING.md) — docker-compose for the deps,
vscode debugger for the application, `SANDBOX_BACKEND=local` — is faster and
matches what 90% of the codebase exercises.

Today the only feature that needs this setup is **Onyx Craft (build mode)**
with `SANDBOX_BACKEND=kubernetes`: sandboxes are real pods (services, PVCs,
in-pod daemons, cluster-internal DNS), and any work that touches the pod
spec, the sandbox image, or the cluster-side push / auth paths has to be
exercised on a real cluster.

If you're not working on Craft, stop here and use the default dev path.

## Prerequisites

Tools (all available via `brew` on macOS):

- **`kind`** — local kubernetes-in-docker
- **`helm`** — chart deploys
- **`kubectl`** — cluster CLI
- **`telepresence`** — host ↔ cluster bridge (only required if you want to run
  application processes on the host instead of in the cluster)
- **Docker Desktop** running, with at least 8 CPU / 16 GB allocated to the VM

```bash
brew install kind helm kubectl telepresence
```

The CONTRIBUTING.md prerequisites (Python 3.11, uv, Node.js 22, the venv,
`.vscode/.env`) all still apply — k8s mode adds to that setup, it doesn't
replace it.

## Running from vscode

All cluster lifecycle and telepresence commands are also exposed as vscode
tasks (Cmd+Shift+P → "Tasks: Run Task"):

- `k8s: cluster up`
- `k8s: cluster down (full teardown)`
- `k8s: helm uninstall (keep cluster + data)`
- `k8s: telepresence connect`
- `k8s: telepresence intercept api_server`
- `k8s: telepresence quit`

You can do the whole loop without leaving the editor.

## One-time setup

### 1. Bring up the cluster

```bash
deployment/helm/dev/k8s-up.sh
```

Or run the **`k8s: cluster up`** task from vscode.

This is idempotent and does roughly:

- `kind create cluster --name onyx-dev` (if it doesn't exist)
- Switches kubectl to the `kind-onyx-dev` context
- **Refuses to run unless the current context is exactly `kind-onyx-dev`**
  (or whatever you pass via `--cluster-name`). The `onyx` namespace exists
  in our prod EKS clusters too, and you might have other kind clusters for
  other projects — neither namespace nor a loose `kind-*` match would be
  safe, so the script demands an exact context match
- `helm dependency update` on the Onyx chart
- `helm upgrade --install onyx … -f values-localdev.yaml` into namespace `onyx`
- Generates an OpenSearch admin password on first install and stores it in the
  `onyx-opensearch` Secret

Watch the pods come up:

```bash
kubectl -n onyx get pods -w
```

Expected steady state: ~12–15 pods, all `Running`. Vespa and CNPG-postgres are
the slowest to ready (1–3 minutes).

#### Known issue: CNPG operator on Docker Desktop

Chris hit this in Dec 2025: the CloudNativePG operator's `unable to setup PKI
infrastructure: no operator deployment found` error. It's a known interaction
between the CNPG chart and Docker Desktop's kubernetes-in-docker (#eng-infra,
2025-12-01). If you hit it:

- Switch to `kind` instead of Docker Desktop's bundled k8s
- Or use a deployed dev cluster (`st-dev`) and skip the local cluster entirely

### 2. Wire your host to the cluster

You have two options. Pick based on what you're developing.

**Option A — `telepresence connect`** (host gets cluster DNS)

```bash
telepresence helm install     # one-time, installs traffic-manager
telepresence connect -n onyx
```

After this, `*.svc.cluster.local` resolves from your laptop, and your local
api_server can reach in-cluster postgres / redis / sandbox pods directly. The
cluster sees your local process's traffic as coming from the
`traffic-manager` pod.

**Sufficient for:** sandbox provisioning and most Craft work.

**Not sufficient for:** features that depend on the **source pod's identity**
from the cluster's perspective — sandbox pods seeing requests as coming from
`app.kubernetes.io/name: onyx-api-server` (NetworkPolicies, pod-selector
auth), env vars injected from k8s Secrets into the api_server pod (e.g. an
upcoming `ONYX_SANDBOX_PUSH_SECRET`), etc. Use Option B for those.

**Option B — `telepresence intercept`** (replaces the api_server pod with your laptop)

```bash
telepresence intercept onyx-api-server \
  --namespace onyx \
  --port 8080:8080 \
  --env-file .vscode/.env.k8s
```

Installs a traffic-agent sidecar in the real api_server pod, routes inbound
traffic to your laptop, and dumps the pod's env into `.vscode/.env.k8s`. From
the cluster's perspective, your local process **is** the api_server pod —
labels, secrets, service account, all of it.

**Use this when:** you're working on Craft features that exercise pod
identity from the cluster side — NetworkPolicies between api_server and
sandbox pods, k8s Secret injection, service-account-scoped behavior.

### 3. Run your local processes

Open the vscode debug panel and run **"Web / Model / API (k8s)"** (or
**"Run All Onyx Services"** if you also need celery — celery configs read from
`.vscode/.env`, which is fine since they don't need to be intercepted in most
flows).

The `API Server (k8s)` profile sources `.vscode/.env.k8s` (the file
telepresence wrote) and sets `SANDBOX_BACKEND=kubernetes`. Everything else is
identical to the standard `API Server` profile.

Visit `http://localhost:3000` in a browser. The web server runs locally and
talks to the locally-running api_server (intercepted from the cluster).

## Iteration loop

The big iteration-time matrix:

| What you changed | Cycle time | What to do |
|---|---|---|
| Python in api_server / celery / model_server | ~instant | uvicorn / debugpy reloads. No cluster touch. |
| Frontend (`web/`) | ~instant | Next.js HMR. |
| Helm chart templates / values | 10–30s | `deployment/helm/dev/k8s-up.sh` (it's `helm upgrade --install`, idempotent). |
| Backend image (`Dockerfile`) | 60–180s | `docker build backend/` → `kind load docker-image …` → `kubectl rollout restart deployment/<thing>`. |
| Sandbox image (`backend/onyx/server/features/build/sandbox/kubernetes/docker/`) | 60–180s | Same — build, `kind load`, restart any running sandbox pods. New sandboxes pick up the new image immediately. |

### Building and loading local images

```bash
# Backend image
docker build -t onyxdotapp/onyx-backend:dev backend/
kind load docker-image onyxdotapp/onyx-backend:dev --name onyx-dev

# Tell the chart to use it (only needed once per session)
helm upgrade onyx deployment/helm/charts/onyx \
  -n onyx \
  -f deployment/helm/charts/onyx/values-localdev.yaml \
  --set api.image.tag=dev \
  --set api.image.pullPolicy=IfNotPresent \
  --set celery_shared.image.tag=dev

# Or restart the deployments to re-pull
kubectl -n onyx rollout restart deployment/onyx-api-server
```

The `kind load docker-image` step ships the image directly to the kind node's
containerd — no registry push, no pull credentials.

### Avoid this loop when you can

For pure-python work that doesn't depend on cluster-only behavior, develop the
underlying logic against unit tests or external-dependency-unit tests first,
and only round-trip through the cluster for the parts that need it. Sandbox
safe-extract logic, push wire format, tarball round-trips — all testable
against a temp dir on your laptop. See `backend/tests/README.md` for the test
matrix.

## Data persistence

Persistence stays **enabled** in `values-localdev.yaml`, just with shrunk PVC
sizes. In kind, PVCs are host-paths inside the kind node container, so:

| Action | Data survives? |
|---|---|
| `helm upgrade` (any chart change) | yes |
| `kubectl rollout restart …` | yes |
| Docker Desktop restart / laptop reboot | yes (kind cluster restarts with its data) |
| `k8s-down.sh --keep-cluster` (helm uninstall, cluster kept) | yes (PVCs left intact for the next install) |
| `k8s-down.sh` (full teardown — `kind delete cluster`) | no (cluster and PVCs gone) |

So your test users, indexed connectors, file uploads, etc. survive normal
iteration. The only thing that wipes them is an explicit full teardown.

If you do need a clean slate without nuking the cluster:

```bash
kubectl -n onyx delete pvc --all
deployment/helm/dev/k8s-up.sh
```

## Tear-down

Wipe everything:

```bash
deployment/helm/dev/k8s-down.sh
```

Keep the kind cluster but uninstall Onyx (faster re-install, data preserved):

```bash
deployment/helm/dev/k8s-down.sh --keep-cluster
```

Stop telepresence:

```bash
telepresence quit
```

## Common issues

**Pods stuck `Pending`** — almost always resources. Bump Docker Desktop's
allocation (Settings → Resources). The `values-localdev.yaml` overlay targets
~8 CPU / 12 GB for the chart; if Docker has less, eviction kicks in.

**Vespa stuck `0/1 Ready`** — give it 2–3 minutes on first install. The Vespa
container takes a long time to converge. If it still isn't ready after 5
minutes: `kubectl -n onyx describe pod da-vespa-0` and check events.

**CNPG postgres won't start with "no operator deployment found"** — see the
Docker Desktop note above. Use kind.

**Helm install fails with "context deadline exceeded"** — chart dependency
update timed out. Re-run `k8s-up.sh`; it's idempotent.

**`telepresence intercept` says "ambiguous workload"** — your namespace flag
isn't being read. Pass `--namespace onyx` explicitly.

**Sandbox pod can't be reached from local api_server** — if a NetworkPolicy
is enforcing api-server-only ingress, you're on Option A (`connect`) and the
traffic-manager source is being blocked. Switch to Option B (`intercept`),
or turn the relevant NetworkPolicy off in your override values for dev.

**Kubeconfig clashes with a remote prod context** — kind writes to your
default `~/.kube/config`. To isolate:

```bash
export KUBECONFIG=$HOME/.kube/onyx-dev-config
kind create cluster --name onyx-dev --kubeconfig $KUBECONFIG
```

Then point vscode at the same `KUBECONFIG` in `.vscode/.env.k8s`.

## What's checked in

| Path | Purpose |
|---|---|
| `deployment/helm/charts/onyx/values-localdev.yaml` | Helm overlay: shrunk PVCs and resources, no ingress / monitoring / code-interpreter. |
| `deployment/helm/dev/k8s-up.sh` | Idempotent cluster bring-up. |
| `deployment/helm/dev/k8s-down.sh` | Tear-down (full or keep-cluster). |
| `.vscode/launch.json` → `API Server (k8s)`, `Web / Model / API (k8s)` | Debugger profiles that source `.vscode/.env.k8s` and set `SANDBOX_BACKEND=kubernetes`. |
| `.vscode/tasks.json` → `k8s: …` | One-click cluster up/down, telepresence connect/intercept/quit. |
| `.vscode/.env.k8s` | **Not** checked in. Generated by `telepresence intercept --env-file`. |

If you find yourself working around a gap in one of these artifacts, fix the
artifact and update this doc — they're meant to be the canonical setup.

## References

- [CONTRIBUTING.md — Development Setup](../../CONTRIBUTING.md#development-setup) — the default (non-k8s) dev path
- [deployment/helm/README.md](../../deployment/helm/README.md) — chart-maintainer notes (different audience)
- [backend/onyx/server/features/build/sandbox/README.md](../../backend/onyx/server/features/build/sandbox/README.md) — sandbox subsystem
- [Telepresence docs](https://www.telepresence.io/docs/) — connect vs. intercept semantics
- [kind docs](https://kind.sigs.k8s.io/) — local cluster runtime
