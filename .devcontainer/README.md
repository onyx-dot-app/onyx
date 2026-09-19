# Onyx Dev Container

A containerized development environment for working on Onyx.

## What's included

- Ubuntu 26.04 base image
- Node.js 20, uv, Claude Code
- GitHub CLI (`gh`)
- Neovim, ripgrep, fd, fzf, jq, make, wget, unzip
- Zsh as default shell (sources host `~/.zshrc` if available)
- Python venv auto-activation
- Optional opt-in network firewall (default-deny, whitelists npm, GitHub, Anthropic APIs, Sentry, and VS Code update servers)

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
ods dev exec bun run test

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

## Claude Code memory (devcontainer overlay)

`.devcontainer/claude-code/CLAUDE.md` holds Claude Code instructions that apply **only inside
the container** (e.g. service hostnames, "no Docker daemon in here"). It is bind-mounted
read-only to `/etc/claude-code/CLAUDE.md` — Claude Code's managed-policy memory location — so it
loads automatically alongside the project's root `CLAUDE.md`.

Because it is a live bind mount, editing the file in the repo takes effect on the next Claude
Code session — no image rebuild or container restart required. The directory (rather than the
single file) is mounted so that atomic-save editors don't detach the mount, and so additional
managed config (e.g. `managed-settings.json`) can be dropped in alongside it later.

## Firewall

The container ships with an **opt-in** default-deny firewall (`init-firewall.sh`).
When enabled, it only allows outbound traffic to:

- npm registry
- GitHub
- Anthropic API
- Sentry
- VS Code update servers

To enable it, set `ONYX_DEVCONTAINER_FIREWALL=1` in your host environment before
starting the container (e.g. via `ods dev up`):

```bash
export ONYX_DEVCONTAINER_FIREWALL=1
ods dev up
```

The variable is forwarded into the container via `containerEnv` and read by
`postStartCommand`, which then runs `init-firewall.sh`. Without the variable set
to `1`, the firewall script is skipped and the container has unrestricted
outbound network access.

You can also enable the firewall on a running container by running
`sudo bash /workspace/.devcontainer/init-firewall.sh` from inside it.

The firewall requires the `NET_ADMIN` and `NET_RAW` capabilities, which are
always added via `runArgs` in `devcontainer.json` so the firewall can be
toggled on after container start without recreating the container.
