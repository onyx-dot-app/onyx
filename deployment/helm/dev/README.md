# Craft local Kubernetes development

Use kind for Craft sandbox pods and supporting services. Run the API, web server,
and workers locally with hot reload. Telepresence connects these processes to the
cluster and routes API Service traffic to the local API.

For the Docker sandbox backend, use
[the Docker backend guide](../../../backend/onyx/server/features/build/sandbox/docker/README.md).
For work that needs no Kubernetes sandboxes, use the ordinary ODS development stack.
Agent guidance is in [the Craft development skill](../../../.agents/skills/onyx-craft-dev/SKILL.md).

`dev.py` implements the Make targets and VS Code tasks. `runtime.py` resolves the
deployed configuration. `launch.py` starts the API and workers with that configuration.

## Prerequisites

Install Docker, kind, kubectl, Helm, Telepresence v2, uv, and the frontend
dependencies listed in [CONTRIBUTING.md](../../../CONTRIBUTING.md).
Docker must be running and accessible to your user.

- Allow at least 8 CPU and 16 GiB for the cluster. Three active sandboxes need more.
- Craft uses native init sidecars and requires Kubernetes 1.33 or later.
  `k8s-up.sh` defaults to `kindest/node:v1.33.1`. Set `KIND_NODE_IMAGE` for another version.
- Keep kubectl within one minor version of the cluster.

Install the Python groups that the local API and tools use:

```bash
uv sync --frozen --no-default-groups --group backend --group dev --group ee
```

The Telepresence daemon can ask for a sudo password on the first connection.
After the cluster exists, run `make craft-connect` once from an interactive terminal.

## One-time setup

```bash
make craft-up
make craft-doctor
make craft-migrate
```

`craft-up` creates or updates the cluster and Helm release. It waits for Onyx
Deployments, StatefulSets, and the Telepresence manager. It builds the sandbox image
only when it is missing, then loads it into kind. It creates absent env files and
does not change existing ones.

"Infrastructure ready" means that cluster services are ready. It does not mean that
local application processes are running. `--skip-helm` creates only the cluster.

The defaults are cluster `onyx-dev`, namespace `onyx`, and Helm release `onyx`.
Sandbox pods use `onyx-sandboxes`. To use another cluster, export `CLUSTER_NAME`
and `NAMESPACE` before you run Make or open VS Code.

## Daily workflow

### Start local processes

In VS Code, select **Run All Onyx Services (k8s)**. It prepares the API intercept,
starts the API and workers, and runs a readiness check.

From a terminal:

```bash
make craft-api     # prepares the intercept, then runs Uvicorn with hot reload
make craft-ready   # in another terminal, after the web server starts
```

`craft-ready` needs an active API intercept. It waits for `/health/ready` through
the frontend `/api` proxy, then checks that the frontend serves HTML. A login page
is a valid frontend response. The check does not create a Craft session or check
a license. Set `CRAFT_FRONTEND_URL` for a frontend on another port.

Start a worker through the same launcher:

```bash
.venv/bin/python deployment/helm/dev/launch.py celery \
  -A onyx.background.celery.versioned_apps.primary worker \
  --pool=threads --concurrency=4 --loglevel=INFO --hostname=primary@%n -Q celery
```

Start the primary worker before dependent workers. The VS Code worker profiles
contain the full queue arguments.

### Configuration and `.env.k8s`

The launcher reads the deployed API container's `envFrom` and `env` entries,
including ConfigMaps, Secrets, and inline values, in Kubernetes precedence order.
Resolved secrets stay in process memory. No launch task writes them to a file.

`.vscode/.env.k8s` holds only personal overrides, for example model keys and log
settings. Its entries take precedence over deployed values, except for the
Kubernetes context, sandbox backend, and sandbox namespace, which the launcher pins.
Service entries in an old env file override chart settings. Remove them to follow
the chart. Restart the launch process after a Helm configuration change.
Keep `.env.k8s` and `.env.web` untracked.

Craft API operations need a model provider and a valid Business or Enterprise
license. A development license works. `ENABLE_CRAFT=true` alone does not grant access.

### Sandbox callbacks

The chart sets `ONYX_SERVER_URL` to the internal API Service URL for both the API
and the sandbox PodTemplate. During an intercept, Telepresence forwards sandbox
callbacks to the local API, so no host gateway alias or public ingress is necessary.

Existing sandbox pods keep the callback URL from when they were created. If you
remove a `configMap.ONYX_SERVER_URL` override, first remove or recreate the
sandboxes that use it.

### Refresh images

| Change | Command |
| --- | --- |
| Local API or web source | Use the running hot reload process |
| Sandbox image source | `make craft-sandbox-image` |
| In-cluster API or sandbox proxy source | `make craft-backend-image` |
| Both images | `make craft-refresh-images` |
| Compare images with the checkout | `make craft-check-images` |
| Force a sandbox build during startup | `deployment/helm/dev/craft-up.sh --rebuild-sandbox-image` |

Image fingerprints include uncommitted and untracked, non-ignored files.
A sandbox refresh updates the PodTemplate for future pods. Existing sandbox pods
keep their image. A backend refresh waits for the rollouts and reports image IDs.

The local overlay uses `onyxdotapp/sandbox:dev` with `IfNotPresent`.
Worktrees share the default mutable tags. Do not build concurrently against the
same tags. For independent environments, use separate clusters and distinct
`BACKEND_IMAGE` and `SANDBOX_IMAGE` tags.

Behind a TLS inspection proxy, set `CRAFT_BUILD_CA_BUNDLE` to a PEM bundle with
public roots and your proxy CA. Image builds receive it as the `build_ca_bundle`
BuildKit secret. Certificate verification stays on, and the image does not store
the bundle.

### Diagnose

```bash
make craft-doctor       # tools, Docker, disk, Python deps, version skew, Telepresence, config, image policy
make craft-ready-infra
make craft-connect
make craft-intercept
make craft-ready
```

`craft-doctor` does not print secret values and does not check login or license.
Its disk check covers the checkout filesystem only.

Intercept creation reuses an intercept only when it forwards container port 8080
to local port 8080. A known stale-agent failure causes one targeted restart and retry.

Always pin the context when you inspect resources:

```bash
kubectl --context kind-onyx-dev -n onyx get pods
kubectl --context kind-onyx-dev -n onyx get events --sort-by=.lastTimestamp
kubectl --context kind-onyx-dev -n onyx-sandboxes get pods
```

- Image pull failure: check the PodTemplate image, then run `make craft-sandbox-image`.
- DNS failure: check the Telepresence context and namespace with `telepresence status --output json`.
- Startup failure: read the local service logs and the rollout that the readiness output names.

## Pause, tear down, and clean up

Stop the local launch compound before you pause:

```bash
make craft-pause    # keeps cluster state and PVC data
make craft-resume   # restarts nodes and reconnects Telepresence; relaunch local services after
make craft-down     # deletes the cluster and its data
```

```bash
make craft-disk
make craft-clean                                   # preview
make craft-clean CLEAN_ARGS=--apply
make craft-clean CLEAN_ARGS=--build-cache          # preview shared build cache cleanup
make craft-clean CLEAN_ARGS='--build-cache --apply'
```

Cleanup removes only unused dangling images labeled for this checkout. It keeps
tagged, referenced, unlabeled, and kind runtime images, and all volumes. Run it
before you delete a worktree. Build cache cleanup removes entries unused for seven
days with a 10 GB retention target. It is not a total Docker disk limit.

## Remote Firecracker cluster (`--target craft-dev`)

Firecracker sandboxes need KVM, so they do not run in kind. With the `craft-dev`
target, the local API uses a shared remote cluster: its Postgres, Redis, OpenSearch,
and host agents. Telepresence (`connect` only, no intercept) gives the laptop cluster
DNS and routes. No local Celery workers or beat run.

### Profile

A profile file holds all cluster facts. This repository ships no cluster names or
account IDs. The launcher reads the profile path from `--profile`, then
`CRAFT_DEV_PROFILE`, then `../onyx-internal/dev/craft-dev.yaml` next to the main
checkout. Example with placeholders:

```yaml
name: craft-dev
kube:
  context: <kube context name>          # always passed with --context
  allowed_contexts: [<kube context name>] # --context or CRAFT_DEV_CONTEXT must be in this list
  kubeconfig: ~/.kube/<file>.yaml       # optional; the local API always gets the kubeconfig the checks use
  server: https://<eks endpoint>        # optional; refuse a context with another API server
aws:
  profile: <aws sso profile>            # optional
  region: <region>
  eks_cluster: <eks cluster name>
  account_id: "<account id>"            # optional; quote it
namespaces:
  app: onyx
  sandbox: onyx-sandboxes
  agent: <host agent namespace>
agent:
  selector: app.kubernetes.io/component=craft-fc-host-agent
  port: 7443
  container: host-agent                 # optional; the agent container for `logs`
user:
  email: <your Onyx login email>        # optional; else CRAFT_DEV_USER or --user
telepresence:
  min_version: 2.27.4
local_env: {}                           # optional; values for the local API only
```

The cluster needs a Telepresence traffic manager that also proxies the VPC CIDR
(database and cache), and a NetworkPolicy that lets the traffic manager reach the
host agent port. The profile owner installs both.

### Run

Use the `ods craft-dev` commands. They run the Python launchers in this
directory with `uv`. Until the next `onyx-devtools` release includes them, use
`go -C tools/ods run . craft-dev ...` from the repository root instead of `ods craft-dev ...`.

```bash
export CRAFT_DEV_PROFILE=<path to the profile>     # optional with the onyx-internal checkout
ods craft-dev doctor
telepresence connect --context <context> -n onyx   # in a real terminal; it asks for sudo once
ods craft-dev api                                  # local API with hot reload
ods craft-dev web                                  # in another terminal; next dev against the local API
```

All commands accept `--profile` and `--context`. `--context` (or `CRAFT_DEV_CONTEXT`)
must be in `kube.allowed_contexts`. `api` and `web` accept `--port` for the local API port.

In VS Code, use the **Craft dev (remote cluster)** compound and the
**craft-dev: doctor** task.

`ods craft-dev api` does these steps:

1. Refuses a context that is not in the profile and an API server that differs from `kube.server`.
2. Refuses to start when Telepresence is not connected to the same context, API server, and namespace.
3. Resolves the deployed api-server env, like the kind flow. Then it applies `local_env`,
   sets `SENTRY_DSN` to empty and `WEB_DOMAIN` to `CRAFT_FRONTEND_URL` (default
   `http://localhost:3000`), and applies `.vscode/.env.craft-dev`. The deployed
   `SANDBOX_BACKEND`, `SANDBOX_NAMESPACE`, and `SANDBOX_RUNTIME` always stay. No override changes them.
4. Copies each Secret volume of the api-server container (for example the host agent
   client certificate) to a mode-0700 temporary directory. Env values that point into
   the mount point at the copies. The launcher deletes the directory when the API stops.
5. Compares the checkout Alembic head with the shared database. It refuses on a
   difference. It never runs migrations: redeploy the cluster to migrate.
6. Runs Uvicorn on `127.0.0.1`. The port is `--port`, then `CRAFT_API_PORT`, then 8080
   if it is free, else a free port. Start the web server with the same port:
   `ods craft-dev web --port <port>`.

`.vscode/.env.craft-dev` holds personal overrides, for example a personal
`SANDBOX_FC_TEMPLATE`. Keep it untracked.

`ods craft-dev doctor` checks the AWS SSO session and account, the IPv4 egress address
against the EKS endpoint allowlist, IPv6 egress, the context pin, kube access, the
Telepresence version and connection, NodeInfo over mTLS to each host agent, and the
Alembic head. Each failure prints one fix line. It changes nothing.

If `telepresence connect` hangs, run `telepresence quit -s`, then connect again.

### Your VM

These commands act only on the sandbox VM of your user: `--user`, else
`CRAFT_DEV_USER`, else `user.email` in the profile. They run a helper in an
api-server pod with `kubectl exec`, so they do not need Telepresence.

```bash
export CRAFT_DEV_USER=<your Onyx login email>
ods craft-dev vms                                  # your VM, its node and state
ods craft-dev skills push ./my-skills --wake       # put a directory on /mnt/skills
ods craft-dev skills push ./data --mount spaces    # or on user-uploads or spaces
ods craft-dev exec --wake -- ls -la /mnt/skills    # run a command as the sandbox user
ods craft-dev logs --agent --tail 50               # guest and agent lines of your VM
ods craft-dev logs -f                              # follow; -f does not take --tail
ods craft-dev reset                                # save your sessions, then stop the VM
```

The managed mounts are `noexec`. Run a script through its interpreter, for example
`python3 /mnt/skills/x.py`. `skills push` prints this hint for each script.
`reset --force` stops the VM without a save.

## Test the workflow tools

```bash
.venv/bin/python -m unittest discover -s deployment/helm/dev/tests -v
```

Helm callback and pod-spec tests are in `backend/tests/external_dependency_unit/craft_helm`.
Real Craft tests are in `backend/tests/integration/tests/craft/k8s` and need a
licensed development stack.
