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

Follow the four steps below in order. Skipping step 3 (the sandbox image)
is the most common Craft setup failure — sandbox pods can't pull
`onyxdotapp/sandbox:dev` from anywhere, so Build sessions hang.

### 1. Bring up the cluster

```bash
deployment/helm/dev/k8s-up.sh
```

Or run the **`k8s: cluster up`** vscode task. The script is idempotent and
refuses to run unless your kubectl context is exactly `kind-onyx-dev` (the
`onyx` namespace also exists in prod EKS). It also installs the
telepresence traffic-manager once per cluster.

Watch pods (vespa and CNPG-postgres take a minute or two on first boot):

```bash
kubectl -n onyx get pods -w
```

The chart pins images to the `:edge` tag in
[`values-localdev.yaml`](/deployment/helm/charts/onyx/values-localdev.yaml)
with `pullPolicy: Always`, so in-cluster pods track nightly builds off `main`
rather than the released `:latest`.

### 2. Copy `.env.k8s` from the template

```bash
cp .vscode/.env.k8s.template .vscode/.env.k8s
```

Then fill in `<REPLACE THIS>` values (at minimum `GEN_AI_API_KEY`). See
[Set up your `.env.k8s`](#set-up-your-envk8s) below for the full workflow
and what to mirror from `.vscode/.env`.

### 3. Build and load the sandbox image

**Required for Craft (`SANDBOX_BACKEND=kubernetes`).** The chart points
sandbox pods at `onyxdotapp/sandbox:dev`, which is local-only — it isn't on
any registry, so kind's `imagePullPolicy: IfNotPresent` will fail until
you've built it and loaded it into the kind node:

```bash
docker build -t onyxdotapp/sandbox:dev \
  backend/onyx/server/features/build/sandbox/kubernetes/docker
kind load docker-image onyxdotapp/sandbox:dev --name onyx-dev
```

Rebuild + reload when you change anything under that directory. The image
tag (`onyxdotapp/sandbox:dev`) must match `SANDBOX_CONTAINER_IMAGE` in your
`.env.k8s` and the chart's `sandbox.image.*` values.

Verify it's present in the kind node:

```bash
docker exec onyx-dev-control-plane crictl images | grep sandbox
```

### 4. Connect telepresence

```bash
telepresence connect -n onyx
```

This sets up the DNS bridge so your local api_server can resolve
in-cluster services (`onyx-pg-rw`, `onyx-minio`, etc.). The vscode `(k8s)`
launch profiles also run an `intercept` automatically — `connect` here is
only needed if you're driving telepresence outside of vscode.

---

**Known issue: CNPG operator on Docker Desktop k8s.** CloudNativePG fails
with `unable to setup PKI infrastructure: no operator deployment found`
against Docker Desktop's bundled kubernetes. Use kind (the default in
`k8s-up.sh`) or a deployed dev cluster (`st-dev`).

**Recovery: `onyx-sandboxes` namespace exists without Helm ownership.** If a
previous `k8s-up.sh` (or any manual `kubectl create namespace onyx-sandboxes`)
created the sandbox namespace before the chart could, helm install bails out
with `exists and cannot be imported into the current release`. Adopt the
namespace, then re-run `k8s-up.sh`:

```bash
kubectl label   namespace onyx-sandboxes app.kubernetes.io/managed-by=Helm --overwrite
kubectl annotate namespace onyx-sandboxes meta.helm.sh/release-name=onyx --overwrite
kubectl annotate namespace onyx-sandboxes meta.helm.sh/release-namespace=onyx --overwrite
```

## Daily workflow

### vscode tasks

All cluster + telepresence commands are exposed as tasks (Cmd+Shift+P → Tasks:
Run Task):

- `k8s: cluster up` — bring up or reconcile the cluster.
- `k8s: pause cluster (data preserved)` — stop the kind node container at end of day.
- `k8s: resume cluster` — start it back up; kubelet reconciles pods.
- `k8s: cluster down (full teardown)` — delete the kind cluster and all PVC data.
- `k8s: telepresence connect`, `... intercept api_server`, `... quit`.

### Set up your `.env.k8s`

The K8s api_server launch loads env from `.vscode/.env.k8s`. You own this
file end-to-end — the telepresence intercept no longer regenerates it.
Copy from the tracked template:

```bash
cp .vscode/.env.k8s.template .vscode/.env.k8s
```

Then fill in `<REPLACE THIS>` values. **Mirror everything you have in
`.vscode/.env` into this file** — the K8s launch does not read `.env`,
only `.env.k8s`. If you set `GEN_AI_API_KEY` only in `.env`, it won't be
present in K8s mode and you'll hit confusing missing-key errors. The
template's section 1 lists the standard `.env` vars to copy.

**You must also set `SANDBOX_BACKEND=kubernetes`** (included in the
template). This is what flips the api_server from local Docker sandboxes
to in-cluster pod sandboxes. The vscode `(k8s)` launch profiles set it via
their `env:` block as a safety net, but anything that reads `.env.k8s`
directly (CLI scripts, ad-hoc invocations, tests) needs the value to be
in the file too.

`OPENSEARCH_ADMIN_PASSWORD` is the one cluster-random value — leave it as
`<AUTO_FROM_CLUSTER>` in your `.env.k8s`. The `k8s: telepresence intercept
api_server` preLaunchTask reads the `onyx-opensearch` Secret and rewrites
that one line before each launch, so the password stays in sync even
across `k8s-up.sh` reinstalls (which rotate it).

The preLaunchTask fails fast if `.env.k8s` doesn't exist or if the
opensearch Secret can't be read (cluster down), so you'll know immediately
if you missed a step.

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

Every `(k8s)` profile sources `.vscode/.env.k8s` (the file you copied from
`.env.k8s.template`) and sets `SANDBOX_BACKEND=kubernetes`.

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

# Point the chart at it (once per session). Override global.pullPolicy
# only when you're running a locally-built tag like :dev that isn't on
# docker.io — otherwise the localdev default (Always) is what you want
# so the nightly :edge tag refreshes.
helm upgrade onyx deployment/helm/charts/onyx \
  -n onyx \
  -f deployment/helm/charts/onyx/values-localdev.yaml \
  --set global.pullPolicy=IfNotPresent \
  --set api.image.tag=dev \
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

## `.env.k8s`

`.env.k8s` is dev-owned and gitignored. The `k8s: telepresence intercept
api_server` task no longer writes it — copy it once from
`.env.k8s.template` and edit the `<REPLACE THIS>` values. See
[Set up your `.env.k8s`](#set-up-your-envk8s) above for the workflow.

For Craft development, the required vars (already in the template) are:

```
ENABLE_CRAFT=true
SANDBOX_BACKEND=kubernetes
SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:dev
SANDBOX_API_SERVER_URL=http://onyx-api-service.onyx.svc.cluster.local:8080
ONYX_SANDBOX_PUSH_PRIVATE_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
```

The `onyxdotapp/sandbox:dev` image referenced here is **local-only**; build
and load it per [step 3 of One-time setup](#3-build-and-load-the-sandbox-image)
before launching the api_server.

## Troubleshooting

### Craft tab missing from the sidebar (and `/craft` 404s)

The web doesn't read `ENABLE_CRAFT` directly. The sidebar (`AppSidebar.tsx`)
and the `/craft` route guard (`app/craft/layout.tsx`) both check
`combinedSettings.settings.onyx_craft_enabled`, which is computed by the
backend in `is_onyx_craft_enabled(user)`
(`backend/onyx/server/features/build/utils.py`) and returned from
`GET /api/settings` (`backend/onyx/server/settings/api.py`).

That backend check returns **`False`** when:

1. **No user is authenticated** — the settings endpoint short-circuits to
   `False` for anonymous requests, so the tab won't appear on the login page
   or in incognito. Log in first.
2. **The api_server you're hitting doesn't have `ENABLE_CRAFT=true`.** Most
   common cause: running the plain `API Server` launch (loads `.vscode/.env`)
   instead of the `(k8s)` launch (loads `.vscode/.env.k8s`). The `(k8s)`
   compound and `Run All Onyx Services (k8s)` are the only profiles that
   source `.env.k8s`.

Confirm by hitting `/api/settings` while logged in and checking
`onyx_craft_enabled`:

```bash
# from a logged-in browser session, copy the cookie and:
curl -sS http://localhost:3000/api/settings -H "Cookie: <paste>" | jq .settings.onyx_craft_enabled
```

If that returns `true` but the tab is still missing, hard-reload (the
settings response is fetched server-side; stale Next.js cache can hide a
just-flipped flag).

## References

- [CONTRIBUTING.md — Development Setup](/CONTRIBUTING.md#development-setup)
- [deployment/helm/README.md](/deployment/helm/README.md)
- [backend/onyx/server/features/build/sandbox/README.md](/backend/onyx/server/features/build/sandbox/README.md)
- [Telepresence docs](https://www.telepresence.io/docs/)
- [kind docs](https://kind.sigs.k8s.io/)
