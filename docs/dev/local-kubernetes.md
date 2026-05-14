# Local Kubernetes Development

How to develop Onyx against a local kind cluster, with the vscode debugger
attached to api_server / celery / web.

## When you need this

The default path in [CONTRIBUTING.md](/CONTRIBUTING.md) (docker-compose deps +
vscode debugger + `SANDBOX_BACKEND=local`) is faster and covers ~90% of the
codebase. Use it unless you're working on **Onyx Craft (build mode)** with
`SANDBOX_BACKEND=kubernetes`: sandboxes are real pods, so anything touching
the pod spec, the sandbox image, or the cluster-side push / auth paths must
be exercised on a real cluster.

## Prerequisites

Builds on the CONTRIBUTING.md prereqs (Python 3.11, uv, Node.js 22, the venv,
`.vscode/.env`). Docker Desktop must be running with at least 8 CPU / 16 GB
allocated.

```bash
brew install kind helm kubectl

curl -fLo /opt/homebrew/bin/telepresence \
  https://github.com/telepresenceio/telepresence/releases/latest/download/telepresence-darwin-arm64
chmod +x /opt/homebrew/bin/telepresence
```

The telepresence network daemon needs sudo for DNS + VPN setup. vscode's
preLaunchTask can't answer an interactive prompt, so pick one:

**A. Passwordless sudo (set once)**

```bash
echo "$USER ALL=(ALL) NOPASSWD: /opt/homebrew/bin/telepresence" \
  | sudo tee /etc/sudoers.d/telepresence
sudo chmod 0440 /etc/sudoers.d/telepresence
```

**B. Manual `connect` once per dev session**

One sudo prompt at session start; the daemon stays alive afterward:

```bash
telepresence connect -n onyx
```

## One-time setup

Bring up the cluster:

```bash
deployment/helm/dev/k8s-up.sh
```

Or run the **`k8s: cluster up`** vscode task. The script is idempotent and
refuses to run unless your kubectl context is exactly `kind-onyx-dev` (the
`onyx` namespace also exists in prod EKS).

Watch pods (vespa and CNPG-postgres take a minute or two on first boot):

```bash
kubectl -n onyx get pods -w
```

Install the in-cluster telepresence traffic-manager (once per cluster):

```bash
telepresence helm install
```

The chart pins images to the `:edge` tag in
[`values-localdev.yaml`](/deployment/helm/charts/onyx/values-localdev.yaml)
with `pullPolicy: Always`, so in-cluster pods track nightly builds off `main`
rather than the released `:latest`.

**Known issue: CNPG operator on Docker Desktop k8s.** CloudNativePG fails
with `unable to setup PKI infrastructure: no operator deployment found`
against Docker Desktop's bundled kubernetes. Use kind (the default in
`k8s-up.sh`) or a deployed dev cluster (`st-dev`).

## Daily workflow

### vscode tasks

All cluster + telepresence commands are exposed as tasks (Cmd+Shift+P → Tasks:
Run Task):

- `k8s: cluster up` — bring up or reconcile the cluster.
- `k8s: pause cluster (data preserved)` — stop the kind node container at end of day.
- `k8s: resume cluster` — start it back up; kubelet reconciles pods.
- `k8s: cluster down (full teardown)` — delete the kind cluster and all PVC data.
- `k8s: telepresence connect`, `... intercept api_server`, `... quit`.

### Run your local processes

Open the debug panel and pick **Run All Onyx Services (k8s)** — web + api +
every celery worker + beat. Model server stays in-cluster.

Each `(k8s)` config has `telepresence intercept onyx-api-server` as its
`preLaunchTask`. vscode dedupes the task across the compound, so one run
connects + (re)creates the intercept idempotently. No manual telepresence
invocation needed.

The intercept points cluster ingress to your local api_server using the same
labels, secrets, and service account as the real pod — NetworkPolicies and
pod-selector auth work transparently.

Celery workers aren't intercepted (no inbound HTTP); they reach in-cluster
redis via telepresence's DNS bridge. The chart scales in-cluster celery to 0
so your local workers are the only consumers.

Both api and celery hot-reload — api via uvicorn's `--reload`, celery via
`watchfiles.run_process` (`backend/scripts/dev_celery_reload.py`); breakpoints
work in both because debugpy follows the reloader's fork (`subProcess: true`).

Individual `Celery <name> (k8s)` configs are hidden from the picker
(`presentation.hidden: true`); flip `hidden` to `false` in
`.vscode/launch.json` to run a single worker.

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
wire format, tarball round-trips), drive it from unit /
external-dependency-unit tests against a temp dir. See
[`backend/tests/README.md`](/backend/tests/README.md).

### End of day

Run **`k8s: pause cluster`** (or `docker stop onyx-dev-control-plane`) to stop
the kind node container. PVC data lives inside that container, so postgres,
redis, opensearch, vespa, and minio state all survive. Resume with
**`k8s: resume cluster`** — the kubelet reconciles pods automatically.

Reach for **`k8s: cluster down (full teardown)`** only when you want a clean
slate: it runs `kind delete cluster`, destroying the node container and all
PVC data.

## Data persistence

Persistence is enabled in `values-localdev.yaml` with shrunk PVCs. kind PVCs
are host-paths inside the kind node container.

| Action | Data survives? |
|---|---|
| `helm upgrade` | yes |
| `kubectl rollout restart` | yes |
| Docker Desktop restart / laptop reboot | yes |
| `k8s: pause cluster` / `docker stop` of the node container | yes |
| `k8s: cluster down` / `k8s-down.sh` (full teardown) | no |

Clean slate without nuking the cluster:

```bash
kubectl -n onyx delete pvc --all
deployment/helm/dev/k8s-up.sh
```

## `.env.k8s.local`

`.env.k8s` is regenerated each preLaunchTask run by `telepresence intercept
--env-file`; `.env.k8s.local` is then appended (last-wins). Neither is
checked in.

Start `.env.k8s.local` from your `.vscode/.env`, then **remove** any keys
that should come from the cluster — overriding these breaks DNS or auth into
cluster services:

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

- [CONTRIBUTING.md — Development Setup](/CONTRIBUTING.md#development-setup)
- [deployment/helm/README.md](/deployment/helm/README.md)
- [backend/onyx/server/features/build/sandbox/README.md](/backend/onyx/server/features/build/sandbox/README.md)
- [Telepresence docs](https://www.telepresence.io/docs/)
- [kind docs](https://kind.sigs.k8s.io/)
