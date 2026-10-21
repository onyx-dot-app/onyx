# Local Kubernetes Development

Use kind for Craft sandbox pods and supporting services. Run the API, web server,
and workers locally with hot reload. Telepresence connects these processes to the cluster
and routes API Service traffic to the local API.

For Docker sandbox development, use [the Compose guide](./local-compose-craft.md).
For work that needs no Kubernetes sandboxes, use the ordinary ODS development stack.
Agent guidance is in [the Craft development skill](../../../.agents/skills/onyx-craft-dev/SKILL.md).

## Prerequisites

Install Docker, kind, kubectl, Helm, Telepresence v2, uv, and the frontend dependencies
listed in [CONTRIBUTING.md](../../../CONTRIBUTING.md). ShellCheck is needed only for script changes.
Docker must be running and accessible to your user.

Allow at least 8 CPU and 16 GiB for the cluster. Three active sandboxes need more capacity.
Craft uses native init sidecars and requires Kubernetes 1.33 or later.
The setup script defaults to `kindest/node:v1.33.1`. Set `KIND_NODE_IMAGE` for another node version.
Keep kubectl within one minor version of the cluster.

Install the Python groups used by the local API and development tools:

```bash
uv sync --frozen --no-default-groups --group backend --group dev --group ee
```

The networking daemon can require sudo authorization on the first Telepresence connection.
Run this from an interactive terminal, including an SSH terminal, before automated launch tasks:

```bash
make craft-connect
```

The cluster must exist first. Do not enter passwords in agent chat.

## One-time setup

```bash
make craft-up
make craft-doctor
make craft-migrate
```

`craft-up` creates or updates the cluster and Helm release. It waits for active Onyx
Deployments, StatefulSets, and the Telepresence manager to become ready.
It then builds a missing sandbox image and loads it into kind. Existing images are reused.
Environment files are created only when absent. Existing files remain untouched.

Startup reports **infrastructure ready**. This means the cluster services are ready;
it does not mean that local application processes have started.
`--skip-helm` is a cluster-only operation and skips application workload readiness.

The default cluster is `onyx-dev`, namespace `onyx`, and Helm release `onyx`.
Select another local cluster with `CLUSTER_NAME=my-cluster NAMESPACE=onyx` on Make commands.
Export these variables before opening VS Code when using another cluster.
Sandbox pods use `onyx-sandboxes` by default.

## Daily workflow

### Run your local processes

In VS Code, select **Run All Onyx Services (k8s)**. Its shared task prepares the API
intercept. The API and workers use the same launcher as terminal commands.
The compound also starts a readiness check alongside the application processes.
Worker launches connect to the cluster without recreating the API intercept.

From a terminal, start the API with:

```bash
make craft-api
```

This foreground command prepares the intercept and starts Uvicorn with hot reload.
Start the web server using the existing **Web Server** launch profile or frontend development command.
Then check the application from another terminal:

```bash
make craft-ready
```

This requires an active API intercept in the selected cluster. It waits for the API's `/health/ready` response through the frontend's `/api` proxy,
then checks that the frontend serves an HTML page. A login page is a valid frontend response.
An HTML page returned for the API health route is not a valid API response.
Failures return a nonzero exit code. The check does not create a Craft session or validate a license.

Set `CRAFT_FRONTEND_URL` to test a frontend on another port.
For a shorter diagnostic wait:

```bash
python3 deployment/helm/dev/dev.py ready --timeout 30 --frontend-url http://localhost:3000
```

Run a worker through the same environment and reload implementation:

```bash
.venv/bin/python deployment/helm/dev/launch.py celery \
  -A onyx.background.celery.versioned_apps.primary worker \
  --pool=threads --concurrency=4 --loglevel=INFO --hostname=primary@%n -Q celery
```

Start the primary worker before dependent workers. The VS Code compound includes it.
Use the existing VS Code worker profiles for the full worker queue arguments.
The launcher preserves the worker reload implementation and debugger subprocess support.

### Set up your `.env.k8s`

`.vscode/.env.k8s` contains personal overrides. It no longer needs copies of chart-owned hosts,
credentials, encryption keys, storage endpoints, or sandbox settings.
The shared resolver reads the deployed API container's `envFrom` and `env` references.
This includes ConfigMaps, Secrets, prefixes, and inline values, in Kubernetes precedence order.
Resolved secrets stay in process memory; launch tasks never write them to an env file.

Overrides in `.env.k8s` take precedence over deployed defaults. Placeholder values are ignored.
The selected Kubernetes context, sandbox backend, and sandbox namespace remain pinned by the launcher.
The API and workers resolve the settings again when their launch process starts.
Restart the launch process after a Helm configuration change.

Old env files remain valid, but their service entries override new chart settings.
Remove those entries to follow the deployed configuration automatically. Keep personal model keys,
logging settings, and intentional overrides. Keep `.env.k8s` and `.env.web` untracked.
Migrations reject database host, port, or database-name overrides that differ from the selected deployment.
Before upgrades, stop the local API and workers from this checkout. Container processes do not block the command.

Configure a model provider in the admin UI, or set a model key in the personal env file.
Craft API operations also require a valid Business or Enterprise license, including a development license.
`ENABLE_CRAFT=true` alone does not grant access.

### Sandbox API callbacks

The Helm chart defaults `ONYX_SERVER_URL` to its internal API Service URL.
The API configuration and sandbox PodTemplate use the same value.
Telepresence forwards these callbacks to the local API during an intercept.
This path requires no host gateway alias, public ingress, or running local frontend.

Set `configMap.ONYX_SERVER_URL` to override the default. Include any API path prefix,
for example `https://onyx.example/api`. Explicit overrides continue to apply to both the API and sandbox.
Docker sandbox deployments still configure their reachable API URL separately.

### Iteration loop

| Change or task | Command |
| --- | --- |
| Local API or web source | Use the existing hot reload process |
| Sandbox image source | `make craft-sandbox-image` |
| In-cluster API or proxy source | `make craft-backend-image` |
| Both images | `make craft-refresh-images` |
| Compare images with the checkout | `make craft-check-images` |
| Force a sandbox build during startup | `deployment/helm/dev/craft-up.sh --rebuild-sandbox-image` |

Refresh commands include uncommitted and non-ignored source changes.
Sandbox refresh updates all main and init-container image references in the PodTemplate.
Existing sandbox pods retain their images. Loading an image does not replace live sandboxes.
Backend refresh waits for the deployment rollouts and reports the running image IDs.

The local overlay uses `onyxdotapp/sandbox:dev` with `IfNotPresent`.
`SANDBOX_IMAGE` overrides are forwarded to Helm at setup.
Worktrees share the default mutable tags; do not build concurrently against the same tags.
Use separate clusters and distinct `BACKEND_IMAGE` / `SANDBOX_IMAGE` tags for independent environments.

### Diagnose setup and readiness

```bash
make craft-doctor
make craft-ready-infra
make craft-connect
make craft-intercept
make craft-ready
```

Doctor checks tools, Docker access, disk space, Python dependencies, Kubernetes version skew,
node readiness, Telepresence, effective configuration, and sandbox image policy.
It prints variable names and check results without exposing secret values.
It does not check application login or license status. The disk check covers the checkout filesystem;
Docker storage can use another filesystem.

API intercept creation is shared between terminal and VS Code commands.
It reuses an existing intercept. A known stale agent identity failure allows one targeted restart and retry.
Other intercept failures stop the command. A connection alone does not create an intercept or start the API.

Pin the context when inspecting resources:

```bash
kubectl --context kind-onyx-dev -n onyx get pods
kubectl --context kind-onyx-dev -n onyx get events --sort-by=.lastTimestamp
kubectl --context kind-onyx-dev -n onyx-sandboxes get pods
```

For image pull failures, confirm the PodTemplate image and run `make craft-sandbox-image`.
For DNS failures, check Telepresence's context and namespace with `telepresence status --format json`.
For startup failures, inspect local service logs and the rollout named in the readiness output.
Do not change production contexts or stop unrelated processes to recover a local setup.

## Data persistence

Stop the local launch compound before pausing the cluster:

```bash
make craft-pause
make craft-resume
```

Pause preserves cluster state and PVC data. Resume waits for infrastructure and reconnects Telepresence.
Relaunch local services to restore the API intercept, then run `make craft-ready`.
Use `make craft-down` for a full teardown; it deletes the cluster and its data.

## Control disk use

```bash
make craft-disk
make craft-clean
make craft-clean CLEAN_ARGS=--apply
```

Cleanup defaults to a preview. It removes only unused dangling images labeled for this checkout.
It preserves tagged images, referenced images, unlabeled images, kind runtime images, and volumes.
Run checkout cleanup before deleting the worktree. Worktree deletion does not trigger resource cleanup.

Build cache is shared across projects. Preview its separate cleanup explicitly:

```bash
make craft-clean CLEAN_ARGS=--build-cache
make craft-clean CLEAN_ARGS='--build-cache --apply'
```

This considers entries unused for seven days, with a 10GB retention target.
It is not a total Docker disk limit. These commands do not change Docker's automatic cache collection.
Kind's kubelet collects unused runtime images independently.

## Verify workflow changes

```bash
.venv/bin/python -m unittest discover -s deployment/helm/dev/tests -v
```

Readiness tests use a temporary local HTTP server. Helm callback and pod-spec tests live in
`backend/tests/external_dependency_unit/craft_helm`. Real Craft tests live in
`backend/tests/integration/tests/craft/k8s` and need a licensed development stack.
