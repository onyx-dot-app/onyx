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

Sandbox images are published **manually** by
`.github/workflows/sandbox-deployment.yml` — never on nightly or release tags:

- **Push the `sandbox-edge` git tag** (or run the workflow via
  `workflow_dispatch`) to cut a versioned release. It publishes a new
  `onyxdotapp/sandbox:vX.Y.Z` + `:edge` **only if the build context changed**
  (fingerprinted by git tree hash); an unchanged context is a no-op:
  ```bash
  git tag -f sandbox-edge && git push -f origin sandbox-edge
  ```
- **Push the `sandbox-dev` git tag** for an ad-hoc dev build →
  `onyxdotapp/sandbox:dev`:
  ```bash
  git tag -f sandbox-dev && git push -f origin sandbox-dev
  ```

Environments that pin `SANDBOX_CONTAINER_IMAGE` to `:dev` must also set
`SANDBOX_IMAGE_PULL_POLICY=Always` (default `IfNotPresent`) so re-pushed dev
builds are picked up by new pods. See `docs/craft/image-architecture.md`.

### Building locally

For local iteration, build and load straight into your kind cluster as `:dev`
(don't hand-push `vX.Y.Z` / channel tags — the `sandbox-deployment.yml` workflow
owns those, and a manual push would desync the auto-increment):

```bash
cd backend/onyx/server/features/build/sandbox/image
docker build --platform linux/amd64 -t onyxdotapp/sandbox:dev .
kind load docker-image onyxdotapp/sandbox:dev --name onyx-dev
```

Run with `SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:dev` and
`SANDBOX_IMAGE_PULL_POLICY=Always`. (The repo-root `make` targets automate this.)
Build for **amd64** to match the cluster nodes; add `linux/arm64` via
`docker buildx --platform linux/amd64,linux/arm64` if you need both.

## Deploying a New Version

1. **Publish** the new sandbox version — push the `sandbox-edge` tag
   (`git tag -f sandbox-edge && git push -f origin sandbox-edge`), which cuts the
   next `vX.Y.Z` + `:edge`.

2. **Bump the pin** — set `SANDBOX_CONTAINER_IMAGE` in `configs.py` (and the
   `docker-compose.craft.yml` defaults) to the new `vX.Y.Z`. This is the
   reviewable step that makes an Onyx version adopt the new sandbox; a future
   `ods release sandbox` command will do steps 1–2 in one shot.

3. **Roll out** the new config and recreate sandbox pods so they pull the new
   image:
   ```bash
   kubectl delete pods -n onyx-sandboxes -l app.kubernetes.io/component=sandbox
   ```

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
