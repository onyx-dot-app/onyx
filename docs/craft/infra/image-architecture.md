# Craft image & deployment architecture

**Craft uses the standard Onyx application images.** There are no `craft-*`
app/backend images or tags. The regular Onyx images run Craft; you turn it on
with `ENABLE_CRAFT=true`. The sandbox is a separate runtime image and uses the
same tag as the application release by default.

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

The application release workflow publishes the sandbox image under the same
tag as the application image. For an application tag `X`,
`onyxdotapp/sandbox:X` must exist before Craft deploys that app tag.

The sandbox jobs in `.github/workflows/deployment.yml` key image content by the
build context at `backend/onyx/server/features/build/sandbox/image/` and
publish a content tag (`ctx-<hash>`). If a later application release does not
change the sandbox context, CI only adds new aliases to the existing manifest
instead of rebuilding it.

Public runtime tags:

- Stable app tags publish matching stable sandbox tags, e.g.
  `onyxdotapp/sandbox:v4.1.2`.
- Beta app tags publish matching beta sandbox tags, e.g.
  `onyxdotapp/sandbox:v4.2.0-beta.0`.
- Cloud/nightly/main tags publish matching sandbox tags, e.g.
  `onyxdotapp/sandbox:v4.1.0-cloud.6` or
  `onyxdotapp/sandbox:nightly-latest-20260616`.
- `latest`, `beta`, and `edge` may exist as moving registry aliases for
  internal/dev/staging/cloud flows. They are not the customer deployment
  contract.

We do not publish sandbox-only `v0.1.x` tags or a Docker Hub
`onyxdotapp/sandbox:dev` tag for new builds. Local development can still use
`onyxdotapp/sandbox:dev` as a locally built, kind-loaded image tag.

Kubernetes sandbox pods default to the chart's app image pull policy. Internal
clusters that deliberately use moving tags such as `latest`, `beta`, or `edge`
should set `SANDBOX_IMAGE_PULL_POLICY=Always` alongside the matching app image
pull policy.

Docker compose follows the existing compose `IMAGE_TAG` behavior, including the
default `latest`. Since sandboxes are created later by the Docker manager rather
than by compose, the manager pulls immutable tags only when missing and refreshes
moving tags once per API process.

## Deploying Craft

Use the **normal** application image tags and turn Craft on. Customers should
not choose a separate sandbox tag; the app version selects the matching
sandbox image.

**docker-compose** (`--include-craft` does this for you):
```
ENABLE_CRAFT=true
SANDBOX_BACKEND=docker
# sandbox defaults to onyxdotapp/sandbox:${IMAGE_TAG}
```

**Kubernetes (helm):**
```
ENABLE_CRAFT=true
SANDBOX_BACKEND=kubernetes
global.version: vX.Y.Z
# sandbox defaults to onyxdotapp/sandbox:${global.version}
```
