# Sandbox Container Image

This directory contains the Dockerfile and resources for building the Onyx Craft sandbox container image.

## Directory Structure

```
image/
├── Dockerfile              # Main container image definition
├── .dockerignore           # Trims the build context
├── entrypoint.sh           # Container startup (+ sidecar-entrypoint.sh, firewall-init.sh)
├── sandbox_daemon/         # In-pod push/snapshot daemon (baked in)
├── opencode-plugins/       # Per-session egress tagging plugin (baked in)
├── templates/
│   └── outputs/            # Web app scaffold template (Next.js)
├── initial-requirements.in  # Curated Python packages pre-installed in sandbox
├── initial-requirements.txt # Fully pinned Python lock for sandbox
└── README.md               # This file
```

Built-in skill sources are **not** here — they live in `backend/onyx/skills/builtin/`
and are pushed into sandboxes at session setup, never baked into the image.

## Building the Image

### Via CI (preferred)

Application release CI publishes this image under the same tag as the app
image, e.g. `onyxdotapp/sandbox:v4.1.2` for app tag `v4.1.2`.

The sandbox jobs in `.github/workflows/deployment.yml` compute a content tag
from this directory (`ctx-<hash>`). If the content tag already exists, the
deployment workflow only adds the requested app tag/alias to the existing
manifest. If the content tag does not exist, it builds multi-arch once, pushes
`ctx-<hash>`, and then adds the app-aligned tags.

Use that workflow manually only to backfill or repair a supplied application
tag. Do not publish sandbox-only `v0.1.x` tags or a Docker Hub
`onyxdotapp/sandbox:dev` tag for new builds. Local development can still build
`onyxdotapp/sandbox:dev` and load it directly into kind.

### Building locally

The sandbox image must be built for **amd64** architecture since our Kubernetes cluster runs on x86_64 nodes.

### Build for amd64 only (fastest)

```bash
cd backend/onyx/server/features/build/sandbox/image
docker build --platform linux/amd64 -t onyxdotapp/sandbox:dev .
```

### Build multi-arch for backfill or repair

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t onyxdotapp/sandbox:<app-tag> \
  --push .
```

## Deploying a New Version

Deploy the matching application tag. The deploy surface derives the sandbox
image from the app version:

- Docker compose: `onyxdotapp/sandbox:${IMAGE_TAG}`.
- Helm: `onyxdotapp/sandbox:${global.version}`.

Docker compose follows the normal app-image `IMAGE_TAG` behavior, including the
default `latest`. Kubernetes deployments should prefer immutable application
release tags unless they deliberately opt into moving tags.

`SANDBOX_CONTAINER_IMAGE` remains an internal escape hatch for local testing,
staging, cloud, and emergency operations.

## What's Baked Into the Image

- **Base**: `python:3.13-slim` (Debian-based) with Node.js 24 copied from `node:24-trixie-slim`
- **Templates**: `/workspace/templates/outputs/` — Next.js web app scaffold
- **Python venv**: `/workspace/.venv/` with packages from `initial-requirements.txt`
- **OpenCode CLI**: Installed in `/home/sandbox/.opencode/bin/`
- **onyx-cli**: `/usr/local/bin/onyx-cli` — Onyx CLI for search
- **Snapshot sidecar daemon**: Packages and restores session files; durable storage is handled by the api_server through the Onyx FileStore

Skills are **not** baked in — the API server pushes them to `/workspace/managed/skills/` at session setup.

## Runtime Directory Structure

When a session is created, the following structure is set up in the pod:

```
/workspace/
├── managed/skills/         # Pushed at session-setup time (built-ins + customs)
├── opencode-data/          # Sandbox-global opencode data in Kubernetes
├── templates/              # Baked into image
└── sessions/
    └── $session_id/
        ├── .opencode/
        │   └── skills      # Symlink → /workspace/managed/skills
        ├── outputs/        # Copied from templates, contains web app
        ├── attachments/    # User-uploaded files
        ├── AGENTS.md       # Instructions for the AI agent
        └── opencode.json   # OpenCode configuration
```

## Troubleshooting

### Verify image exists on Docker Hub

```bash
curl -s "https://hub.docker.com/v2/repositories/onyxdotapp/sandbox/tags" | jq '.results[].name'
```

### Check what image a pod is using

```bash
kubectl get pod <pod-name> -n onyx-sandboxes -o jsonpath='{.spec.containers[?(@.name=="sandbox")].image}'
```
