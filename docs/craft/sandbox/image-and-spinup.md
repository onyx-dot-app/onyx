# Sandbox image and spinup notes

This is the active reference for the Craft sandbox image and image-warming
path. The runtime contract is in [Firecracker infrastructure](../infra/firecracker.md).

Craft has a shared Firecracker runtime interface. The Kubernetes launcher uses
`kata-fc`; the Docker Firecracker launcher remains under implementation.
The original Docker/runc sandbox, HTTP sidecar, push daemon, and daemon package
are removed.

Related files:

- `backend/onyx/server/features/build/sandbox/image/Dockerfile`
- `backend/onyx/server/features/build/sandbox/image/README.md`
- `backend/onyx/server/features/build/sandbox/image/entrypoint.sh`
- `backend/onyx/server/features/build/sandbox/image/firewall-init.sh`
- `backend/onyx/server/features/build/sandbox/image/guest/`
- `backend/onyx/server/features/build/sandbox/manager.py`
- `backend/onyx/server/features/build/sandbox/runtime.py`
- `backend/onyx/server/features/build/sandbox/kubernetes_runtime.py`
- `backend/onyx/server/features/build/sandbox/exec.py`
- `deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml`
- `deployment/helm/charts/onyx/templates/sandbox-image-prepuller.yaml`

## Runtime shape

`SandboxManager` is the only manager. It calls the `SandboxRuntime` protocol for
lifecycle, exec, endpoints, credentials, and logs. `KubernetesRuntime` owns
Kubernetes objects and its `ExecClient`.
The exec target is the immutable guest helper:

```text
/opt/onyx-guest/venv/bin/python -I -m onyx_guest
```

The guest helper package is `image/guest/`, installed as `onyx_guest` in the
sandbox image. It handles filesystem operations, managed content pushes,
session snapshots, and OpenCode history. It does not expose an HTTP API.
Bootstrap and status avoid Pydantic and archive imports. User operation imports
follow privilege drop, so commands do not load them twice.

The pod has one main `sandbox` container and one `sandbox-firewall` init
container. The init container applies proxy-only egress with `NET_ADMIN`. The
main container has no network administration capability. The sidecar release is
superseded; use [Firecracker infrastructure](../infra/firecracker.md) for
cutover rules.

## Image build contracts

The sandbox image is the only Craft-specific image. Standard Onyx backend and
web images run Craft when `ENABLE_CRAFT=true`.

The release workflow publishes `onyxdotapp/sandbox:<app tag>` for each app
release. Helm defaults the sandbox image to that app-aligned tag through
`global.version`. `configMap.SANDBOX_CONTAINER_IMAGE` can override it for local
or CI images.

Keep these Dockerfile contracts intact:

- `python:3.13-slim`, `node:24-trixie-slim`, and `oven/bun:1.3.14` are
  digest-pinned. Update the tag and digest together.
- Bun comes from the `oven/bun` image. Do not return to piping the installer
  from `bun.sh` during image builds.
- OpenCode is still installed from the OpenCode installer with an explicit
  version. A future hardening pass can download the release artifact directly
  and verify its SHA256.
- The image must not include provider-specific storage CLIs for snapshots.
  The guest helper creates archives locally. The API server stores them through
  the normal Onyx FileStore.

## Prewarmed dependencies

OpenCode installs `@opencode-ai/plugin` into each configuration directory.
Cold installs were measured in minutes and exceeded session startup budgets.

The image pre-installs the matching plugin SDK under
`/workspace/templates/opencode`. Session setup seeds each `.opencode`
directory from that template. The copy is per session, so one session cannot
edit another session's dependencies.

The image also prewarms Bun's cache. Snapshots exclude `node_modules` and
`.next`; restore rebuilds those dependencies from the warmed cache.

## Python packages

`initial-requirements.txt` defines the libraries each sandbox starts with.
Keep it small. Agents can install extra packages inside their session when a
task needs them.

Keep these groups in the base image:

- foundational packages used by common notebooks and scripts, such as `numpy`,
  `pandas`, `matplotlib`, and `Pillow`
- office and document packages used by built-in skills
- guest helper dependencies, including `pydantic` and `cryptography`
- skill-specific runtime packages that built-in skills import directly

Do not add the heavy ML/CV stack unless a built-in skill imports it at runtime.
That includes `opencv-python`, `scikit-learn`, `scikit-image`, `scipy`,
`xgboost`, `onnxruntime`, `markitdown`, `seaborn`, and `matplotlib-venn`.

## Skill and browser build args

`ENABLE_SKILLS=false` omits the office tooling and fonts used by document
skills. `ENABLE_BROWSER=false` omits Chromium and the browser CLI. Neither
switch changes the guest security boundary.

Production images should keep skills and browser support enabled unless the
deployment also disables the corresponding product surface. If the image omits
the browser, set backend `ENABLE_BROWSER=false` too so the browser skill is not
advertised without its runtime.

## Image warming

Kubernetes pre-pulls the sandbox image with
`sandbox-image-prepuller.yaml`. The prepuller is a DaemonSet over the sandbox
node pool. It uses the same image reference, pull policy, RuntimeClass,
ServiceAccount, node selector, and tolerations as sandbox pods.

These details are load-bearing:

- Use a DaemonSet, not a one-shot Job. Kubelet image garbage collection only
  exempts images referenced by running pods.
- Share the image reference and pull policy with the sandbox PodTemplate.
  A drifted prepuller can look healthy while sandboxes still cold-pull.
- Keep the prepuller on the sandbox node pool.
- Pull credentials must come from the sandbox ServiceAccount. Chart-wide
  `imagePullSecrets` live in the release namespace and do not resolve for pods
  in the sandbox namespace.
- Do not add chart-owned PriorityClass objects. `priorityClassName` may point
  at an existing class.
- Keep the prepuller out of the `component: sandbox` label. That label selects
  sandbox NetworkPolicies.
- Keep the prepuller NetworkPolicy deny-all. The kubelet pulls the image; the
  pod itself needs no network.

Pin `global.version` or `configMap.SANDBOX_CONTAINER_IMAGE` to an immutable tag
when using the prepuller. A mutable tag can hold the first digest each node
pulled until the DaemonSet restarts and re-resolves the tag.

Disable `sandboxImagePrepull.enabled` when sandbox nodes do not have disk
headroom for the extracted sandbox image plus workspace rootfs capacity.

## Private registries

Private registry credentials must be attached to the sandbox ServiceAccount in
`SANDBOX_NAMESPACE`. The sandbox pod and prepuller both use that account.

Do not add `imagePullSecrets` blocks directly to the sandbox PodTemplate or the
prepuller. A split path can make the prepuller warm an image that sandbox pods
cannot pull.

## Storage capacity

Production Craft stores writable workspace state on the Kata rootfs block
device. Size the containerd devmapper pool for the promised workspace quota.
Kubernetes `ephemeral-storage` requests and limits do not enforce the
devmapper rootfs size.

For a workspace near 50 GiB, set containerd `base_image_size` to at least
64 GiB and reserve real thin-pool capacity on the sandbox node pool. Monitor
the pool and configure auto-extension.

## Historical benchmark note

A May 2026 local kind benchmark showed that trimming the image reduced the
compressed image from 915 MB to 717 MB with skills enabled, and to 581 MB with
skills disabled. The same work reduced extracted size from 4.25 GB to 3.33 GB
and 2.79 GB respectively.

Treat those numbers as historical context, not a current release claim. The
old benchmark script lived under the removed Kubernetes manager tree and is no
longer the active verification path.

## Verification

For image and spinup changes, use checks that match the changed contract:

- image build for Dockerfile and dependency changes
- Helm render checks for PodTemplate and prepuller shape
- a real KVM-capable Kubernetes cluster for Firecracker boot checks
- a real Craft frontend flow before claiming end-to-end success

Do not claim Firecracker or browser integration from static renders alone.
