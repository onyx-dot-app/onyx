# Local Kubernetes Development

How to develop Onyx against a local kind cluster, with the vscode debugger
attached to api_server / celery / web.

## When you need this

This is the canonical local setup for **Onyx Craft (build mode)** — sandboxes
are real Kubernetes pods, so there is no longer a non-cluster shortcut.
Non-Craft work can still use the docker-compose deps + vscode debugger path
described in [CONTRIBUTING.md](/CONTRIBUTING.md); use that when you don't
need a sandbox.

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

## kubectl context

Every script in this doc — and the `make craft-up` wrapper — refuses to
operate unless your `kubectl` context is exactly `kind-onyx-dev`. This is
a deliberate safety guard: the `onyx` namespace also exists in production
EKS, and `helm uninstall` / `kubectl delete` on the wrong cluster is
catastrophic.

List your contexts:

```bash
kubectl config get-contexts
```

Check which one is active:

```bash
kubectl config current-context
```

Switch to the kind cluster:

```bash
kubectl config use-context kind-onyx-dev
```

**Verify before anything destructive** (uninstall, namespace delete, etc.):

```bash
kubectl config current-context    # expect: kind-onyx-dev
```

## One-time setup

Run **`make craft-up`** (or the **`craft: up`** vscode task). It handles
the cluster, helm install, sandbox image build/load, and `.env.k8s`
bootstrap in one shot. Idempotent — safe to re-run.

```bash
make craft-up
```

Then fill in `<REPLACE THIS>` values in `.vscode/.env.k8s` (at minimum
`GEN_AI_API_KEY`). See [Set up your `.env.k8s`](#set-up-your-envk8s) below.

If telepresence isn't already connected when you go to run the api_server,
the vscode `(k8s)` launch profile's preLaunchTask connects + intercepts
automatically. Outside vscode:

```bash
telepresence connect -n onyx
```

### What `craft-up` does

For transparency / debugging, `craft-up.sh` runs these steps in order. You
can also invoke them individually for tighter rebuild loops.

**1. Bring up the cluster.** Delegates to
[`deployment/helm/dev/k8s-up.sh`](/deployment/helm/dev/k8s-up.sh). The
script is idempotent and refuses to run unless your kubectl context is
`kind-onyx-dev`. It also installs the telepresence traffic-manager once
per cluster.

Watch pods (vespa and CNPG-postgres take a minute or two on first boot):

```bash
kubectl -n onyx get pods -w
```

The chart pins images to the `:edge` tag in
[`values-localdev.yaml`](/deployment/helm/charts/onyx/values-localdev.yaml)
with `pullPolicy: Always`, so in-cluster pods track nightly builds off `main`
rather than the released `:latest`.

**2. Bootstrap `.vscode/.env.k8s`.** Copies `.vscode/.env.k8s.template` to
`.vscode/.env.k8s` if absent. Existing files are never overwritten — your
secrets stay intact across `craft-up` runs.

**3. Build and load the sandbox image.** The chart points sandbox pods at
`onyxdotapp/sandbox:dev`, which is local-only. Skipping this is the most
common Craft setup failure — kind's `imagePullPolicy: IfNotPresent` will
fail and Build sessions hang. The standalone rebuild command:

```bash
make craft-sandbox-image
```

which is equivalent to:

```bash
docker build -t onyxdotapp/sandbox:dev \
  backend/onyx/server/features/build/sandbox/kubernetes/docker
kind load docker-image onyxdotapp/sandbox:dev --name onyx-dev
```

The image tag (`onyxdotapp/sandbox:dev`) must match `SANDBOX_CONTAINER_IMAGE`
in your `.env.k8s` and the chart's `sandbox.image.*` values.

Verify it's present in the kind node:

```bash
docker exec onyx-dev-control-plane crictl images | grep sandbox
```

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

- `craft: up (cluster + sandbox image + .env.k8s)` — one-shot setup.
- `craft: down (teardown + telepresence quit)` — symmetric teardown.
- `craft: rebuild sandbox image` — rebuild + reload the sandbox image.
- `k8s: cluster up` — bring up or reconcile the cluster.
- `k8s: pause cluster (data preserved)` — stop the kind node container at end of day.
- `k8s: resume cluster` — start it back up; kubelet reconciles pods.
- `k8s: cluster down (full teardown)` — delete the kind cluster and all PVC data.
- `k8s: telepresence connect`, `... intercept api_server`, `... quit`.

### Common commands

The recipes you'll hit in your first week:

```bash
# Watch pods come up / go down
kubectl -n onyx get pods -w

# Tail logs from one pod
kubectl -n onyx logs -f <pod>

# Stream logs across all api_server replicas (uses stern)
stern -n onyx onyx-api-server

# Shell into the postgres primary
kubectl -n onyx exec -it onyx-pg-1 -- psql -U postgres

# Restart api_server after a chart edit
kubectl -n onyx rollout restart deployment/onyx-api-server

# Delete one sandbox pod (test a recovery path)
kubectl -n onyx-sandboxes delete pod <name>

# Inspect cluster events (most-recent 30)
kubectl -n onyx get events --sort-by=.lastTimestamp | tail -30
```

### Set up your `.env.k8s`

The K8s api_server launch loads env from `.vscode/.env.k8s`. You own this
file end-to-end — the telepresence intercept no longer regenerates it.
`make craft-up` bootstraps it from the template on first run; if you ever
need to recreate it by hand:

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

### Sandbox pods stuck in `ImagePullBackOff`

**Symptoms:** Pods in the `onyx-sandboxes` namespace fail to start, with
`ImagePullBackOff` or `ErrImagePull` for `onyxdotapp/sandbox:dev`. Build
sessions hang at PROVISIONING.

**Cause:** `onyxdotapp/sandbox:dev` is local-only — it isn't on any
registry. You either skipped the build step or you have a fresh cluster
without the image loaded.

**Recovery:**

```bash
make craft-sandbox-image
```

(equivalent to `docker build` + `kind load docker-image`).

### api_server can't resolve `onyx-pg-rw` (or other in-cluster DNS)

**Symptoms:** Your local api_server (run from vscode) crashes on startup
with `Name or service not known` / `Temporary failure in name resolution`
for `onyx-pg-rw`, `onyx-minio`, etc.

**Cause:** telepresence is not connected, so your host DNS doesn't know
about the in-cluster Service records.

**Recovery:**

```bash
telepresence status        # should report "Connected"
telepresence connect -n onyx
```

The vscode `(k8s)` launch profiles wire `k8s: telepresence intercept
api_server` as their `preLaunchTask`, so this is usually only an issue when
running api_server outside vscode.

### `kubectl` operating against the wrong cluster

**Symptoms:** `kubectl get pods` returns prod pods (or empty when you
expect kind pods), or destructive commands surprise you.

**Cause:** Your kubectl current-context isn't `kind-onyx-dev` — it's
probably `docker-desktop`, a real EKS context, or a different kind cluster.

**Recovery:**

```bash
kubectl config current-context              # see what you're on
kubectl config use-context kind-onyx-dev    # switch
kubectl config current-context              # verify
```

The `k8s-up.sh` / `k8s-down.sh` / `craft-up.sh` / `craft-down.sh` scripts
all refuse to operate unless the current context is exactly
`kind-onyx-dev`, so this won't bite you when going through them — only on
ad-hoc `kubectl` invocations.

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
