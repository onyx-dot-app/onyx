# Local Kubernetes Development

How to develop Onyx against a local kind cluster, with the vscode debugger
attached to api_server / celery / web.

## When you need this

Most Onyx development does **not** need this. The default path in
[CONTRIBUTING.md](../../CONTRIBUTING.md) — docker-compose deps + vscode
debugger + `SANDBOX_BACKEND=local` — is faster and covers ~90% of the codebase.

Today the only feature that requires this setup is **Onyx Craft (build mode)**
with `SANDBOX_BACKEND=kubernetes`: sandboxes are real pods (services, PVCs,
in-pod daemons, cluster-internal DNS), so any work touching the pod spec, the
sandbox image, or the cluster-side push / auth paths must be exercised on a
real cluster.

If you're not working on Craft, stop here.

## Prerequisites

Assumes you already have the CONTRIBUTING.md prereqs (Python 3.11, uv,
Node.js 22, the venv, `.vscode/.env`). Docker Desktop must be running with
at least 8 CPU / 16 GB allocated.

```bash
brew install kind helm kubectl

# OSS telepresence (not the Ambassador/blackbird build).
curl -fLo /opt/homebrew/bin/telepresence \
  https://github.com/telepresenceio/telepresence/releases/latest/download/telepresence-darwin-arm64
chmod +x /opt/homebrew/bin/telepresence

# Passwordless sudo for the telepresence daemon. Required: the daemon needs
# sudo to install DNS resolvers + a VPN interface, and vscode preLaunchTasks
# can't answer an interactive prompt.
echo "$USER ALL=(ALL) NOPASSWD: /opt/homebrew/bin/telepresence" \
  | sudo tee /etc/sudoers.d/telepresence
sudo chmod 0440 /etc/sudoers.d/telepresence
```

## One-time setup

### 1. Bring up the cluster

```bash
deployment/helm/dev/k8s-up.sh
```

Or run the **`k8s: cluster up`** vscode task. The script is idempotent and
refuses to run unless your kubectl context is exactly `kind-onyx-dev` (guards
against pointing at prod EKS, since the `onyx` namespace exists there too).

Watch pods:

```bash
kubectl -n onyx get pods -w
```

Expected: ~12–15 pods `Running`. Vespa and CNPG-postgres take 1–3 minutes on
first boot.

Install the in-cluster traffic-manager once per cluster:

```bash
telepresence helm install
```

#### Known issue: CNPG operator on Docker Desktop k8s

CloudNativePG fails with `unable to setup PKI infrastructure: no operator
deployment found` against Docker Desktop's bundled kubernetes. Use kind (the
default in `k8s-up.sh`) or a deployed dev cluster (`st-dev`).

## Daily workflow

### vscode tasks

All cluster + telepresence commands are exposed as tasks (Cmd+Shift+P → Tasks:
Run Task):

- `k8s: cluster up`
- `k8s: cluster down (full teardown)`
- `k8s: helm uninstall (keep cluster + data)`
- `k8s: telepresence connect`
- `k8s: telepresence intercept api_server`
- `k8s: telepresence quit`

### Run your local processes

Open the debug panel and pick one:

- **Web / API (k8s)** — web + api only. Model server stays in-cluster. Fine
  for most Craft work.
- **Run All Onyx Services (k8s)** — full local stack including every celery
  worker + beat.

Each `(k8s)` config has `telepresence intercept onyx-api-server` as its
`preLaunchTask`. vscode dedupes the task across the compound, so one run
connects + (re)creates the intercept idempotently. No manual telepresence
invocation needed.

The intercept points cluster ingress to your local api_server using the same
labels, secrets, and service account as the real pod — NetworkPolicies and
pod-selector auth work transparently.

Celery workers don't get intercepted (they pull from redis, no inbound HTTP).
They reach in-cluster redis via telepresence's DNS bridge. The chart scales
in-cluster celery to 0 so your local workers are the only consumers.

Both api and celery get hot reload via `watchfiles.run_process`
(`backend/scripts/dev_celery_reload.py`) and breakpoints work in both —
debugpy follows the reloader's fork via `subProcess: true`.

The individual `Celery <name> (k8s)` configs are hidden from the picker
(`presentation.hidden: true`). Surface them by flipping `hidden` to `false`
in `.vscode/launch.json` if you need a single worker.

Every `(k8s)` profile sources `.vscode/.env.k8s` (written by
`telepresence intercept --env-file`) and sets `SANDBOX_BACKEND=kubernetes`.

Visit `http://localhost:3000` once running.

### Iteration loop

| What you changed | Cycle time | What to do |
|---|---|---|
| Python in api_server / celery / model_server | ~instant | uvicorn / debugpy reloads. No cluster touch. |
| Frontend (`web/`) | ~instant | Next.js HMR. |
| Helm chart templates / values | 10–30s | Re-run `k8s-up.sh`. |
| Backend image (`Dockerfile`) | 60–180s | `docker build` → `kind load docker-image` → `kubectl rollout restart`. |
| Sandbox image (`backend/onyx/server/features/build/sandbox/kubernetes/docker/`) | 60–180s | Same. New sandboxes pick up the new image immediately. |

### Building and loading local images

```bash
docker build -t onyxdotapp/onyx-backend:dev backend/
kind load docker-image onyxdotapp/onyx-backend:dev --name onyx-dev

# Point the chart at it (once per session)
helm upgrade onyx deployment/helm/charts/onyx \
  -n onyx \
  -f deployment/helm/charts/onyx/values-localdev.yaml \
  --set api.image.tag=dev \
  --set api.image.pullPolicy=IfNotPresent \
  --set celery_shared.image.tag=dev

kubectl -n onyx rollout restart deployment/onyx-api-server
```

`kind load` ships straight to the kind node's containerd — no registry push.

### Avoid this loop when you can

For logic that doesn't depend on cluster-only behavior (safe-extract, push
wire format, tarball round-trips), drive it from unit / external-dependency-unit
tests against a temp dir. See `backend/tests/README.md`.

## Data persistence

Persistence is enabled in `values-localdev.yaml` with shrunk PVCs. kind PVCs
are host-paths inside the kind node container.

| Action | Data survives? |
|---|---|
| `helm upgrade` | yes |
| `kubectl rollout restart` | yes |
| Docker Desktop restart / laptop reboot | yes |
| `k8s-down.sh --keep-cluster` | yes |
| `k8s-down.sh` (full teardown) | no |

Clean slate without nuking the cluster:

```bash
kubectl -n onyx delete pvc --all
deployment/helm/dev/k8s-up.sh
```

## Tear-down

```bash
deployment/helm/dev/k8s-down.sh                 # wipe everything
deployment/helm/dev/k8s-down.sh --keep-cluster  # uninstall Onyx, keep data
telepresence quit                                # stop the host-side daemon
```

## Common issues

- **Pods stuck `Pending`** — bump Docker Desktop resources. Overlay targets
  ~8 CPU / 12 GB.
- **Vespa stuck `0/1 Ready`** — give it 2–3 minutes. After 5, check
  `kubectl -n onyx describe pod da-vespa-0`.
- **CNPG `no operator deployment found`** — use kind, not Docker Desktop k8s.
- **Helm `context deadline exceeded`** — chart dep update timed out. Re-run
  `k8s-up.sh`.
- **`telepresence intercept` says "ambiguous workload"** — pass
  `--namespace onyx` explicitly.
- **Sandbox pod unreachable from local api_server** — a NetworkPolicy is
  blocking the traffic-manager source. Use intercept (not connect) or disable
  the policy in your override values.
- **Kubeconfig clashes with prod context** — isolate:

  ```bash
  export KUBECONFIG=$HOME/.kube/onyx-dev-config
  kind create cluster --name onyx-dev --kubeconfig $KUBECONFIG
  ```

  Then set the same `KUBECONFIG` in `.vscode/.env.k8s`.

## Files

| Path | Purpose |
|---|---|
| `deployment/helm/charts/onyx/values-localdev.yaml` | Laptop overlay. |
| `deployment/helm/dev/k8s-up.sh` / `k8s-down.sh` | Bring-up / teardown. |
| `.vscode/launch.json` `(k8s)` configs | Debugger profiles. |
| `.vscode/tasks.json` `k8s: …` | One-click cluster + telepresence. |
| `.vscode/.env.k8s` | Generated each preLaunchTask run by `telepresence intercept --env-file`; `.env.k8s.local` is appended last. **Not** checked in. |
| `.vscode/.env.k8s.local` | User-maintained personal env overrides. **Not** checked in. |

### `.env.k8s.local`

Start from your existing `.vscode/.env`, then **remove** any keys that should
come from the cluster — overriding these breaks DNS or auth into cluster
services:

- `POSTGRES_*`, `REDIS_*`, `OPENSEARCH_*`, `VESPA_HOST`
- `S3_*` (MinIO endpoint + creds)
- `MODEL_SERVER_HOST`, `INDEXING_MODEL_SERVER_HOST`
- `INTERNAL_URL`

Also drop `SANDBOX_BACKEND=local`-only keys (`SANDBOX_BASE_PATH`,
`OUTPUTS_TEMPLATE_PATH`, `VENV_TEMPLATE_PATH`,
`PERSISTENT_DOCUMENT_STORAGE_PATH`).

Keep personal vars: API keys (OPENAI, BRAINTRUST, EXA), log levels,
password-rule relaxations, feature flags, OAuth client IDs.

## References

- [CONTRIBUTING.md — Development Setup](../../CONTRIBUTING.md#development-setup)
- [deployment/helm/README.md](../../deployment/helm/README.md)
- [backend/onyx/server/features/build/sandbox/README.md](../../backend/onyx/server/features/build/sandbox/README.md)
- [Telepresence docs](https://www.telepresence.io/docs/)
- [kind docs](https://kind.sigs.k8s.io/)
