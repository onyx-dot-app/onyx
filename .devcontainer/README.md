# Onyx Dev Container

A containerized development environment for working on Onyx.

## What's included

- Ubuntu 26.04 base image
- Node.js 20, uv, Claude Code
- Docker CLI, GitHub CLI (`gh`)
- Neovim, ripgrep, fd, fzf, jq, make, wget, unzip
- Zsh as default shell (sources host `~/.zshrc` if available)
- Python venv auto-activation
- Network firewall (default-deny, whitelists npm, GitHub, Anthropic APIs, Sentry, and VS Code update servers)

## Usage

### CLI (`ods dev`)

The [`ods` devtools CLI](../tools/ods/README.md) provides workspace-aware wrappers
for all devcontainer operations (also available as `ods dc`):

```bash
# Start the container
ods dev up

# Open a shell
ods dev into

# Run a command
ods dev exec npm test

# Stop the container
ods dev stop
```

## Restarting the container

```bash
# Restart the container
ods dev restart

# Pull the latest published image and recreate
ods dev rebuild
```

## Image

The devcontainer uses a prebuilt image published to `onyxdotapp/onyx-devcontainer`.
The tag is pinned in `devcontainer.json` — no local build is required.

To build the image locally (e.g. while iterating on the Dockerfile):

```bash
docker buildx bake devcontainer
```

The `devcontainer` target is defined in `docker-bake.hcl` at the repo root.

## User & permissions

The container runs as the `dev` user by default (`remoteUser` in devcontainer.json).
An init script (`init-dev-user.sh`) runs at container start to ensure the active
user has read/write access to the bind-mounted workspace:

- **Standard Docker** — `dev`'s UID/GID is remapped to match the workspace owner,
  so file permissions work seamlessly.
- **Rootless Docker** — The workspace appears as root-owned (UID 0) inside the
  container due to user-namespace mapping. `ods dev up` auto-detects rootless Docker
  and sets `DEVCONTAINER_REMOTE_USER=root` so the container runs as root — which
  maps back to your host user via the user namespace. New files are owned by your
  host UID and no ACL workarounds are needed.

  To override the auto-detection, set `DEVCONTAINER_REMOTE_USER` before running
  `ods dev up`.

## Docker socket

The container mounts the host's Docker socket so you can run `docker` commands
from inside. `ods dev` auto-detects the socket path and sets `DOCKER_SOCK`:

| Environment             | Socket path                    |
| ----------------------- | ------------------------------ |
| Linux (rootless Docker) | `$XDG_RUNTIME_DIR/docker.sock` |
| macOS (Docker Desktop)  | `~/.docker/run/docker.sock`    |
| Linux (standard Docker) | `/var/run/docker.sock`         |

To override, set `DOCKER_SOCK` before running `ods dev up`.

## Firewall

The container starts with a default-deny firewall (`init-firewall.sh`) that only allows outbound traffic to:

- npm registry
- GitHub
- Anthropic API
- Sentry
- VS Code update servers

This requires the `NET_ADMIN` and `NET_RAW` capabilities, which are added via `runArgs` in `devcontainer.json`.
