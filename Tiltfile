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
#      into the running pods; restart_container on each sync.
#   2. Builds the onyx-web-dev image. live_update syncs web/ into /app;
#      bun's `next dev` HMR reloads in the browser (~sub-second).
#   3. Renders the onyx Helm chart into onyx-<slug>, pointing at the
#      shared infra in onyx-infra.
#   4. Port-forwards localhost:13000 -> the shared ingress-nginx so the
#      browser can reach <slug>.onyx.localhost:13000.
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

if not SLUG or not APP_NS or not APP_RELEASE or not INGRESS_HOST or not VALUES_FILE:
    fail(
        'Tiltfile must be launched by deployment/helm/dev/dev.sh.\n'
        'Required env vars: WORKTREE_SLUG, WORKTREE_APP_NS, WORKTREE_APP_RELEASE,\n'
        'WORKTREE_INGRESS_HOST, WORKTREE_VALUES_FILE.'
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

load('ext://helm_resource', 'helm_resource')

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
    live_update=[
        sync('./backend/onyx', '/app/onyx'),
        sync('./backend/ee', '/app/ee'),
        sync('./backend/scripts', '/app/scripts'),
        sync('./backend/shared_configs', '/app/shared_configs'),
        sync('./backend/alembic', '/app/alembic'),
        restart_container(),
    ],
)

# ---- 5. Web dev image (next dev with HMR) ----

docker_build(
    'onyxdotapp/onyx-web-dev',
    context='./web',
    dockerfile='./web/Dockerfile.dev',
    live_update=[
        sync('./web/src', '/app/src'),
        sync('./web/public', '/app/public'),
        sync('./web/lib', '/app/lib'),
        sync('./web/types', '/app/types'),
        sync('./web/next.config.js', '/app/next.config.js'),
        sync('./web/tailwind.config.js', '/app/tailwind.config.js'),
        sync('./web/postcss.config.js', '/app/postcss.config.js'),
        sync('./web/tsconfig.json', '/app/tsconfig.json'),
    ],
)

# ---- 6. App chart (helm install into onyx-<slug>) ----

helm_resource(
    APP_RELEASE,
    './deployment/helm/charts/onyx',
    namespace=APP_NS,
    flags=[
        '-f', './deployment/helm/charts/onyx/values-dev-app.yaml',
        '-f', VALUES_FILE,
        '--wait',
        '--timeout=10m',
    ],
    image_deps=[
        'onyxdotapp/onyx-backend-dev',
        'onyxdotapp/onyx-web-dev',
    ],
    image_keys=[
        [
            ('api.image.repository', 'api.image.tag'),
            ('celery_shared.image.repository', 'celery_shared.image.tag'),
        ],
        ('webserver.image.repository', 'webserver.image.tag'),
    ],
)

# ---- 7. Port-forwards ----
#
# Browser → localhost:13000 → ingress-nginx in onyx-infra → routed by host.
# RFC 6761 resolves *.localhost to 127.0.0.1 with no DNS setup.

local_resource(
    'pf-ingress',
    serve_cmd='kubectl --context k3d-onyx-local -n onyx-infra port-forward svc/onyx-infra-nginx-controller 13000:80',
    resource_deps=[APP_RELEASE],
)

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
        resource_deps=[APP_RELEASE],
        # Hide debug-forward output from the default Tilt UI view — they're
        # noisy with reconnect messages every time a pod restarts.
        labels=['debug'],
    )
