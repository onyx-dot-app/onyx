# Sandbox image + spinup notes

Living context for future agents touching the Craft sandbox image, spinup
path, or snapshot daemon. Captures the *why* behind decisions whose
motivation isn't obvious from the diff.

Related files:

- `backend/onyx/server/features/build/sandbox/image/Dockerfile`
- `backend/onyx/server/features/build/sandbox/image/initial-requirements.in`
- `backend/onyx/server/features/build/sandbox/image/initial-requirements.txt`
- `backend/onyx/server/features/build/sandbox/image/sandbox_daemon/snapshot.py`
- `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py`
- `backend/onyx/server/features/build/sandbox/kubernetes/scripts/bench-sandbox-spinup.sh`
- `deployment/helm/charts/onyx/templates/sandbox-namespace.yaml`

## SHA-pinned base + helper images

`python:3.13-slim`, `node:24-trixie-slim`, and `oven/bun:1.3.14` are
SHA-pinned in the Dockerfile (`@sha256:...`). Same precedent as
`backend/Dockerfile` and `web/Dockerfile`. Bump via:

```
docker pull <image>:<tag>
docker inspect <image>:<tag> --format '{{index .RepoDigests 0}}'
```

and update both the tag and the digest in the same commit so they don't
drift.

## No storage client in the sandbox image

The sandbox image used to include a pod-side storage client for snapshot
upload/download. That is no longer part of the architecture: the sidecar tars
and untars local filesystem state, and the API server persists snapshot bytes
through the normal Onyx FileStore.

Do not add AWS CLI, `s5cmd`, or provider-specific object-store CLIs back to the
sandbox image for snapshots. If a future feature needs durable storage, route it
through the API server and FileStore unless there is a strong reason to expand
the sandbox's credential surface.

## Multi-stage COPY for bun

We used to `curl -fsSL https://bun.sh/install | bash` at image-build
time. That hit the public internet on every uncached layer rebuild and
made builds vulnerable to bun.sh availability. The bun binary is now
copied out of `oven/bun:<version>` (same pattern as `web/Dockerfile:15-16`).

`BUN_VERSION` and the COPY tag must be kept in sync.

## opencode is still curl-piped (with `--version` pin)

opencode (now hosted at `anomalyco/opencode` after the sst → anomaly
acquisition) does not publish an official Docker image. The image
installs opencode via its own install script with the `--version` flag
so the build is at least reproducible:

```dockerfile
ARG OPENCODE_VERSION=1.18.19
RUN curl -fsSL https://opencode.ai/install \
    | bash -s -- --version "${OPENCODE_VERSION}" --no-modify-path
```

Future work: download the release tarball directly from
`github.com/anomalyco/opencode/releases/download/v$VERSION/...` and
verify by SHA256, so the build doesn't depend on opencode.ai serving
the install script.

## `initial-requirements.txt` philosophy

The Python venv is ~430 MB on disk and defines the libraries every
sandbox session starts with. Anything else, agents can `pip install`
on demand from inside the sandbox.

We keep only:

- **Foundational / "expected by most code"**: `numpy`, `pandas`,
  `matplotlib` (+ `matplotlib-inline`), `Pillow`.
- **Office formats**: `openpyxl`, `python-pptx`, `pdfplumber`, `lxml`,
  `defusedxml`.
- **Sandbox daemon dependencies**: `fastapi`, `uvicorn[standard]`,
  `pydantic`, `cryptography`.
- **Skill-specific runtime**: `google-genai` (image-generation skill),
  `onyx-cli`.

We deliberately do **not** pre-install the heavy ML/CV stack
(`opencv-python`, `scikit-learn`, `scikit-image`, `scipy`, `xgboost`,
`onnxruntime`, `markitdown`, `seaborn`, `matplotlib-venn`). Pulling
those in adds ~450 MB to the image and is only useful for a small
fraction of sessions — the agent can `pip install` what it needs at
the start of a session script if it actually uses them. If a skill we
ship out of the box ever starts importing one of these, add it back
here.

## `ENABLE_SKILLS` build arg

The pptx skill needs LibreOffice + poppler-utils + extra fonts +
pptxgenjs in the image (~700 MB). Skills themselves are pushed by the
API server at session setup, but their **runtime tools** must be in
the image already (the in-pod `soffice` / `pdftoppm` / `pptxgenjs` calls
from `onyx/skills/builtin/pptx/scripts/`).

- Prod / default: `ENABLE_SKILLS=true` — full image, all skills work.
- Dev kind clusters / CI: `ENABLE_SKILLS=false` — ~700 MB smaller, but
  any skill that shells out to `soffice` / `pdftoppm` / `pptxgenjs` will
  fail. The full-cluster Craft K8s integration lane doesn't exercise
  those runtime tools, so `pr-craft-k8s-tests.yml` builds with
  `ENABLE_SKILLS=false`.

To toggle in dev:

```
docker build --build-arg ENABLE_SKILLS=false \
    -t onyxdotapp/sandbox:dev-noskills \
    backend/onyx/server/features/build/sandbox/image
```

If you add a new skill that depends on a heavy system package (Chrome,
ffmpeg, etc.), add it under the `if [ "$ENABLE_SKILLS" = "true" ]` block
so the prod image still has it but dev/CI images can opt out.

## Cold pulls vs. image warming — decision and roadmap

**Current state: we pre-pull the sandbox image on both backends.**
Kubernetes uses a DaemonSet over the sandbox node pool
(`sandboxImagePrepull` in `values.yaml`, template
`sandbox-image-prepuller.yaml`); Docker declares the image in
`docker-compose.craft.yml` so `docker compose pull` fetches it — see
"Docker" below. Both on by default when `ENABLE_CRAFT` is set.

This section previously recorded the opposite decision — that we accept
cold pulls — on an estimate of ~3–6 s per pull from AZ-local bandwidth.
Measurement contradicted it. Evicting `onyxdotapp/sandbox:latest` from a
kind node and timing `crictl pull` (1070 MB compressed, 34 MB/s
effective) gave:

| | pull | create → Ready |
|---|---|---|
| cold pull | **31.4 s** | 32.6 s |
| blobs cached, image record dropped | 1.4 s | 3.3 s |

~5x the old estimate, which had assumed a same-region registry. The
realistic case is a self-hosted install pulling Docker Hub over its own
link.

It also isn't only latency. That cost lands inside the 90 s budget
`_wait_for_pod_ip` shares with the opencode-history restore, so on a
slower link the download alone blows the deadline and provisioning
*fails* with `Timeout waiting for sandbox pod ... to be assigned an IP`
— or succeeds and starves the restore. Nodes lack the image whenever
they're new, whenever no sandbox has landed on them yet, after a tag
bump, or after kubelet image GC reclaims it.

### Why the DaemonSet is shaped the way it is

Each of these fails *silently* if changed — the DaemonSet reports Ready
while sandboxes go on cold-pulling, and the only symptom is the slow
provisioning the feature was meant to remove. There are render-time
tests for all of them in
`backend/tests/external_dependency_unit/craft_helm/test_sandbox_image_prepuller.py`.

They live in the `craft_helm` shard, next to `test_pod_spec.py`, because
that is the lane which installs `helm` and runs `helm dependency build`
(see `pr-external-dependency-unit-tests.yml`, triggered on
`deployment/helm/**`). Chart-render tests belong there and nowhere else:
under `backend/tests/unit` they have no helm, and a directory named
`build` is additionally skipped by pytest's default `norecursedirs`, so
they would never even be collected.

- **A DaemonSet, not a one-shot pre-pull Job.** The kubelet only exempts
  images referenced by a *running* pod from image GC. A Job pulls and
  exits, leaving the layers evictable (default
  `imageGCHighThresholdPercent` 85%) with nothing to signal it. A
  long-lived pod pins them, and a DaemonSet also covers nodes that join
  after install.
- **The image ref *and pull policy* are shared with the sandbox
  PodTemplate**, via the `onyx.sandboxImage` /
  `onyx.sandboxImagePullPolicy` helpers. A drifted tag pins layers nobody
  uses while every sandbox still cold-pulls. The pull policy is part of
  that, not a detail: pinning the prepuller to `IfNotPresent` while the
  sandbox pods run `Always` reproduces the same drift one level down —
  on a mutable tag the sandboxes fetch the new digest and the prepuller
  keeps the old one resident and GC-exempt.
- **Scheduling mirrors `sandboxPod`** (nodeSelector + tolerations), or
  it warms the wrong pool.
- **Pull credentials come from the sandbox ServiceAccount only**, the
  same single route the sandbox PodTemplate uses. See "Private
  registries" below for why the chart-wide `.Values.imagePullSecrets`
  is not an option here.
- **No PriorityClass, and no cluster-scoped objects at all.** See
  "Why there is no PriorityClass" below before adding one back.
  `sandboxImagePrepull.priorityClassName` names an *existing* class for
  operators who want the prepuller preemptible; the chart creates none.
- **A portable idle loop**, not `sleep infinity` — a GNU coreutils
  extension that dies on busybox/alpine. A CrashLooping prepuller unpins
  the image.
- **Labelled `component: sandbox-image-prepuller`**, not
  `component: sandbox`, which is the selector for the sandbox
  NetworkPolicies — *and* given its own deny-all NetworkPolicy as a
  result. Staying out of that selector also leaves it out of the sandbox
  default-deny, which would otherwise make the prepuller the one
  unrestricted pod in the sandbox namespace, running the sandbox image.
  It needs no network: the pull is the kubelet's, not the pod's.

Pin `global.version` (or `configMap.SANDBOX_CONTAINER_IMAGE`) to an
immutable tag when running the prepuller. Holding a mutable tag like
`latest` keeps whichever digest a node pulled first resident and
GC-exempt: the DaemonSet spec doesn't change when the tag is repointed,
so nothing restarts the pod to re-resolve it, and the image GC pass that
used to let the node drift back to a fresh `latest` no longer runs on
it. Under `pullPolicy: Always` the restart does re-resolve, which is why
the policy is shared rather than hardcoded.

### Why there is no PriorityClass

The prepuller originally created one, at value -10, so a pending sandbox
pod could preempt it rather than fail to schedule behind a do-nothing
pod. **It broke deploys and has been removed. Don't add it back without
reading this.**

A follow-up changed the default to -11 — on the argument that -10 is
exactly cluster-autoscaler's default `--expendable-pods-priority-cutoff`
and the cutoff is exclusive — while keeping the object's name. Every
cluster already holding the class then failed to upgrade:

```
Error: UPGRADE FAILED: cannot patch "onyx-onyx-sandbox-image-prepuller"
with kind PriorityClass: ... value: Forbidden: may not be changed in an
update.
```

Two Kubernetes facts collide there. `PriorityClass.value` is immutable —
priority is resolved once at pod admission and copied into
`pod.spec.priority`, so the class's value must not drift afterwards. And
`helm upgrade` *patches* existing objects rather than replacing them. So
that field could never be changed in place, by anyone, ever. Worse, Helm
aborts the entire release on one rejected patch, so a latency
optimisation took down the nightly deploy of the whole application.

It was removed rather than worked around, because it was not earning its
keep:

- **Preemption freed nothing useful.** The prepuller requests 10m CPU /
  32Mi. Evicting it cannot unblock a sandbox pod that wants 1000m / 2Gi.
- **The autoscaler argument barely applies to a DaemonSet.**
  cluster-autoscaler does not scale up *because* a DaemonSet pod is
  pending; DS pods only factor into simulating a new node's capacity.
- **It did not affect disk-pressure eviction**, the one form of eviction
  the prepuller actually invites: kubelet ranks "exceeds
  ephemeral-storage request" ahead of priority.
- **Cluster-scoped objects are expensive in a Helm chart.** Two releases
  of the same name in different namespaces render the same object, so the
  name needed the namespace hashed into it, which is where the
  trunc+sha32 logic and several tests came from.

If you want the prepuller preemptible, point
`sandboxImagePrepull.priorityClassName` at a low-priority class you
manage yourself. A render test
(`test_prepuller_ships_no_cluster_scoped_objects`) fails if this template
starts emitting cluster-scoped objects again.

Note also that **no CI lane would have caught this**: `ct install` only
does a fresh install into an empty kind cluster, never an upgrade from
the previously released chart, so the patch path where immutable-field
violations live is untested. `ct install --upgrade` would cover it.

### Docker

Same problem, materially easier shape. The Docker backend pulls lazily in
`DockerSandboxManager._ensure_sandbox_image()`, called from
`provision()` — so on a host without the image, whoever asks for the
first sandbox pays the ~1 GB download inside their own request.

Two differences from Kubernetes drive a different fix:

- **One image store, not one per node.** A compose deployment is a single
  Docker daemon, so a single pull serves `api_server`, `background`, and
  every sandbox container. There is no per-node fan-out to arrange, and
  no `maxUnavailable` to tune.
- **Docker never garbage-collects images.** kubelet reclaims them at
  `imageGCHighThresholdPercent`, which is why the Kubernetes fix needs a
  *running* pod to pin the layers. Docker only removes images on an
  explicit `docker image prune`. Pinning is therefore a bonus here, not
  the point.

So the fix is a `sandbox-image-prepull` entry in
`docker-compose.craft.yml` carrying `deploy.replicas: 0`. The sandbox
image is not otherwise a compose service — `api_server` creates sandbox
containers from it directly — so `docker compose pull` has nothing to
tell it about. Declaring it puts the image on the normal pull/upgrade
lifecycle; `replicas: 0` means no container is ever created.

That combination is load-bearing and was verified rather than assumed:

| shape | `compose pull` fetches it | `up --wait` |
|---|---|---|
| `profiles: [...]` | **no** — skipped | n/a |
| one-shot that exits 0 | yes | **exits 1** |
| long-lived idler | yes | ok, but a pointless container forever |
| `deploy.replicas: 0` | yes | ok, no container at all |

So profiles can't be used (a plain `pull` skips them, which defeats the
point for anyone not using the installer), and a one-shot breaks the
`up --wait` that `install.sh` passes by default.

**One mechanism, and it covers every path.** `install.sh --include-craft`
already runs `docker compose pull` with the craft overlay layered in, so
the installer needs no special case. Anyone who brings the stack up by
hand — a supported path, see `deployment/docker_compose/README.md` option
2 — gets it from the same plain `docker compose pull`, with nothing extra
to remember.

**One fallback.** If the image is missing later (pruned, or an operator
who never pulls), `provision()` pulls it on demand as it always has. The
cost lands on one request and the error surfaces against the request that
caused it.

Earlier revisions added a long-lived compose service to hold the image
*and* a background warm at api_server startup. Both were removed. They
were mutually redundant — each was justified by gaps the other covered —
and neither survives the question "if the other exists, why do I?". The
long-lived service also left a container idling forever for no reason
beyond satisfying `docker compose up --wait` — which `replicas: 0` sidesteps
entirely, since there is nothing for the wait to observe.

Do not warm at api_server startup. Blocking there would put all of Onyx's
readiness behind the registry, and not just on first install: `:latest`
is the default and is in `_MUTABLE_SANDBOX_IMAGE_TAGS`, for which
`_ensure_sandbox_image` skips the local-presence check and always pulls.
Every restart would contact the registry. Making it non-blocking instead
just converts a broken deployment into a slow one that fails later, at a
user's first sandbox.

The `background` worker also provisions (waking `SLEEPING` sandboxes via
`scheduled_tasks/executor.py`) and needs nothing of its own: it shares
the host's image store, so whichever pull happened first covers it.

### Private registries

Relevant only if you mirror the sandbox image into your own registry;
the default `onyxdotapp/sandbox` on Docker Hub is public and needs no
credentials.

**Attach the pull secret to the sandbox ServiceAccount. Chart-level
`imagePullSecrets` will not work for sandbox workloads.** Both the
prepuller and the sandbox pods run in `SANDBOX_NAMESPACE`
(`onyx-sandboxes` by default), while `.Values.imagePullSecrets` names
secrets in the *release* namespace — and a kubelet resolves an
imagePullSecret in the pod's own namespace. Listing those names on a
sandbox-namespace pod points at secrets that do not exist there.

Both the namespace and the account name are configurable, and both pods
follow whatever the configMap sets — patching the default `sandbox`
account on a deployment that overrode `SANDBOX_SERVICE_ACCOUNT_NAME`
leaves the real account uncredentialed and every pull failing:

```bash
# Chart defaults. Override to match configMap.SANDBOX_NAMESPACE and
# configMap.SANDBOX_SERVICE_ACCOUNT_NAME if your deployment sets them.
SANDBOX_NS=onyx-sandboxes
SANDBOX_SA=sandbox

kubectl -n "$SANDBOX_NS" create secret docker-registry regcred \
  --docker-server=... --docker-username=... --docker-password=...
kubectl -n "$SANDBOX_NS" patch serviceaccount "$SANDBOX_SA" \
  -p '{"imagePullSecrets":[{"name":"regcred"}]}'

# Confirm it took, on the account the pods actually use.
kubectl -n "$SANDBOX_NS" get sa "$SANDBOX_SA" -o jsonpath='{.imagePullSecrets}'
```

This is also why the prepuller renders no `imagePullSecrets` block. An
earlier revision gave the prepuller the chart-wide secrets and left the
PodTemplate on the SA alone, which is the worst arrangement available:
on a cluster where the release-namespace secret name happens to also
exist in the sandbox namespace, the prepuller goes Ready and warms an
image the sandbox pods still cannot pull. One route for both, and a
render test asserts neither pod spec carries the block.

### What it costs, and when to turn it off

The sandbox image is ~3.3 GB extracted and becomes **unreclaimable** on
every sandbox node, on the same disk as the sandbox workspaces
(`workspace` emptyDir, 50Gi sizeLimit). Disk pressure that image GC used
to absorb now resolves by evicting pods instead. Set
`sandboxImagePrepull.enabled: false` when either applies:

- Single-node / fixed tiny deployments: the image stays resident anyway
  and nothing evicts it, so the DaemonSet is pure overhead.
- Nodes without headroom for 3.3 GB on top of the workspace
  ephemeral-storage limits.

### What it does not fix

Autoscale-up. Node boot (60–120 s) dominates the pull there, and the
DaemonSet lands on the new node simultaneously with the sandbox that
triggered the scale-out, so that pod may still cold-start.

### Next step, when autoscale-up cold starts start hurting

**Bake the sandbox image into the node image** (AMI on AWS / custom
node image on GCP/Azure). The autoscaler boots nodes that already have
the layers on disk — zero runtime workload, zero cold pulls, works
even for the very first pod on a brand-new node. This is the piece the
prepuller can't cover; lazy pull (GKE Image Streaming, SOCI) is the
other option.

Sketch:

1. Start from the cloud's standard managed node image (e.g.
   EKS-optimized AL2023).
2. In a Packer / EC2 Image Builder / `gcloud compute images create`
   pipeline, boot the base, run `crictl pull <sandbox-image>:<tag>`,
   and snapshot the disk.
3. Point the sandbox node group at the new image ID.
4. Re-bake whenever the app-aligned sandbox image tag changes (or fall back to
   pulling for that version).

Tradeoff: adds a build pipeline keyed to sandbox image versions, and
re-baking takes ~10–20 min per cloud.

### Trigger to revisit

Pick up node-image baking if either of:
- The sandbox node pool starts churning frequently (autoscale events
  measured in minutes, not hours), so scale-out cold starts — which the
  prepuller does not fix — become common rather than incidental.
- Product surface shows cold-pull spinups still dominating a measurable
  fraction of "open sandbox" latency p95 with the prepuller deployed.

## Recorded benchmark — 2026-05-21

Captured on a local `kind-onyx-dev` cluster, `REPS=3` cold + warm runs
per image via `backend/onyx/server/features/build/sandbox/kubernetes/scripts/bench-sandbox-spinup.sh`.
Cold = `crictl rmi` + `kind load` + pod create + `kubectl wait Ready`;
warm = pod create + Ready with image already on the node.

| Image | Manifest | Uncompressed | Cold p50 | Warm p50 |
|---|---|---|---|---|
| `before` (git HEAD)                   | 915 MB         | 4.25 GB       | 30.5 s | 923 ms |
| `after-trimmed` (`ENABLE_SKILLS=true`, prod)  | 717 MB (−22%)  | 3.33 GB (−22%) | 28.8 s (−6%)  | 918 ms |
| `after-trimmed` (`ENABLE_SKILLS=false`, CI)   | **581 MB (−37%)** | **2.79 GB (−34%)** | **22.8 s (−25%)** | 923 ms |

`after-trimmed` is the cumulative result of: dropping the AWS CLI layer,
multi-stage COPYs for bun, SHA-pinning the base, gating
LibreOffice/poppler/fonts/pptxgenjs behind `ENABLE_SKILLS`, and trimming
heavy ML libs (`opencv-python`, `scikit-learn`, `scikit-image`, `scipy`,
`xgboost-cpu`, `markitdown` (→ `magika`+`onnxruntime`), `seaborn`,
`matplotlib-venn`) from `initial-requirements.txt`. Agents can `pip
install` any of those on demand if a skill needs them.

Caveats:

- **Cold p50 is dominated by `kind load`'s tar-shuffle overhead**, not by
  actual container start. Treat the *delta* between images as meaningful,
  the *absolute* cold number as transport overhead.
- This row originally extrapolated the prod registry pull at 3–6 s from
  150–300 MB/s AZ-local bandwidth. **That was wrong** — see the measured
  31.4 s in "Cold pulls vs. image warming" above. The estimate assumed a
  same-region registry; the realistic case is a self-hosted install
  pulling Docker Hub over its own link (34 MB/s effective, measured).
- Warm spinup is essentially image-size-insensitive (~900 ms regardless)
  because layers are already extracted in the kubelet. Once a node has
  pulled the image once, every subsequent pod sees warm-start latency.

## Reproducing the benchmark

The harness lives at:

```
backend/onyx/server/features/build/sandbox/kubernetes/scripts/bench-sandbox-spinup.sh
```

It accepts one or more locally-built sandbox image tags and, per image,
runs `REPS` cold + `REPS` warm iterations against a kind cluster. Cold
removes the image from the kind node's containerd, then `kind load`s it
back and times pod-create→Ready. Warm skips the rmi/load and only times
pod-create→Ready. Image sizes are read from `docker image inspect`.

### Prereqs

- Local kind cluster on the `kind-onyx-dev` context (see
  `docs/craft/dev/local-kubernetes.md`). The script refuses to run against
  any other kubectl context as a safety guard.
- Tools on `$PATH`: `docker`, `kind`, `kubectl`, `python3`.

### Typical workflow

```bash
# 1. Build current dev image + a candidate you want to compare
make craft-sandbox-image            # → onyxdotapp/sandbox:dev
docker build --build-arg ENABLE_SKILLS=false \
    -t onyxdotapp/sandbox:candidate \
    backend/onyx/server/features/build/sandbox/image

# 2. Benchmark both (3 reps each scenario by default)
REPS=3 backend/onyx/server/features/build/sandbox/kubernetes/scripts/bench-sandbox-spinup.sh \
    onyxdotapp/sandbox:dev \
    onyxdotapp/sandbox:candidate
```

Output is a per-image table of image size + min/median/max latency for
each scenario, ready to paste into a PR description.

### Knobs (env vars)

| Var | Default | Notes |
|---|---|---|
| `REPS` | `3` | Iterations per scenario per image. |
| `NS` | `onyx-sandboxes` | Namespace bench pods live in (auto-created). |
| `KIND_CLUSTER` | `onyx-dev` | Used for `kind load --name` + context check. |
| `KIND_NODE` | `<cluster>-control-plane` | Node where `crictl rmi` runs. |
| `WAIT_TIMEOUT` | `300s` | `kubectl wait` timeout per pod. |

### When to run

Any time you change the Dockerfile, `initial-requirements.txt`, or
anything else that affects the image bytes or container start. Paste
the resulting table into the PR description so reviewers can see the
delta without rebuilding locally.

### What it doesn't measure

The bench creates a bare pod running `sleep` — it does **not** exercise
the full `KubernetesSandboxManager.provision` + `setup_session_workspace`
path (no snapshot streaming, no init container, no `bun install`, no
session config). For end-to-end session-spinup numbers, run a real
session against a live cluster and time `provision()` →
`setup_session_workspace()` via the manager directly.

Also: `kind load` is much slower than a real registry pull (it does
docker save → tar → crictl load). The *delta* between two images is
meaningful, but the absolute "cold" number is mostly kind-load
overhead, not realistic prod cold-pull time. See the caveats under
"Recorded benchmark" above.

## Snapshot daemon path quick reference

`sandbox_daemon/snapshot.py` runs inside the sidecar process and only touches
the shared pod filesystem. It is responsible for session-level snapshots under
`/workspace/sessions/<session_id>/{outputs,attachments}`. Sandbox-global
opencode history lives outside the session tree and is snapshotted separately.
Storage is handled by the API server through FileStore.

`node_modules` and `.next` are deliberately excluded from snapshots
because (a) they're huge, (b) `restore_snapshot` rebuilds them via the
hardlink-backed `bun install` against the pre-warmed Bun cache.
