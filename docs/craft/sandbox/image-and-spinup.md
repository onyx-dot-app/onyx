# Sandbox image + spinup notes

Living context for future agents touching the Craft sandbox image, spinup
path, or snapshot daemon. Captures the *why* behind decisions whose
motivation isn't obvious from the diff.

Related files:

- `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile`
- `backend/onyx/server/features/build/sandbox/kubernetes/docker/initial-requirements.txt`
- `backend/onyx/server/features/build/sandbox/kubernetes/docker/sandbox_daemon/snapshot.py`
- `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py`
- `backend/onyx/server/features/build/sandbox/kubernetes/scripts/bench-sandbox-spinup.sh`
- `deployment/helm/charts/onyx/templates/sandbox-namespace.yaml`

## SHA-pinned base + sidecar images

`node:20-slim`, `oven/bun:1.3.14`, and `peakcom/s5cmd:v2.3.0` are all
SHA-pinned in the Dockerfile (`@sha256:...`). Same precedent as
`backend/Dockerfile` and `web/Dockerfile`. Bump via:

```
docker pull <image>:<tag>
docker inspect <image>:<tag> --format '{{index .RepoDigests 0}}'
```

and update both the tag and the digest in the same commit so they don't
drift.

## s5cmd replaces the AWS CLI v2 layer

The sandbox image used to `COPY --from=amazon/aws-cli:latest` (~250 MB of
Python-bundled CLI v2) purely so `sandbox_daemon/snapshot.py` could shell
out to `aws s3 cp - s3://...` for streaming snapshot upload/download.

The file-sync sidecar already moved off the AWS CLI in PR #8170
("chad s5cmd > chud aws cli (mem overhead + speed)") for the same memory
+ speed reasons that apply here. The snapshot daemon now does the same:

| Operation | Old                         | New                |
|-----------|-----------------------------|--------------------|
| Upload    | `... \| aws s3 cp - s3://x` | `... \| s5cmd pipe s3://x` |
| Download  | `aws s3 cp s3://x - \| ...` | `s5cmd cat s3://x \| ...` |

Same streaming semantics, no memory buffering. The static binary is
copied out of the upstream `peakcom/s5cmd` image via multi-stage COPY.

If you reintroduce an AWS CLI dependency for some other reason — please
don't. `s5cmd` and AWS SDKs in app code cover everything we need.

## Multi-stage COPY for bun and s5cmd

We used to `curl -fsSL https://bun.sh/install | bash` at image-build
time. That hit the public internet on every uncached layer rebuild and
made builds vulnerable to bun.sh availability. The bun binary is now
copied out of `oven/bun:<version>` (same pattern as `web/Dockerfile:15-16`).

s5cmd is copied the same way from `peakcom/s5cmd:<version>`.

`BUN_VERSION` and the COPY tag must be kept in sync.

## opencode is still curl-piped (with `--version` pin)

opencode (now hosted at `anomalyco/opencode` after the sst → anomaly
acquisition) does not publish an official Docker image. The image
installs opencode via its own install script with the `--version` flag
so the build is at least reproducible:

```dockerfile
ARG OPENCODE_VERSION=1.15.7
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
from `docker/skills/pptx/scripts/`).

- Prod / default: `ENABLE_SKILLS=true` — full image, all skills work.
- Dev kind clusters / CI: `ENABLE_SKILLS=false` — ~700 MB smaller, but
  any skill that shells out to `soffice` / `pdftoppm` / `pptxgenjs` will
  fail. The current K8s test suite doesn't exercise those, so
  `pr-craft-k8s-tests.yml` builds with `ENABLE_SKILLS=false`.

To toggle in dev:

```
docker build --build-arg ENABLE_SKILLS=false \
    -t onyxdotapp/sandbox:dev-noskills \
    backend/onyx/server/features/build/sandbox/kubernetes/docker
```

If you add a new skill that depends on a heavy system package (Chrome,
ffmpeg, etc.), add it under the `if [ "$ENABLE_SKILLS" = "true" ]` block
so the prod image still has it but dev/CI images can opt out.

## Cold pulls vs. image warming — decision and roadmap

**Current state: we accept cold image pulls on freshly-scheduled nodes.**

The first sandbox pod scheduled to a new node pays the registry-pull cost
(~3–6 s for the trimmed image at typical AZ-local bandwidth; see the
benchmark below). Every subsequent pod on that node hits warm-start
(~900 ms) until the kubelet GCs the image.

### What we considered and rejected

A DaemonSet (`sandbox-image-warmer`) that runs the sandbox image with
`sleep infinity` on every node in the `onyx.app/workload=sandbox` pool.
The kubelet won't GC images that are referenced by a running pod, so
this pins the layers on disk indefinitely and every real sandbox pod
sees warm-start latency.

Rejected because the cost (an always-on pod per node, more Helm
template surface, another workload to monitor) outweighs the win for
our current scale and image size. The warmer also doesn't help the
*first* pod on a freshly-autoscaled node — the warmer pod itself still
has to pull before it can pin anything.

### Optimal solution if cold pulls ever become painful

**Bake the sandbox image into the node image** (AMI on AWS / custom
node image on GCP/Azure). The autoscaler boots nodes that already have
the layers on disk — zero runtime workload, zero cold pulls, works
even for the very first pod on a brand-new node.

Sketch:

1. Start from the cloud's standard managed node image (e.g.
   EKS-optimized AL2023).
2. In a Packer / EC2 Image Builder / `gcloud compute images create`
   pipeline, boot the base, run `crictl pull <sandbox-image>:<tag>`,
   and snapshot the disk.
3. Point the sandbox node group at the new image ID.
4. Re-bake whenever `SANDBOX_CONTAINER_IMAGE` bumps (or fall back to
   pulling for that version).

Tradeoff: adds a build pipeline keyed to sandbox image versions, and
re-baking takes ~10–20 min per cloud. Worth it once cold-pull latency
is measurably hurting users, not before.

### Trigger to revisit

Bring this section back up if any of:
- The sandbox image grows materially past ~1 GB compressed (cold pulls
  start climbing past ~10 s).
- The sandbox node pool starts churning frequently (autoscale events
  measured in minutes, not hours).
- Product surface shows cold-pull spinups dominating a measurable
  fraction of "open sandbox" latency p95.

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
multi-stage COPYs for bun + s5cmd, SHA-pinning the base, gating
LibreOffice/poppler/fonts/pptxgenjs behind `ENABLE_SKILLS`, and trimming
heavy ML libs (`opencv-python`, `scikit-learn`, `scikit-image`, `scipy`,
`xgboost-cpu`, `markitdown` (→ `magika`+`onnxruntime`), `seaborn`,
`matplotlib-venn`) from `initial-requirements.txt`. Agents can `pip
install` any of those on demand if a skill needs them.

Caveats:

- **Cold p50 is dominated by `kind load`'s tar-shuffle overhead**, not by
  actual container start. In prod the equivalent op is a registry pull,
  which at typical AZ-local bandwidth (150–300 MB/s) translates to
  roughly 3–6 s for a 700 MB manifest, less for the noskills variant.
  Treat the *delta* between images as meaningful, the *absolute* cold
  number as transport overhead.
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
  `docs/dev/local-kubernetes.md`). The script refuses to run against
  any other kubectl context as a safety guard.
- Tools on `$PATH`: `docker`, `kind`, `kubectl`, `python3`.

### Typical workflow

```bash
# 1. Build current dev image + a candidate you want to compare
make craft-sandbox-image            # → onyxdotapp/sandbox:dev
docker build --build-arg ENABLE_SKILLS=false \
    -t onyxdotapp/sandbox:candidate \
    backend/onyx/server/features/build/sandbox/kubernetes/docker

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
path (no sidecar S3 sync, no init container, no `bun install`, no
session config). For end-to-end session-spinup numbers, run a real
session against a live cluster and time `provision()` →
`setup_session_workspace()` via the manager directly.

Also: `kind load` is much slower than a real registry pull (it does
docker save → tar → crictl load). The *delta* between two images is
meaningful, but the absolute "cold" number is mostly kind-load
overhead, not realistic prod cold-pull time. See the caveats under
"Recorded benchmark" above.

## Snapshot daemon path quick reference

`sandbox_daemon/snapshot.py` runs **inside** the sandbox container (not
the file-sync sidecar). The sidecar is responsible for syncing the
user's knowledge files from S3 (`/workspace/files/`); the daemon is
responsible for session-level snapshots
(`/workspace/sessions/<session_id>/{outputs,attachments,.opencode-data}`).
Both shell out to `s5cmd`. Don't conflate them.

`node_modules` and `.next` are deliberately excluded from snapshots
because (a) they're huge, (b) `restore_snapshot` rebuilds them via the
hardlink-backed `bun install` against the pre-warmed Bun cache (see
`docs/craft/features/bun-node-modules-dedup.md`).
