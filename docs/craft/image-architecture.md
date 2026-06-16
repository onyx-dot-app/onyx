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

## How the sandbox image is built & versioned

The sandbox is an **independently-versioned dependency** of Onyx, published
**manually** — it is *not* built on nightly or release tags. This keeps the
lifecycle consistent: a new sandbox version is a deliberate publish, and adopting
it is a deliberate pin bump (no auto-publish that you then have to manually adopt).

`.github/workflows/sandbox-deployment.yml` is the only thing that publishes it:

- **`sandbox-edge` git tag** (or `workflow_dispatch`) → **if the build context
  changed**, auto-increments the patch off the highest published tag and pushes
  `onyxdotapp/sandbox:vX.Y.Z` + `:edge` (+ a `src-<hash>` dedup tag). The context
  is fingerprinted by its git tree hash, so pushing the tag with no change is a
  no-op — no new version:
  ```bash
  git tag -f sandbox-edge && git push -f origin sandbox-edge
  ```
- **`sandbox-dev` git tag** → builds and pushes the mutable `onyxdotapp/sandbox:dev`:
  ```bash
  git tag -f sandbox-dev && git push -f origin sandbox-dev
  ```

**Onyx pins the sandbox version it requires** via `SANDBOX_CONTAINER_IMAGE`
(default in `configs.py`, a specific `onyxdotapp/sandbox:vX.Y.Z`). The pin is
committed, so each Onyx version reproducibly resolves its sandbox. Bumping the
pin to adopt a newer sandbox is a deliberate, reviewable change — a future
`ods release sandbox` command will dispatch the publish workflow and bump the
pin in one step.

Immutable `:vX.Y.Z` pins are safe with the default `imagePullPolicy: IfNotPresent`.
Environments pinning a mutable tag (`:dev`, `:edge`) must set
`SANDBOX_IMAGE_PULL_POLICY=Always` and delete running sandbox pods to pick up a
re-push.

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
