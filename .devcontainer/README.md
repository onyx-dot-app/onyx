# Onyx Dev Container

A containerized development environment for working on Onyx.

## What's included

- Ubuntu 25.10 base image
- Node.js 20
- Claude Code
- Zsh as default shell (sources host `~/.zshrc` if available)
- Python venv auto-activation
- Network firewall (default-deny, whitelists only npm, GitHub, and Anthropic APIs)

## Usage

### VS Code

1. Install the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
2. Open this repo in VS Code
3. "Reopen in Container" when prompted

### CLI (`ods dev`)

The [`ods` devtools CLI](../tools/ods/README.md) provides workspace-aware wrappers
for all devcontainer operations (also available as `ods dc`):

```bash
# Start the container
ods dev up

# Open a shell
ods dev into

# Run a command
ods dev exec -- npm test

# Stop the container
ods dev stop
```

If you don't have `ods` installed, use the `devcontainer` CLI directly:

```bash
npm install -g @devcontainers/cli

devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . zsh
```

## Restarting the container

### VS Code

Open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`) and run:

- **Dev Containers: Reopen in Container** — restarts the container without rebuilding

### CLI

```bash
# Restart the container
ods dev restart

# Pull the latest published image and recreate
ods dev rebuild
```

Or without `ods`:

```bash
devcontainer up --workspace-folder . --remove-existing-container
```

## Image

The devcontainer uses a prebuilt image published to `onyxdotapp/onyx-devcontainer`.
The tag is pinned in `devcontainer.json` — no local build is required.

To build the image locally (e.g. while iterating on the Dockerfile):

```bash
docker buildx bake devcontainer
```

The `devcontainer` target is defined in `docker-bake.hcl` at the repo root.

## Firewall

The container starts with a default-deny firewall (`init-firewall.sh`) that only allows outbound traffic to:

- npm registry
- GitHub
- Anthropic API
- Sentry
- VS Code update servers

This requires the `NET_ADMIN` and `NET_RAW` capabilities, which are added via `runArgs` in `devcontainer.json`.
