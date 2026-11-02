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
- DNS failure: check the Telepresence context and namespace with `telepresence status --format json`.
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

## Test the workflow tools

```bash
.venv/bin/python -m unittest discover -s deployment/helm/dev/tests -v
```

Helm callback and pod-spec tests are in `backend/tests/external_dependency_unit/craft_helm`.
Real Craft tests are in `backend/tests/integration/tests/craft/k8s` and need a
licensed development stack.
