# Craft Sandbox Image Tagging Plan

## Problem

The sandbox image currently has an independent tag lifecycle from the main Onyx
application images. Application images are released as stable, beta, nightly,
and cloud tags, while the sandbox image is published as its own `v0.1.x`,
`latest`, and `dev` series.

That creates two bad properties:

- `SANDBOX_CONTAINER_IMAGE` is pinned in runtime config, so every sandbox fix
  requires both publishing a new sandbox image and then updating application
  config to point at it.
- Sandbox tags do not communicate which application release they are compatible
  with.

Craft is still beta, so we should optimize for a clean model over preserving
the old tag scheme.

## Requirements

- When an application image is tagged stable or beta, the sandbox image must
  also receive that same tag.
- Cloud runs from `main`, so cloud deploys need a sandbox image built from the
  same source line as the application deploy.
- Sandbox image changes happen in bursts, followed by periods where many app
  tags may happen without sandbox content changes.
- Runtime defaults should not require hotfixing `configs.py` to adopt a sandbox
  fix.
- Customers should not configure sandbox image tags separately from the
  application version. The app version selects the matching sandbox image.
- Stop publishing a Docker Hub sandbox `dev` tag. Local development may still
  build `onyxdotapp/sandbox:dev` and load it directly into kind.

## Tag Model

Use the application tag as the public compatibility contract for the sandbox
image.

For an application tag `X`, `onyxdotapp/sandbox:X` must exist before that app
tag is considered deployable for Craft.

Examples:

- Stable: `onyxdotapp/sandbox:v4.1.2`
- Beta: `onyxdotapp/sandbox:v4.2.0-beta.0`
- Nightly/main: `onyxdotapp/sandbox:nightly-latest-20260616`
- Cloud: `onyxdotapp/sandbox:v4.1.0-cloud.6`

Moving channel tags may exist as registry aliases only:

- `latest` points at the latest stable sandbox image.
- `beta` points at the latest beta sandbox image.
- `edge` points at the latest nightly/main sandbox image.

Do not make these a separate sandbox runtime contract. They are useful for
internal smoke tests, discovery, and dev/staging/cloud deploy flows. Docker
compose may still follow the existing application `IMAGE_TAG=latest` default;
the important contract is that the sandbox image follows the application tag
rather than being configured independently.

Do not continue publishing sandbox-only `v0.1.x` tags for new builds. Keep old
tags in Docker Hub for existing users, but stop producing them.

## Build Model

Separate sandbox content identity from release aliases.

1. Compute a content key from the sandbox image build context:
   `backend/onyx/server/features/build/sandbox/image/`.
2. Publish the built image under a content tag, for example
   `onyxdotapp/sandbox:ctx-<hash>`.
3. For every application release tag, retag the matching content image to the
   application tag.

If the sandbox build context has not changed since the last app release, CI
should only add new tag aliases to the existing sandbox manifest. It should not
rebuild the image.

If the sandbox build context has changed, CI should build the image once,
publish the new `ctx-<hash>` tag, and then add the application tag aliases.

## Runtime Defaults

Deploy surfaces should default the sandbox image from the selected application
version, not from a hardcoded sandbox version.

Preferred defaults:

- Docker compose: `onyxdotapp/sandbox:${IMAGE_TAG}`.
- Helm: `onyxdotapp/sandbox:${global.version}`.

Docker compose should follow the existing app-image `IMAGE_TAG` behavior,
including `latest`. Kubernetes deployments should prefer immutable application
release tags unless they deliberately opt into moving tags.

`SANDBOX_CONTAINER_IMAGE` should remain as an internal escape hatch for Onyx
dev, staging, cloud, and emergency operations. It should not be presented as a
normal customer-facing setting.

## Pull Policy

Kubernetes production should normally use immutable app-aligned tags with
`IfNotPresent`.

`imagePullPolicy: Always` is appropriate only for internal deployments that
deliberately use mutable sandbox tags. In Kubernetes, it checks the registry on
every sandbox pod start, which adds latency and makes each cold sandbox depend
on registry availability.

Docker compose does not use Kubernetes pull policy. The Docker sandbox manager
must ensure the configured sandbox image is available before the first sandbox
spinup in a process, because not every deployment path runs the installer.
Immutable app-aligned tags should be pulled only if missing. Moving tags such
as `latest`, `beta`, and `edge` should refresh once per process and then use
the local image for sandbox creation.

## CI Changes

- Make the app image release workflow responsible for ensuring the matching
  sandbox tag exists.
- Ensure cloud deployment dispatch waits for the matching sandbox tag.
- Update the manual `latest` and `beta` retag workflows to retag the sandbox
  image as well as backend, web, and model-server images.
- Fold sandbox build/retag jobs into the normal app image deployment workflow;
  the sandbox image should no longer have an independent release workflow.
- Remove the `sandbox-dev` trigger and stop publishing a Docker Hub
  `onyxdotapp/sandbox:dev` tag.
- Remove `SANDBOX_CONTAINER_IMAGE` from customer docs/templates except where
  documenting internal override behavior.

## Migration

1. Backfill current active tags on `onyxdotapp/sandbox`, including current
   stable, beta, edge/nightly, and active cloud tags.
2. Change runtime defaults away from `onyxdotapp/sandbox:v0.1.x`.
3. Stop publishing new sandbox-only `v0.1.x` tags and the Docker Hub `dev` tag.
4. Update compose, Helm, runtime defaults, and docs so Craft users deploy one
   application tag and get the matching sandbox image automatically.
