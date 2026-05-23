# Onyx Local Cluster — Tilt + k3d

How to run the full Onyx stack on your laptop in a real Kubernetes cluster,
with hot-reload of api / celery / web / sandbox-proxy, supporting **multiple
worktrees on one shared infra**.

This is the supported local-Kubernetes workflow. The previous kind +
Telepresence path is gone; tear down the old `onyx-dev` cluster and follow
this guide.

---

## When you'd use this

The default workflow ([CONTRIBUTING.md](/CONTRIBUTING.md): docker-compose deps
+ Python in the VSCode debugger) is faster for ~80% of changes. Reach for
this Tilt + k3d path when you need:

- Prod-parity behavior that docker-compose can't exercise: NetworkPolicies,
  RBAC, init containers, ServiceAccount-projected tokens, sandbox-proxy
  pod-identity.
- Craft (`SANDBOX_BACKEND=kubernetes`) — sandboxes are real pods, so chart /
  pod-spec / cluster-side changes must run in-cluster.
- Multiple worktrees side by side, each with isolated state.

---

## Architecture at a glance

One k3d cluster (`onyx-local`) on your laptop. Inside it:

```
k3d cluster: onyx-local
│
├── ns: onyx-infra        ← SHARED (one bring-up per machine)
│   ├── ingress-nginx     ← cluster-wide ingress
│   ├── cnpg cluster      ← one Postgres, N databases (one per worktree)
│   ├── opensearch        ← one cluster, indexes prefixed per worktree
│   ├── minio             ← one MinIO, one bucket per worktree
│   ├── redis             ← one Redis instance, separate DB number per worktree
│   ├── inference-model   ← shared (no tenant state)
│   └── indexing-model    ← shared (no tenant state)
│
├── ns: onyx-<slug-a>     ← PER WORKTREE (one bring-up per worktree)
│   ├── api-server
│   ├── celery-* (8 workers + beat)
│   ├── webserver         (`next dev` w/ HMR)
│   ├── sandbox-proxy
│   └── ingress → <slug-a>.onyx.localhost
│
├── ns: onyx-<slug-a>-sandboxes  ← sandbox pods spawned by api
├── ns: onyx-<slug-b>     ← second worktree, same shape
└── ns: onyx-<slug-b>-sandboxes
```

**Why a single cluster, not one per worktree?** k3d clusters cost ~1.5 GB
RAM each just for the control plane and CNI. Sharing the heavy stateful
pods (postgres, opensearch, minio) across worktrees keeps a 4-worktree
setup at ~10 GB instead of ~30 GB.

### What's isolated per worktree

| Resource | Isolation mechanism |
|---|---|
| Postgres | A separate logical DATABASE per worktree (`postgres_<slug>`). Same superuser, same CNPG cluster. `DROP DATABASE` nukes the worktree's state. |
| MinIO | A separate bucket per worktree (`onyx-<slug>`). `S3_FILE_STORE_BUCKET_NAME` points at it. |
| Redis | A separate DB number per worktree, allocated in groups of 3 (worker DB, celery result, celery broker). Redis is reconfigured with `databases 256` for headroom. |
| App pods | Own namespace `onyx-<slug>`. |
| Sandbox pods | Own namespace `onyx-<slug>-sandboxes`. |
| Ingress hostname | `<slug>.onyx.localhost` (RFC 6761 — all `*.localhost` resolves to 127.0.0.1 without DNS setup). |
| Tilt UI port | Allocated per worktree (10350 + offset). |

### What's NOT isolated (and why it's fine)

- **OpenSearch index names.** Index names live in each worktree's
  `search_settings` table — but the seed value
  (`danswer_chunk_<encoder>`) is identical across worktrees, so two
  worktrees indexing concurrently would collide. In practice, only one
  worktree at a time runs indexing tests, so this is acceptable. See
  [Multi-tenant follow-up](#multi-tenant-follow-up) for a future fix.
- **Model servers.** Inference + indexing model containers are stateless;
  share them.

---

## One-time machine setup

### 1. Install tools

```bash
brew bundle   # repo-root Brewfile
```

Installs `k3d`, `tilt`, `kubectl`, `helm`, `k9s`, `stern`, `jq`, `direnv`.

Docker Desktop should have at least **6 CPU / 12 GB RAM** allocated (more if
you plan to run > 2 worktrees concurrently).

### 1a. Enable direnv (one-time)

The repo's `.envrc` scopes `KUBECONFIG` to the local k3d cluster so naked
`kubectl` / `helm` from inside the repo can't accidentally hit prod or
staging. Hook direnv into your shell once:

```bash
# zsh
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc

# bash
echo 'eval "$(direnv hook bash)"' >> ~/.bashrc
```

Then, in this checkout:

```bash
direnv allow .
```

After that, every shell entering the repo gets `KUBECONFIG=~/.kube/onyx-local.yaml`
automatically. Outside the repo, your usual contexts (prod, staging) are
unaffected.

### 2. Bring up everything

One command, run from the worktree you want to launch:

```bash
deployment/helm/dev/dev.sh up
```

This is the only command you need on first run. Idempotent — re-run any
time. What it does, in order:

1. Creates a k3d-managed Docker registry at `localhost:5001` if absent.
   Tilt pushes locally-built images here; the cluster pulls from it
   without `docker save | kind load` overhead.
2. Creates the k3d cluster `onyx-local` if absent (Traefik + ServiceLB
   disabled — we use ingress-nginx via the upstream subchart).
3. Writes `~/.kube/onyx-local.yaml`. **Use this as `KUBECONFIG`** so
   prod/staging contexts in `~/.kube/config` are unreachable from inside
   the repo:

   ```bash
   export KUBECONFIG=~/.kube/onyx-local.yaml
   ```

   The Tiltfile pins `allow_k8s_contexts('k3d-onyx-local')` as a
   belt-and-suspenders.

4. Pre-installs the **CNPG operator** (separate Helm release, namespace
   `cnpg-system`) and the **opstree redis-operator**. Doing this before
   the app chart fixes a known race where the operator's mutating webhook
   isn't reachable when the Cluster CR is applied.
5. Installs the onyx chart with `values-dev-infra.yaml` overlay into
   namespace `onyx-infra` if absent. This release renders only the shared
   infra resources — postgres Cluster CR, opensearch, minio, redis,
   ingress-nginx, model servers. App pods (api / celery / web) are
   scaled to 0 in the infra release.
6. **Per-worktree provisioning** (every run):
   - Derives a **slug** from the current git branch (sanitized to
     `[a-z0-9-]+`, ≤40 chars). Override with `--slug <name>`.
   - Allocates a **Tilt UI port** (10350 + first free offset) and a
     **Redis DB number range** (3 consecutive DBs from `n*3`), recorded
     in `~/.config/onyx-dev/<slug>.json`.
   - Creates database `postgres_<slug>` on the shared CNPG cluster.
   - Creates MinIO bucket `onyx-<slug>`.
   - Creates namespaces `onyx-<slug>` + `onyx-<slug>-sandboxes`.
   - Writes `~/.config/onyx-dev/<slug>.values.yaml` (per-worktree helm
     overlay).
7. Execs `tilt up --port <allocated>` from the repo root. Tilt builds
   the backend + web-dev images, pushes to the local registry, and
   `helm upgrade --install onyx-<slug>` into the worktree namespace.

First boot: ~5–8 min on a cold cluster (image pulls, CNPG bootstrap,
OpenSearch warmup, first build of the dev images). Subsequent invocations
in the same worktree: ~10–30 s.

### 3. Hit the app

- **Tilt UI** at `http://localhost:<allocated-port>` (printed at launch).
  Per-resource status, log panes, restart buttons.
- **App** at `http://<slug>.onyx.localhost:13000`. RFC 6761 resolves
  `*.localhost` to 127.0.0.1 with no DNS setup.
- Login: `a@example.com` / `a` (seeded by the dev license).

### Subsequent worktrees

Repeat `dev.sh up` from a sibling worktree. The shared cluster and infra
are re-used; only per-worktree state changes. Multiple worktrees run
concurrently; each Tilt session owns its own port-forwards and namespace.

---

## Day-to-day commands

```bash
deployment/helm/dev/dev.sh up        # bring up (or re-attach to) this worktree
deployment/helm/dev/dev.sh stop      # pause the cluster — data preserved
deployment/helm/dev/dev.sh start     # resume the paused cluster
deployment/helm/dev/dev.sh status    # show cluster + worktree state
```

**`stop` is the default end-of-day action.** It stops the k3d node
containers; PVC data (postgres, opensearch, minio) and the local
registry survive. Resume with `dev.sh start` and the kubelet reconciles
pods automatically — no re-provisioning, no `dev.sh up` needed unless
you want to add a new worktree.

Destructive commands are intentionally **not** wired into VSCode tasks:

```bash
deployment/helm/dev/dev.sh nuke worktree           # drop THIS worktree's DB+bucket+namespaces
deployment/helm/dev/dev.sh nuke worktree --slug X  # specific worktree
deployment/helm/dev/dev.sh nuke all                # delete cluster + registry + all worktree state
```

Each prompts for confirmation. Reach for `nuke` only when you actually
want to lose data — for clean app-pod restarts the Tilt UI's "Restart"
button is what you want.

---

## Hot-reload iteration loop

| What you changed | What happens |
|---|---|
| Python in `backend/onyx/` or `backend/ee/` | Tilt `sync()`s the file into the backend pods (api + all celery), then `restart_container()` so they re-exec with the new code. **p50 3–5 s.** |
| `web/` source | Tilt `sync()`s into the webserver pod. `next dev` HMR re-renders in the browser. **p50 <1 s.** |
| `backend/requirements/*.txt` or `backend/Dockerfile` | Tilt rebuilds the backend image. **p50 30–90 s.** |
| `web/package.json` or `web/Dockerfile.dev` | Tilt rebuilds the web-dev image. |
| Helm chart templates / values | Restart the `onyx-<slug>` resource in the Tilt UI (or Ctrl-C and re-run `dev.sh up`). |
| Chart subchart versions or infra config | `dev.sh nuke all && dev.sh up` (the only path that re-runs the infra install). |

### Logs

- **Tilt UI** (`localhost:<tilt-port>`) — primary surface.
- `stern -n onyx-<slug> '.*'` — multi-pod tail in a terminal.
- `kubectl logs -n onyx-<slug> -f deploy/onyx-<slug>-api-server`.

---

## Debugger (Python breakpoints in VSCode)

Every backend service runs under `debugpy --listen 0.0.0.0:<port>`. Tilt
forwards each port to a deterministic host port; `.vscode/launch.json`
has matching **attach** configs.

| Service | Port |
|---|---|
| `Attach API Server (cluster)` | 5678 |
| `Attach Celery beat (cluster)` | 5679 |
| `Attach Celery primary (cluster)` | 5680 |
| `Attach Celery light (cluster)` | 5681 |
| `Attach Celery heavy (cluster)` | 5682 |
| `Attach Celery docfetching (cluster)` | 5683 |
| `Attach Celery docprocessing (cluster)` | 5684 |
| `Attach Celery monitoring (cluster)` | 5685 |
| `Attach Celery user_file_processing (cluster)` | 5686 |
| `Attach Celery scheduled_tasks (cluster)` | 5687 |

To debug:

1. `dev.sh up` (running)
2. VSCode → Debug panel → pick `Attach API Server (cluster)` (or
   `Attach All Onyx Services (cluster)` to attach every service at once).
3. Set breakpoints in `backend/onyx/...` and trigger the code path from
   the browser / curl.

`pathMappings` is wired so `${workspaceFolder}/backend` maps to `/app`
in the pod — breakpoints set against the local file system fire against
the synced source.

Debugpy uses `--listen` (not `--wait-for-client`), so pods don't block on
startup waiting for an attach. Attach any time; detach any time; the
service keeps running either way.

---

## Where things live

```
deployment/helm/dev/
└── dev.sh                One-script orchestrator: up / stop / start / status / nuke

deployment/helm/charts/onyx/
├── values-dev-infra.yaml   onyx-infra overlay (subcharts on, app pods off)
└── values-dev-app.yaml     per-worktree overlay (subcharts off, app pods on,
                            debugpy-wrapped commands)

Tiltfile                Per-worktree Tilt driver (reads env from dev.sh)
Brewfile                k3d/tilt/kubectl/helm/k9s/stern/jq

web/Dockerfile.dev      Node 24 + bun image; `bun run dev` entrypoint for HMR
```

Per-worktree state lives in `~/.config/onyx-dev/<slug>.json` (allocation
record) and `~/.config/onyx-dev/<slug>.values.yaml` (rendered helm
overlay). Both are blown away by `dev.sh nuke worktree --slug <slug>`.

---

## Troubleshooting

### "context k3d-onyx-local not found"

`dev.sh up` writes `~/.kube/onyx-local.yaml`. The Tiltfile pins that
context. Either set `KUBECONFIG`:

```bash
export KUBECONFIG=~/.kube/onyx-local.yaml
```

…or merge it into your default kubeconfig:

```bash
k3d kubeconfig merge onyx-local --kubeconfig-merge-default
```

### "helm install pending-install" on re-run

A previous `tilt up` got Ctrl-C'd mid-install. `dev.sh up` auto-detects
and clears stuck `pending-*` releases on the next run, so just re-run:

```bash
deployment/helm/dev/dev.sh up
```

### Two worktrees see each other's data

Most common cause: same slug. `dev.sh up` derives the slug from
`git branch --show-current`. Two checkouts with the same branch name
(`main`, e.g.) collide. Pass `--slug feature-a` / `--slug feature-b`
explicitly:

```bash
deployment/helm/dev/dev.sh up --slug feature-a
```

### CNPG operator on Docker Desktop k8s

Docker Desktop's bundled Kubernetes fails CNPG with
`unable to setup PKI infrastructure`. Use k3d (the default) — Docker
Desktop k8s is not supported.

### Browser shows "ERR_CONNECTION_REFUSED" on `<slug>.onyx.localhost:13000`

The Tilt port-forward isn't running. Check the `pf-ingress` resource in
the Tilt UI; restart it if it's red. The forward goes from your laptop's
`13000` to the `onyx-nginx-controller` Service in `onyx-infra`.

---

## Multi-tenant follow-up

Onyx supports multi-tenant mode (`MULTI_TENANT=true`) where one app
deployment serves N tenant schemas. Adding multi-tenant to this dev
workflow is **not implemented in Phase 1**. The pieces needed:

1. **Per-worktree multi-tenant flag.** `values-dev-app.yaml` sets
   `MULTI_TENANT=true` and the worktree's app pods read tenants from the
   shared CNPG cluster. The worktree's database (`postgres_<slug>`)
   already supports schemas — multi-tenant just creates more.
2. **Tenant Service deployment.** The chart already templates
   `tenant-service.yaml` (in `templates_disabled/`). Move it back, gate
   on `tenantService.enabled`, deploy per worktree.
3. **OpenSearch index prefix.** The collision risk gets real with N
   tenants per worktree. Add an `OPENSEARCH_INDEX_NAME_PREFIX` env var
   that the alembic seeding migration
   (`backend/alembic/versions/dbaa756c2ccf_embedding_models.py`) prepends
   to `danswer_chunk_<encoder>`. Set per worktree from values.
4. **`alembic_tenants` pipeline.** The shared-schema migrations need to
   run against the worktree's database on first `worktree-up`. Wire into
   the script as a pre-step (`python -m alembic_tenants upgrade head`
   in a kubectl exec or one-off pod).
5. **Tenant seeding script.** A new `deployment/helm/dev/seed-tenant.sh`
   that calls the api's `POST /tenants/create` to spin a tenant against
   the worktree's api.

None of the above touches the production helm chart in ways that
back-compat the kind/Telepresence workflow couldn't already support, so
the chart edits land cleanly when we're ready.

---

## References

- [CONTRIBUTING.md — Development Setup](/CONTRIBUTING.md#development-setup)
- [deployment/helm/README.md](/deployment/helm/README.md)
- [backend/onyx/server/features/build/sandbox/README.md](/backend/onyx/server/features/build/sandbox/README.md)
- [k3d docs](https://k3d.io/)
- [Tilt docs](https://docs.tilt.dev/)
