# Craft image & deployment architecture

**Craft is a runtime feature, not a separate image flavor.** There are no
`craft-*` images or tags. The regular Onyx images run Craft; you turn it on
with `ENABLE_CRAFT=true`.

## Why there's no craft backend image

The Craft agent (`opencode`) runs entirely inside the **sandbox container**.
The api_server is just an HTTP client to `opencode-serve` (it never executes
`opencode`/`node` itself), and there is no `local` sandbox backend — only
`docker` and `kubernetes`, both of which run the agent in the sandbox.

So the backend needs nothing craft-specific baked in. `ENABLE_CRAFT` is read
at runtime (`onyx/server/features/build/configs.py`) to toggle the feature.

## The images

| Image | Craft-specific? | Notes |
|---|---|---|
| `onyxdotapp/onyx-backend` | No | Standard image. `ENABLE_CRAFT=true` at runtime enables Craft. |
| `onyxdotapp/onyx-web-server` | No | Standard image. |
| `onyxdotapp/onyx-model-server` | No | Standard image. |
| **`onyxdotapp/sandbox`** | **Yes** | The only Craft-specific image. Bundles Node + the `opencode` CLI; runs the agent. |

## How the sandbox image is built

`.github/workflows/sandbox-deployment.yml` builds it on the **nightly** tag
(`nightly-latest-*`), but only when its build context
(`backend/onyx/server/features/build/sandbox/image/`) changed since the
previous nightly. It publishes `onyxdotapp/sandbox:vX.Y.Z` (auto-incremented
patch) + `:latest`. Run it manually any time via the workflow's
`workflow_dispatch` to cut a build on demand.

For an ad-hoc dev build, push the `sandbox-dev` git tag:

```bash
git tag -f sandbox-dev && git push -f origin sandbox-dev
```

This builds unconditionally and pushes `onyxdotapp/sandbox:dev`. Dev builds
never cut a `vX.Y.Z` version or move `:latest` — those only happen on the
nightly path. Only `sandbox-dev` is supported, to keep Docker Hub free of
one-off tags.

Sandbox pods default to `imagePullPolicy: IfNotPresent`, which would keep
serving a node-cached `:dev` after a re-push. Environments that pin the
mutable `:dev` tag must also set `SANDBOX_IMAGE_PULL_POLICY=Always` (next to
`SANDBOX_CONTAINER_IMAGE` in the env config) so new pods always pull the
latest dev build. Already running sandbox pods are unaffected — delete them
to pick up the new image.

The backend does **not** track `:latest` — it pins a specific version via
`SANDBOX_CONTAINER_IMAGE` (default in `configs.py`). Bump that pin to adopt a
new sandbox version.

## Deploying Craft

Use the **normal** image tags (`latest` / `edge` / `vX.Y.Z`) and turn Craft on:

**docker-compose** (`--include-craft` does this for you):
```
ENABLE_CRAFT=true
SANDBOX_BACKEND=docker
SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:vX.Y.Z   # optional; defaults to the pinned version
```

**Kubernetes (helm):**
```
ENABLE_CRAFT=true
SANDBOX_BACKEND=kubernetes
# global.version / per-component tags use the normal release tags
```

## What changed (history)

Previously there were `craft-latest` / `craft-edge` images built with a
`--build-arg ENABLE_CRAFT=true` that installed Node + opencode into the
backend. That was a leftover from the old `local` sandbox backend (agent in
the api_server process). With `local` gone, the agent lives only in the
sandbox image, so the craft backend build, the `craft-*` tags, and the
`ENABLE_CRAFT` build-arg were all removed.
