# Tiltfile — Onyx local-cluster (per-worktree).
#
# Invoked by deployment/helm/dev/dev.sh after the worktree slug / Tilt port
# / namespace / values file have been allocated. The script exec()s
# `tilt up --port $TILT_PORT` from the repo root with the env vars this
# Tiltfile reads below.
#
# What this does:
#   1. Builds the onyx-backend image (with debugpy) and pushes to the
#      local k3d registry. live_update syncs backend/onyx and backend/ee
#      into the running pods. The chart's command override runs each
#      backend process under backend/scripts/dev_{api,celery}_reload.py,
#      which uses watchfiles to re-exec the inner process on source change.
#   2. Builds the onyx-web-dev image. live_update syncs web/ into /app;
#      bun's `next dev` HMR reloads in the browser (~sub-second).
#   3. Renders the onyx Helm chart into onyx-<slug>, pointing at the
#      shared infra in onyx-infra.
#   4. Routes localhost:13000 -> k3d serverlb -> nodePort 30080 -> the
#      shared ingress-nginx so the browser can reach
#      <slug>.onyx.localhost:13000. The host->nodePort map lives in
#      dev.sh's `k3d cluster create -p` flag; no kubectl port-forward.
#   5. Port-forwards each backend pod's debugpy port (5678–5687) so
#      VSCode attach configs (see .vscode/launch.json) can hit
#      breakpoints in the synced source.
#
# See docs/dev/local-cluster.md.

# ---- 0. Required env from dev.sh ----

SLUG = os.getenv('WORKTREE_SLUG')
APP_NS = os.getenv('WORKTREE_APP_NS')
APP_RELEASE = os.getenv('WORKTREE_APP_RELEASE')
INGRESS_HOST = os.getenv('WORKTREE_INGRESS_HOST')
VALUES_FILE = os.getenv('WORKTREE_VALUES_FILE')
NEXT_PORT = os.getenv('WORKTREE_NEXT_PORT')

if not SLUG or not APP_NS or not APP_RELEASE or not INGRESS_HOST or not VALUES_FILE or not NEXT_PORT:
    fail(
        'Tiltfile must be launched by deployment/helm/dev/dev.sh.\n' +
        'Required env vars: WORKTREE_SLUG, WORKTREE_APP_NS, WORKTREE_APP_RELEASE,\n' +
        'WORKTREE_INGRESS_HOST, WORKTREE_VALUES_FILE, WORKTREE_NEXT_PORT.'
    )

# ---- 1. Safety: only operate against the local k3d cluster ----

allow_k8s_contexts('k3d-onyx-local')

# ---- 2. Registry config ----
#
# Tilt pushes locally-built images to localhost:5001 (the k3d-managed
# registry created by dev.sh). The cluster pulls from the same registry
# via the k3d --registry-use config. host_from_cluster is the in-cluster
# DNS name of the registry container.

default_registry(
    'localhost:5001',
    host_from_cluster='k3d-onyx-registry:5001',
)

# ---- 3. Update settings ----

update_settings(max_parallel_updates=4, k8s_upsert_timeout_secs=600)

# ---- 4. Backend image (api + all celery workers) ----
#
# api + every celery worker shares the onyx-backend image. INSTALL_DEBUGPY=true
# at build time so the chart's `<svc>.debug.enabled` wrap finds debugpy on
# $PATH. Sync source files into every pod and restart_container() so the
# new code takes effect.

docker_build(
    'onyxdotapp/onyx-backend-dev',
    context='./backend',
    dockerfile='./backend/Dockerfile',
    build_args={
        'ENABLE_CRAFT': 'true',
        'INSTALL_DEBUGPY': 'true',
    },
    # Only source-tree dirs go in live_update. Config-shaped files
    # (`requirements/*.txt`, `Dockerfile`, `alembic.ini`) intentionally
    # do NOT — Tilt's live_update syncs into already-running pods but
    # does not refresh the image, so a subsequent pod restart (helm
    # upgrade, OOM, manual delete) would boot from the stale image and
    # mask dev edits. Files outside live_update trigger image rebuilds
    # on change, keeping image + running pods consistent.
    live_update=[
        sync('./backend/onyx', '/app/onyx'),
        sync('./backend/ee', '/app/ee'),
        sync('./backend/scripts', '/app/scripts'),
        sync('./backend/shared_configs', '/app/shared_configs'),
        sync('./backend/alembic', '/app/alembic'),
    ],
)

# ---- 5. Web dev (native on host, not in cluster) ----
# `next dev` runs on macOS via `local_resource` below (see section 9).
# values-dev-app.yaml sets webserver.replicaCount=0 so the chart omits
# the Deployment + Service + Ingress for the webserver.

# ---- 6. App chart (helm template -> per-workload Tilt resources) ----
#
# We render the chart locally with helm() and feed the manifests to
# k8s_yaml(). Unlike the helm_resource extension — which tracks the whole
# release as ONE Tilt resource and bundles every pod's logs together —
# k8s_yaml() lets Tilt assemble one resource per workload, so each
# deployment (api-server, web-server, every celery worker) has its own
# logs and readiness in the Tilt UI.
#
# Notes:
#   - helm() runs `helm template`: there is no Helm release object. dev.sh
#     tears a worktree down by deleting its namespace, not `helm uninstall`.
#   - helm() skips chart hooks. The chart's only hook (pre-delete CR
#     cleanup) is guarded by postgresql/redis .enabled, both false in dev
#     (shared infra), so it renders to nothing regardless.
#   - skip_crds=True: the CNPG CRDs under the chart's crds/ dir are owned
#     by the shared infra release in onyx-infra. helm() includes crds/ by
#     default (unlike raw `helm template`); re-applying here would conflict.
#   - The image repositories are overridden to the dev build refs so Tilt
#     associates them with the docker_build()s above. Tilt matches images
#     by repository name; the tag is ignored.
#   - dev.sh creates APP_NS before `tilt up`; helm() does not create it.

k8s_yaml(helm(
    './deployment/helm/charts/onyx',
    name=APP_RELEASE,
    namespace=APP_NS,
    values=[
        './deployment/helm/charts/onyx/values-dev-app.yaml',
        VALUES_FILE,
    ],
    set=[
        'api.image.repository=onyxdotapp/onyx-backend-dev',
        'celery_shared.image.repository=onyxdotapp/onyx-backend-dev',
    ],
    skip_crds=True,
))

# One Tilt resource per chart Deployment. Tilt names each resource after
# the workload's metadata.name (APP_RELEASE + suffix). Grouping them under
# the 'app' label keeps the UI tidy; referencing a name the chart did not
# render would fail the Tiltfile, so this list must track the chart.
APP_WORKLOAD_SUFFIXES = [
    'api-server',
    'celery-beat',
    'celery-worker-primary',
    'celery-worker-light',
    'celery-worker-heavy',
    'celery-worker-docfetching',
    'celery-worker-docprocessing',
    'celery-worker-monitoring',
    'celery-worker-user-file-processing',
    'celery-worker-scheduled-tasks',
    'sandbox-proxy',
]

for suffix in APP_WORKLOAD_SUFFIXES:
    k8s_resource(APP_RELEASE + '-' + suffix, labels=['app'])

# ---- 7. Ingress access (no port-forward) ----
#
# Browser → localhost:13000 → k3d serverlb → nodePort 30080 →
# ingress-nginx in onyx-infra → routed by host. The host→nodePort mapping
# is declared in dev.sh's `k3d cluster create -p` flag; the nginx Service
# is NodePort (values-dev-infra.yaml). RFC 6761 resolves *.localhost to
# 127.0.0.1 with no DNS setup.
#
# This replaces a `kubectl port-forward` to the controller. That tunnel
# rides a SPDY stream that drops long-lived connections (next-dev HMR
# websockets, chat SSE), which manifested as recurring "lost connection to
# pod" failures. The serverlb is a real TCP proxy and holds them fine.

# ---- 8. Debugger port-forwards ----
#
# One per backend pod. Ports match values-dev-app.yaml and the VSCode
# attach configs in .vscode/launch.json. `kubectl port-forward` accepts
# any TCP port on the pod regardless of containerPorts.
#
# We forward to the Deployment (not a Service) — none of these pods has
# a Service for the debug port. The Deployment label-selector picks the
# single replica each Deployment runs.

# (service_name_in_chart, host_port, deployment_name_suffix)
DEBUG_TARGETS = [
    ('api',                                 5678, 'api-server'),
    ('celery-beat',                         5679, 'celery-beat'),
    ('celery-worker-primary',               5680, 'celery-worker-primary'),
    ('celery-worker-light',                 5681, 'celery-worker-light'),
    ('celery-worker-heavy',                 5682, 'celery-worker-heavy'),
    ('celery-worker-docfetching',           5683, 'celery-worker-docfetching'),
    ('celery-worker-docprocessing',         5684, 'celery-worker-docprocessing'),
    ('celery-worker-monitoring',            5685, 'celery-worker-monitoring'),
    ('celery-worker-user-file-processing',  5686, 'celery-worker-user-file-processing'),
    ('celery-worker-scheduled-tasks',       5687, 'celery-worker-scheduled-tasks'),
]

for (label, host_port, deploy_suffix) in DEBUG_TARGETS:
    local_resource(
        'pf-debug-' + label,
        serve_cmd=(
            'kubectl --context k3d-onyx-local -n ' + APP_NS +
            ' port-forward deployment/' + APP_RELEASE + '-' + deploy_suffix +
            ' ' + str(host_port) + ':' + str(host_port)
        ),
        resource_deps=[APP_RELEASE + '-' + deploy_suffix],
        # Hide debug-forward output from the default Tilt UI view — they're
        # noisy with reconnect messages every time a pod restarts.
        labels=['debug'],
    )

# ---- 9. next-dev (native on host) ----
# /api/* is proxied by web/src/app/api/[...path]/route.ts to INTERNAL_URL.
# INTERNAL_URL ends in /api so the cluster ingress's /api(/|$)(.*) rewrite
# strips it back off before the api-server sees the path.
local_resource(
    'next-dev',
    serve_cmd=(
        'cd ' + os.getcwd() + '/web && ' +
        'INTERNAL_URL=http://' + INGRESS_HOST + ':13000/api ' +
        'PORT=' + NEXT_PORT + ' ' +
        'AUTH_TYPE=basic ENABLE_CRAFT=true DEV_MODE=true ' +
        'WEB_DOMAIN=http://localhost:' + NEXT_PORT + ' ' +
        'bun run dev'
    ),
    resource_deps=[APP_RELEASE + '-api-server'],
    readiness_probe=probe(
        http_get=http_get_action(port=int(NEXT_PORT), path='/'),
        period_secs=2,
        timeout_secs=2,
    ),
    labels=['app'],
)

# ---- 10. Craft sandbox pods (dynamic, not in chart) ----
# Stern tails all sandbox pod logs (including init containers) and surfaces
# pod lifecycle events, so a sandbox failure shows up here instead of being
# discoverable only via kubectl.
local_resource(
    'sandbox-pods',
    serve_cmd=(
        'stern --context k3d-onyx-local ' +
        '--namespace ' + APP_NS + '-sandboxes ' +
        '--since 5m --tail 100 sandbox-'
    ),
    resource_deps=[APP_RELEASE + '-api-server'],
    labels=['app'],
)
