# Local Kubernetes Development

How to develop Onyx against a local kind cluster, with the vscode debugger
attached to api_server / celery / web.

## When you need this

Craft uses Firecracker VMs through Kubernetes and the `kata-fc` RuntimeClass.
Non-Craft work can still use the docker-compose deps + vscode debugger path
described in [CONTRIBUTING.md](/CONTRIBUTING.md); use that when you don't
need a sandbox.

Craft setup requires an existing Linux KVM kind cluster with Kata configured.
Ordinary Docker Desktop kind clusters cannot run Craft. See
[Firecracker node prerequisites](../infra/firecracker.md).

## Prerequisites

Install the Python, uv, and Bun tools described in CONTRIBUTING.md.
Run `uv sync --frozen` at the repository root before image refresh.
Refresh requires the development `.venv` and Docker support for `docker image save --platform`.
The runtime host must provide Linux KVM and `/dev/vhost-vsock`.
The existing runtime helper supports Linux x86_64 kind hosts.
macOS Docker Desktop does not supply these prerequisites.
Install kind, Helm, and kubectl on the Linux runtime host.
On a Mac development client, use these client tools.

```bash
brew install kind helm kubectl

curl -fLo /opt/homebrew/bin/telepresence \
  https://github.com/telepresenceio/telepresence/releases/latest/download/telepresence-darwin-arm64
chmod +x /opt/homebrew/bin/telepresence
```

### Configure a Linux KVM kind cluster

Use a fresh cluster for first-time runtime installation. Preserve existing clusters and their data.
Copy this kind configuration to a local file, such as `/tmp/onyx-kind.yaml`.

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraMounts:
      - hostPath: /dev/kvm
        containerPath: /dev/kvm
      - hostPath: /dev/vhost-vsock
        containerPath: /dev/vhost-vsock
      - hostPath: /lib/modules
        containerPath: /lib/modules
        readOnly: true
```

Run these commands on the Linux host.

```bash
export KIND_CLUSTER_NAME=onyx-dev
export KIND_NODE_NAME=onyx-dev-control-plane
deployment/helm/dev/firecracker-ci.sh preflight-host
kind create cluster --name onyx-dev --image kindest/node:v1.33.1 --config /tmp/onyx-kind.yaml
kubectl config use-context kind-onyx-dev
deployment/helm/dev/firecracker-ci.sh configure-kind-node
deployment/helm/dev/firecracker-ci.sh install-kata
```

`configure-kind-node` creates the devmapper pool once. It refuses existing backing files and pools.
The stock kind daemon excludes devmapper. Setup replaces only that daemon with
the checksum-pinned official containerd 2.1.1 build at the same source revision.
It sets `DM_DISABLE_UDEV=1` for setup and containerd because kind does not run udev.
Do not run it as a daily setup command. The Kata install invokes the checksum-pinned
`deployment/firecracker/install-pinned-firecracker.sh` for Firecracker `v1.17.0` and its jailer.

Check the configured prerequisites without changing the cluster.

```bash
deployment/helm/dev/k8s-up.sh --check-runtime
```

After building a guest image, use the existing smoke check on the Linux host.

```bash
KATA_SMOKE_IMAGE=onyxdotapp/sandbox:dev deployment/helm/dev/firecracker-ci.sh verify
```

The smoke check verifies a separate guest boot ID and the live Firecracker binary.
It does not replace Craft integration or browser tests.
Craft requires a NetworkPolicy-enforcing CNI.
Runtime preflight does not test policy enforcement.
Run the real network isolation suite before trusting the deployment.

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

## Local resource budgets

`deployment/helm/dev/values-localdev.yaml` defines local service resources.
CPU requests reserve capacity. CPU limits allow short bursts above the request.
Memory limits remain separate from requests.

| Service | CPU request / limit | Memory request / limit |
| --- | --- | --- |
| API (Telepresence target) | 0.1 / 0.5 | 256 MiB / 1 GiB |
| Sandbox proxy | 0.5 / 2 | 512 MiB / 1 GiB |
| Each model server | 1 / 2 | 1 GiB / 2 GiB |
| OpenSearch | 1 / 2 | 2 GiB / 4 GiB |
| PostgreSQL | 0.5 / 2 | 512 MiB / 2 GiB |
| PostgreSQL operator | 0.1 / 1 | 128 MiB / 512 MiB |
| MinIO | 0.25 / 1 | 256 MiB / 1 GiB |
| Object store | 0.25 / 1 | 256 MiB / 2 GiB |
| Redis | 0.1 / 1 | 128 MiB / 512 MiB |

Redis has a 400 MB cache budget. Its memory limit also covers process overhead.
OpenSearch keeps its 1 GiB heap and has memory for other allocations.

The API serves as a Telepresence target. The developer's local Python process handles intercepted API requests.
Its small resource budget is deliberate; local API startup can take longer.

These services request 4.8 CPU and about 6 GiB before other operators and Kubernetes system pods.
Each sandbox adds the request configured by `sandboxPod.resources`. The
firewall init container is short-lived and does not replace VM capacity
planning.
These values support development. They do not guarantee performance for large indexes or models.

Run `make craft-up` to apply the local overlay. Keep any local image overrides when upgrading an existing release.
Changing PostgreSQL resources restarts its single instance. Existing connections can delay shutdown for up to three minutes.
New database connections fail during this restart.
Check node capacity with `kubectl describe node`; check usage with `kubectl top pods` when metrics are available.

## kubectl context

Setup and image refresh pass `--context kind-onyx-dev` explicitly to Kubernetes
and Helm. They do not change your active context. Set `CLUSTER_NAME` for image
refresh or pass `--cluster-name` to setup for another configured kind cluster.
Teardown commands still require their documented context check.

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

After configuring the runtime, run **`make craft-up`** or the **craft: up** vscode task.
It checks the runtime, builds local images, installs Onyx, and creates missing IDE env files.
It refuses existing sandbox pods.
Snapshot live sessions with the current release before draining their sandboxes.
Before an image or protocol update, stop host Onyx API, Celery workers, and beat processes.
This includes the VS Code **Run All Onyx Services (k8s)** debug session.
Restart these processes only after setup or refresh succeeds.

On Linux, replace `host.docker.internal` in the local Helm overlay and `.env.k8s`
with a host address reachable through the sandbox proxy. Both `ONYX_SERVER_URL`
values must point to the frontend API route.

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

**1. Check the existing runtime.** Delegates to
[`deployment/helm/dev/k8s-up.sh`](/deployment/helm/dev/k8s-up.sh). The
script requires `kata-fc`, usable KVM devices, healthy devmapper, and the pinned binary versions.
These checks run before image builds, env copies, or cluster changes.
It does not install a runtime or replace an existing cluster.

`k8s-up.sh --skip-helm` creates or checks an ordinary non-Craft kind cluster.
That path does not install Onyx, build images, patch Kindnet, or claim Firecracker support.

Watch pods (opensearch and CNPG-postgres take a minute or two on first boot):

```bash
kubectl -n onyx get pods -w
```

The chart selects local backend and guest `:dev` images in
[`values-localdev.yaml`](/deployment/helm/dev/values-localdev.yaml)
with `IfNotPresent`. Other Onyx images use `:edge` with `IfNotPresent`.

**2. Build and load matching images.** The shared refresh script builds the
backend and guest. Upgrades roll every in-cluster backend deployment and wait
for old pods to terminate. Then they load the new guest image and apply the
complete Helm PodTemplate, including both containers and its protocol label.
Prepare leaves both live image tags unchanged when a guest template already exists.
In-cluster rollouts do not stop your host API, Celery workers, or beat.
The backend uses Kind's image loader. The guest loader checks each node's cluster ownership,
imports the selected platform through containerd devmapper, and marks the image retained by CRI.
It compares the saved Docker config digest with each node's CRI image ID and checks retention before applying the template.
The standalone refresh command is:

```bash
make craft-refresh-images
```

`craft-sandbox-image` and `craft-backend-image` use this same refresh path.
Neither target updates one half of a guest protocol change.
Image and pull policy settings belong to Helm, not `.env.k8s`.

**3. Bootstrap the vscode env files.** Copies `.vscode/.env.k8s.template` to
`.vscode/.env.k8s`, and `.vscode/env.web_template.txt` to `.vscode/.env.web`.
Only absent files are created. Existing files and their secrets remain untouched.

Verify both images are present in the kind node.

```bash
docker exec onyx-dev-control-plane crictl images | grep -E 'sandbox|onyx-backend'
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

Set `CRAFT_SANDBOX_RUNTIME=kubernetes_firecracker` and `ENABLE_CRAFT=true`.
The removed `SANDBOX_BACKEND`, push signing key, and backend image controls have no effect.

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

The task checks for an unregistered traffic-agent with a recent stale-session
error. It restarts only `onyx-api-server`, waits up to 120 seconds for the
rollout, and creates the intercept. If the session becomes stale during intercept
creation, it checks again and retries after recovery. Recovery runs at most once
per launch. Other failures stop the task and show the original error.

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
`.env.k8s.template`).

Visit `http://localhost:3000` once running.

### Iteration loop

| What you changed | Cycle time | What to do |
|---|---|---|
| Python in api_server / celery / model_server | ~instant | uvicorn / debugpy reloads. No cluster touch. |
| Frontend (`web/`) | ~instant | Next.js HMR. |
| Helm chart templates / values | Depends on rollout | Snapshot and drain sandboxes, stop host processes, then re-run `k8s-up.sh`. |
| Backend or guest image and helper protocol | Depends on build and rollout | Snapshot and drain sandboxes, stop host processes, then run `make craft-refresh-images`. |

### Building and loading local images

Stop new session traffic and snapshot live sessions with the current release.
Drain those sandboxes, then stop host Onyx API, Celery workers, and beat processes.
Stop the VS Code **Run All Onyx Services (k8s)** session and any separately launched Kubernetes backend processes.
The refresh script does not detect or stop host processes.

```bash
make craft-refresh-images
make craft-check-images
```

Restart the host processes only after refresh succeeds.
The shared script loads images into kind without a registry push.
Guest loading streams the image archive without a local archive file.
It reads the archive once for the config digest, then exports the same platform to each node.
An import, image ID, or retention failure stops refresh before template application.
The check target reports image IDs and the live template. It does not prove source freshness or VM acceptance.
Refresh checks for sandbox pods before image changes and after template application.
If a sandbox appears during refresh, the script fails without deleting the pod.
Keep the host processes stopped and preserve that sandbox's work before retrying.

### Avoid this loop when you can

For logic that does not depend on cluster behavior, such as archive validation,
use local or external-dependency-unit tests against a temp dir. See
[`backend/tests/README.md`](/backend/tests/README.md).

### End of day

Run **`k8s: pause cluster`** (or `docker stop onyx-dev-control-plane`) to stop
the kind node container. PVC data lives inside that container, so postgres,
redis, opensearch, and minio state all survive. Resume with
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
CRAFT_SANDBOX_RUNTIME=kubernetes_firecracker
ONYX_SERVER_URL=http://host.docker.internal:3000/api
```

Sandbox image, service account, RuntimeClass, and pull policy are Helm values.
Set those in the local values file, not in backend Python env.

## Troubleshooting

### Sandbox egress stalls with Kindnet CPU throttling

Kindnet CPU throttling can delay pod network traffic.
Connections to the sandbox proxy and Kubernetes resource watches can stall. OpenCode startup
can then time out while installing plugins, before sending an LLM request.

Reconcile the local networking configuration after draining sandboxes:

```bash
deployment/helm/dev/k8s-up.sh --skip-cluster-create
```

Check the active CPU quota and throttling counters:

```bash
kubectl --context kind-onyx-dev -n kube-system exec daemonset/kindnet -- \
  cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/cpu.stat
```

`cpu.max` starts with `max` when the container has no CPU limit.

### VPN or proxy certificate errors

For `x509: certificate signed by unknown authority` or `CERTIFICATE_VERIFY_FAILED`,
obtain your proxy's root CA from IT. Save it as a PEM `.crt` outside the repository.
Setup scripts do not install certificates. Keep TLS verification enabled.

If `docker pull` fails, follow [Docker's CA setup](https://docs.docker.com/engine/network/ca-certs/).
If only kind image pulls fail, run this in Bash with your CA path:

```bash
set -euo pipefail
onyx_local_ca="/absolute/path/to/company-root.crt"
deployment/helm/dev/k8s-up.sh --skip-helm
onyx_local_nodes="$(kind get nodes --name onyx-dev)"
for onyx_local_node in $onyx_local_nodes; do
  docker cp "$onyx_local_ca" "$onyx_local_node:/usr/local/share/ca-certificates/onyx-local-proxy.crt"
  docker exec "$onyx_local_node" update-ca-certificates
  docker exec "$onyx_local_node" systemctl restart containerd
done
make craft-up
```

For local client errors, build a bundle from the repository root:

```bash
set -euo pipefail
onyx_local_ca="/absolute/path/to/company-root.crt"
mkdir -p "$HOME/.onyx-dev"
onyx_public_ca="$(.venv/bin/python -m certifi)"
cat "$onyx_public_ca" "$onyx_local_ca" > "$HOME/.onyx-dev/manual-ca-bundle.crt"
```

Set `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` to the bundle's absolute path in `.vscode/.env.k8s`.
Set `NODE_EXTRA_CA_CERTS` to the root CA's absolute path in `.vscode/.env.web`. Restart the services.

After CA rotation or removal, replace or remove the node certificate, run `update-ca-certificates --fresh`, and restart containerd.
Rebuild the local bundle and update client settings. Repeat node setup after cluster recreation.
Node trust does not configure certificates inside application pods.

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
