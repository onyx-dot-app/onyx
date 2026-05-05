#!/usr/bin/env bash
set -euo pipefail

# Remap the dev user's UID/GID to match the workspace owner so that
# bind-mounted files are accessible without running as root.
#
# Standard Docker:   Workspace is owned by the host user's UID (e.g. 1000).
#                    We remap dev to that UID -- fast and seamless.
#
# Rootless Docker:   Workspace appears as root-owned (UID 0) inside the
#                    container due to user-namespace mapping.  Requires
#                    DEVCONTAINER_REMOTE_USER=root (set automatically by
#                    ods dev up).  Container root IS the host user, so
#                    bind-mounts and named volumes are symlinked into /root.

WORKSPACE=/workspace
TARGET_USER=dev
REMOTE_USER="${SUDO_USER:-$TARGET_USER}"

WS_UID=$(stat -c '%u' "$WORKSPACE")
WS_GID=$(stat -c '%g' "$WORKSPACE")
DEV_UID=$(id -u "$TARGET_USER")
DEV_GID=$(id -g "$TARGET_USER")

# devcontainer.json bind-mounts and named volumes target /home/dev regardless
# of remoteUser.  When running as root ($HOME=/root), Phase 1 bridges the gap
# with symlinks from ACTIVE_HOME → MOUNT_HOME.
MOUNT_HOME=/home/"$TARGET_USER"

if [ "$REMOTE_USER" = "root" ]; then
    ACTIVE_HOME="/root"
else
    ACTIVE_HOME="$MOUNT_HOME"
fi

# ── Phase 1: home directory setup ───────────────────────────────────

# ~/.local and ~/.cache are named Docker volumes mounted under MOUNT_HOME.
mkdir -p "$MOUNT_HOME"/.local/state "$MOUNT_HOME"/.local/share

# When running as root, symlink bind-mounts and named volumes into /root
# so that $HOME-relative tools (Claude Code, git, etc.) find them.
if [ "$ACTIVE_HOME" != "$MOUNT_HOME" ]; then
    for item in .claude .cache .local; do
        [ -d "$MOUNT_HOME/$item" ] || continue
        if [ -e "$ACTIVE_HOME/$item" ] && [ ! -L "$ACTIVE_HOME/$item" ]; then
            echo "warning: replacing $ACTIVE_HOME/$item with symlink to $MOUNT_HOME/$item" >&2
            rm -rf "${ACTIVE_HOME:?}/$item"
        fi
        ln -sfn "$MOUNT_HOME/$item" "$ACTIVE_HOME/$item"
    done
    # Symlink files (not directories).
    for file in .claude.json .gitconfig .zshrc.host; do
        [ -f "$MOUNT_HOME/$file" ] && ln -sf "$MOUNT_HOME/$file" "$ACTIVE_HOME/$file"
    done

    # Nested mount: .config/nvim
    if [ -d "$MOUNT_HOME/.config/nvim" ]; then
        mkdir -p "$ACTIVE_HOME/.config"
        if [ -e "$ACTIVE_HOME/.config/nvim" ] && [ ! -L "$ACTIVE_HOME/.config/nvim" ]; then
            echo "warning: replacing $ACTIVE_HOME/.config/nvim with symlink" >&2
            rm -rf "$ACTIVE_HOME/.config/nvim"
        fi
        ln -sfn "$MOUNT_HOME/.config/nvim" "$ACTIVE_HOME/.config/nvim"
    fi
fi

# ── Phase 2: workspace access ───────────────────────────────────────

# Root always has workspace access; Phase 1 handled home setup.
if [ "$REMOTE_USER" = "root" ]; then
    exit 0
fi

# Already matching -- nothing to do.
if [ "$WS_UID" = "$DEV_UID" ] && [ "$WS_GID" = "$DEV_GID" ]; then
    exit 0
fi

if [ "$WS_UID" != "0" ]; then
    # ── Standard Docker ──────────────────────────────────────────────
    # Workspace is owned by a non-root UID (the host user).
    # Remap dev's UID/GID to match.
    if [ "$DEV_GID" != "$WS_GID" ]; then
        if ! groupmod -g "$WS_GID" "$TARGET_USER" 2>&1; then
            echo "warning: failed to remap $TARGET_USER GID to $WS_GID" >&2
        fi
    fi
    if [ "$DEV_UID" != "$WS_UID" ]; then
        if ! usermod -u "$WS_UID" -g "$WS_GID" "$TARGET_USER" 2>&1; then
            echo "warning: failed to remap $TARGET_USER UID to $WS_UID" >&2
        fi
    fi
    if ! chown -R "$TARGET_USER":"$TARGET_USER" "$MOUNT_HOME" 2>&1; then
        echo "warning: failed to chown $MOUNT_HOME" >&2
    fi
else
    # ── Rootless Docker ──────────────────────────────────────────────
    # Workspace is root-owned (UID 0) due to user-namespace mapping.
    # The supported path is remoteUser=root (set DEVCONTAINER_REMOTE_USER=root),
    # which is handled above.  If we reach here, the user is running as dev
    # under rootless Docker without the override.
    echo "error: rootless Docker detected but remoteUser is not root." >&2
    echo "       Set DEVCONTAINER_REMOTE_USER=root before starting the container," >&2
    echo "       or use 'ods dev up' which sets it automatically." >&2
    exit 1
fi
