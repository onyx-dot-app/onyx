---
name: onyx-craft-dev
description: Start, debug, refresh images, run migrations, and clean up the local Onyx Craft Kubernetes environment with kind, Telepresence, and Make. Use for Craft sandbox development; use the Compose guide when testing the Docker sandbox backend.
---

# Onyx Craft development

Run commands from the checkout being tested. Use the existing Make targets and VS Code tasks.
The implementation lives in [dev.py](../../../deployment/helm/dev/dev.py); do not replace it with ad hoc lifecycle scripts.

Read [the local Kubernetes guide](../../../docs/craft/dev/local-kubernetes.md) for setup, environment variables, and recovery.
For `SANDBOX_BACKEND=docker`, follow [the Compose guide](../../../docs/craft/dev/local-compose-craft.md) instead.
For ordinary development without Kubernetes sandboxes, use the `onyx-dev-stack` skill.

## Inspect and start

Run `make craft-doctor` for read-only setup checks. It exits nonzero when required checks fail.
It checks the pinned backend, dev, and EE dependencies, and resolves effective settings without printing secret values.
It also checks the sandbox PodTemplate image and pull policy against the selected local image.
Unset model credentials produce a warning. Doctor does not verify application login or license status.

Check Docker access and the required tools: `kind`, `kubectl`, `helm`, and Telepresence v2.
Use a Kubernetes node image at version 1.33 or later for native init sidecars.
Match kubectl to the cluster's supported version skew. Set `KIND_NODE_IMAGE` when creating a different node version.

```bash
make craft-doctor
kind get clusters
kubectl config get-contexts
telepresence status --format json
make craft-up
```

`craft-up` installs the Helm release and loads the sandbox image. It builds only when that image is missing.
It creates absent environment files and preserves existing files.
Keep `.vscode/.env.k8s` and `.vscode/.env.web` private and untracked.
The shared launcher resolves ConfigMaps, Secret references, and inline settings from the deployed API container.
Use `.env.k8s` only for personal overrides. Remove old service entries to follow chart settings automatically.
Launch tasks never rewrite this file. Resolved secrets stay in process memory.

The default cluster is `onyx-dev`; application services use `onyx`, and sandbox pods use `onyx-sandboxes`.
For another environment, export its variables before running Make or standalone commands:

```bash
export CLUSTER_NAME=my-cluster
export NAMESPACE=onyx
make craft-up
```

Keep these exports in each terminal used for that environment.
Use explicit `kubectl --context kind-<cluster>` arguments for inspection and recovery.

Telepresence provides access to cluster services from local application processes.
For the first connection, run this command in the developer's interactive terminal, including over SSH:

```bash
telepresence connect --context "kind-${CLUSTER_NAME:-onyx-dev}" -n "${NAMESPACE:-onyx}"
```

The networking daemon can require a sudo password. Automated tasks cannot answer that prompt.
After connection, use the VS Code `(k8s)` launch profiles, or run `make craft-api` in a terminal.
`launch.py` provides the same environment and reload behavior in both cases.
Worker profiles connect without recreating the API intercept.
`craft-up` waits for infrastructure, then reports that local services still need to start.
After starting the API and web server, run `make craft-ready` to verify the API through the frontend proxy.
The VS Code compound also starts this check. Readiness failure is not a successful startup.
A connection alone does not start the local API or create its intercept.

## Choose the smallest refresh

| Change or task | Command |
| --- | --- |
| Compare local images with this checkout | `make craft-check-images` |
| Refresh the sandbox image and PodTemplate | `make craft-sandbox-image` |
| Refresh the in-cluster API and sandbox proxy | `make craft-backend-image` |
| Refresh both images | `make craft-refresh-images` |
| Force a sandbox build during startup | `deployment/helm/dev/craft-up.sh --rebuild-sandbox-image` |

Image checks include tracked and non-ignored source files, including uncommitted edits.
Refresh commands reuse matching images and build changed source.
Local API and web edits use the existing development processes; they usually need no image build.

A sandbox image refresh updates the PodTemplate for future pods. Existing sandbox pods retain their image.
Do not claim that loading an image replaces live sandboxes.
Backend refreshes restart the API and proxy deployments; check their rollout results and reported image IDs.

Worktrees share the default mutable image tags. Do not run concurrent builds against those same tags.
For separate environments, use distinct clusters and `BACKEND_IMAGE` / `SANDBOX_IMAGE` tags.
Keep the chart image values and `.env.k8s` sandbox image configuration consistent with those tags.

## Migrate and verify

```bash
make craft-migration-status
make craft-migrate
```

These commands use the checkout's `.venv` and `.vscode/.env.k8s`.
They resolve cluster credentials, connect Telepresence, and reject database target overrides that differ from the deployment.
Stop local Onyx API and Celery processes before an upgrade. Do not kill unrelated processes to bypass this check.
A failed migration is a failed operation; inspect the error before retrying.

Check workloads with `kubectl --context "kind-${CLUSTER_NAME:-onyx-dev}" -n "${NAMESPACE:-onyx}" get pods`.
For sandbox failures, inspect pods, events, and container logs in `onyx-sandboxes`.
Use the frontend URL for API verification, as required by the repository instructions.
Report separately whether infrastructure, application services, and a real Craft operation were verified.
Craft API operations require a valid Business or Enterprise license; use a development license for local smoke tests.
The `ENABLE_CRAFT` flag alone does not grant access.

## Preserve data and control disk use

Stop the local launch compound before pausing the cluster:

```bash
make craft-pause
make craft-resume
make craft-disk
make craft-clean
make craft-clean CLEAN_ARGS=--apply
```

Pause preserves cluster data. Resume starts the nodes, waits for infrastructure, and reconnects Telepresence.
Relaunch local services to restore the API intercept after resume.
`make craft-down` deletes the cluster and its data; use it when teardown is requested.

Cleanup defaults to a preview. It removes only unused dangling images labeled for this checkout.
It preserves tagged images, container-referenced images, unlabeled images, kind runtime images, and volumes.
Run checkout cleanup before removing its worktree; worktree deletion does not trigger resource cleanup.

Build cache is shared across projects. Use `CLEAN_ARGS=--build-cache` to preview its separate cleanup.
Add `--apply` only when cache cleanup is in scope. It considers entries unused for seven days with a 10GB retention target.
This is not a total disk limit. Do not substitute a global Docker prune for checkout cleanup.

For changes to the workflow tools, run their regression tests:

```bash
.venv/bin/python -m unittest discover -s deployment/helm/dev/tests -v
```
