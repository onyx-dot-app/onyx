# Craft Tilt Local-Dev (Phase 1)

How to run the full Onyx stack inside a local k3d cluster with hot-reload of
backend code via Tilt.

## When you'd use this

The default development workflow in
[CONTRIBUTING.md](/CONTRIBUTING.md) (docker-compose + Python processes in
the VSCode debugger) is faster and covers most Craft work. Reach for this
Tilt path when you need prod-parity behavior that docker-compose can't
exercise: pod networking, RBAC, NetworkPolicies, init containers,
ServiceAccount-projected tokens, sandbox-proxy pod-identity flow.

The existing kind + Telepresence path
([local-kubernetes.md](./local-kubernetes.md)) remains supported.
`k3d + Tilt` lives alongside it as the direction for Craft-specific work
that doesn't fit Telepresence's intercept model.

## Prereqs

```bash
brew bundle   # installs k3d, tilt, kubectl, helm, k9s, stern from repo-root Brewfile
```

Docker Desktop should be running with at least 8 CPU / 16 GB allocated.

## Run the stack

```bash
bash deployment/helm/dev/k3d-up.sh
```

This is the only command. It is idempotent. It:

- Creates a k3d-managed Docker registry at `localhost:5001` (port 5000 is
  reserved for AirPlay Receiver on recent macOS) if absent.
- Creates a k3d cluster named `onyx-local` wired to pull from the registry,
  with Traefik + ServiceLB disabled (the onyx chart's ingress-nginx subchart
  owns ingress) if absent.
- Writes a standalone kubeconfig at `~/.kube/onyx-local.yaml`.
- Creates the `onyx` namespace if absent.
- Execs `tilt up` with `KUBECONFIG` scoped to the local cluster file.

The Tiltfile at the repo root:

- Builds `onyxdotapp/onyx-backend` from `backend/Dockerfile` and pushes to
  the local registry.
- Renders and applies the `onyx` Helm chart with
  `values-localdev.yaml` + `values-tilt.yaml` overlays — bringing up
  CNPG, OpenSearch, MinIO, Redis, ingress-nginx, model servers, api,
  webserver, all celery workers, and sandbox-proxy in-cluster.
- Watches `backend/onyx/`, `backend/ee/`, and `backend/shared_configs/`
  for changes. On save, Tilt syncs the changed files into every pod
  using the backend image and restarts the in-pod process. No image
  rebuild, no `kubectl apply`.

First boot takes a few minutes (image pulls, CNPG bootstrap, OpenSearch
warmup). Subsequent edit-to-restart cycles are sub-second once pods are
healthy.

Open `http://localhost:10350` for the Tilt UI: per-service status, log
panes, restart buttons.

## Hit the app

Tilt forwards:

- `http://localhost:3000` → webserver
- `http://localhost:8080` → api

Log in with `a@example.com` / `a` (seeded by the dev license).

## Iteration loop

| What you changed | What happens |
|---|---|
| Python in `backend/onyx/` or `backend/ee/` | Tilt syncs the file into api / celery / sandbox-proxy pods, restarts each container. p50 ~1–3s. |
| `backend/requirements/*.txt` or `backend/Dockerfile` | Tilt rebuilds the backend image. p50 ~30–90s depending on dep changes. |
| Helm chart templates / values | Re-run `tilt up` (or restart the resource in the Tilt UI). |
| Frontend (`web/`) | Not hot-reloaded in Phase 1 — webserver runs the published image. |

## Logs

Three layers:

- **Tilt UI** at `localhost:10350` — primary surface. Per-service log panes,
  filter, restart.
- `kubectl logs -f` from any terminal with the local KUBECONFIG.
- `stern -n onyx '.*'` for multi-pod tailing (install via `brew install
  stern`).

## Tear down

```bash
tilt down                   # Removes the rendered chart from the cluster.
k3d cluster delete onyx-local
k3d registry delete onyx-registry
```

Cluster deletion wipes all PVC data.

## Scope and follow-ups

Phase 1 is intentionally minimal. It proves the k3d + Tilt loop end-to-end
for backend hot-reload and lays the foundation for the broader Craft dev
workflow. Forthcoming work (see `plans/whuang/craft-tilt-migration.md`):

- Debugger attach via debugpy + a chart `command:` parameterization step.
- Per-worktree namespaces + ingress hostnames so multiple worktrees can
  run side by side.
- Heavy-tier (second k3d cluster) for migration / infra work.
- Frontend hot-reload.
- `ods k8s up` / `ods k8s tilt` / `ods k8s doctor` wrappers.
