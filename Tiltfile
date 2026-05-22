# Tiltfile — Craft local-dev (Phase 1)
#
# Brings up the full Onyx stack in the local k3d cluster created by
# `deployment/helm/dev/k3d-up.sh`. Hot-reload is handled by in-pod watchfiles
# wrappers driven by the chart's `command:` overrides in values-tilt.yaml —
# Tilt only sync()s files into pods; the in-pod reloader detects the change
# and re-execs the target process.
#
# Edit any file under backend/onyx/ or backend/ee/ and Tilt syncs the change
# into every pod using the onyx-backend image. The reloader inside the pod
# (currently wired only for sandbox-proxy in Phase 1) restarts the process.
# api/celery use the chart's default commands today; reload wrappers for
# them land in a follow-up.
#
# See docs/dev/craft-tilt-dev.md for the workflow.

# Refuse to operate against anything but the local k3d cluster. Protects
# against fat-fingered kubectl context pointing at prod/staging.
allow_k8s_contexts('k3d-onyx-local')

# Locally-built images are pushed to the registry created by k3d-up.sh;
# the cluster pulls from the same registry via k3d's `--registry-use` config.
# `host_from_cluster` is the in-cluster DNS name of the registry container.
default_registry(
    'localhost:5001',
    host_from_cluster='k3d-onyx-registry:5001',
)

# Default apply timeout is 30s; the onyx chart's `helm install --wait` runs
# for 5–10 min on a cold cluster (CNPG bootstrap, OpenSearch warmup, image
# pulls). Bump generously.
update_settings(max_parallel_updates=4, k8s_upsert_timeout_secs=900)

# `helm_resource` shells out to real `helm upgrade --install`. This is what
# we want here (vs the built-in `k8s_yaml(helm())`, which runs offline
# `helm template` and applies everything in one parallel batch — racing CRD
# registration against CR creation for CNPG and the Redis operator).
load('ext://helm_resource', 'helm_resource')

# ---- Backend image (api + celery + sandbox-proxy) ----
#
# api, all celery workers, and sandbox-proxy share the onyxdotapp/onyx-backend
# image. Sync source files into every pod using that image. Per-Deployment
# `command:` overrides (set in values-tilt.yaml) wrap the real entrypoint
# with watchfiles.run_process, which detects the synced changes and re-execs
# the target process.

docker_build(
    'onyxdotapp/onyx-backend',
    context='./backend',
    dockerfile='./backend/Dockerfile',
    live_update=[
        sync('./backend/onyx', '/app/onyx'),
        sync('./backend/ee', '/app/ee'),
        sync('./backend/scripts', '/app/scripts'),
    ],
)

# ---- App chart ----
#
# `helm install --wait` handles CRD-before-CR ordering (CNPG Cluster, Redis
# instance) and waits for all resources to be Ready before declaring the
# release healthy. `--timeout=15m` covers cold image pulls + CNPG/OpenSearch
# bootstrap on a fresh cluster.

helm_resource(
    'onyx',
    './deployment/helm/charts/onyx',
    namespace='onyx',
    flags=[
        '-f', './deployment/helm/charts/onyx/values-localdev.yaml',
        '-f', './deployment/helm/charts/onyx/values-tilt.yaml',
        '--wait',
        '--timeout=15m',
    ],
    # api uses .Values.api.image; celery workers + sandbox-proxy use
    # .Values.celery_shared.image. Both reference the same backend image —
    # the helm_resource extension supports this via a list of tuples for
    # the matching image_keys entry.
    image_deps=['onyxdotapp/onyx-backend'],
    image_keys=[
        [('api.image.repository', 'api.image.tag'),
         ('celery_shared.image.repository', 'celery_shared.image.tag')],
    ],
)

# ---- Port-forward ----
#
# Browser hits onyx.localhost:13000 → port-forward → ingress-nginx → the
# api / webserver service per the chart's Ingress rules. Single forward
# because nginx multiplexes (the production webserver image doesn't proxy
# /api/* itself). Host-side port bumped off 80 to avoid sudo / collisions.

local_resource(
    'pf-ingress',
    serve_cmd='kubectl --context k3d-onyx-local -n onyx port-forward svc/onyx-nginx-controller 13000:80',
    resource_deps=['onyx'],
)
