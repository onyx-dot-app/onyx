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

DEV_HOME=/home/"$TARGET_USER"

if [ "$REMOTE_USER" = "root" ]; then
    ACTIVE_HOME="/root"
else
    ACTIVE_HOME="$DEV_HOME"
fi

# ── Phase 1: home directory setup ───────────────────────────────────

# ~/.local and ~/.cache are named Docker volumes mounted under ~dev.
mkdir -p "$DEV_HOME"/.local/state "$DEV_HOME"/.local/share
chown -R "$TARGET_USER":"$TARGET_USER" "$DEV_HOME"/.local
chown -R "$TARGET_USER":"$TARGET_USER" "$DEV_HOME"/.cache

# Copy host configs mounted as *.host into the active user's home.
# Sources are always under ~dev (that's where devcontainer.json mounts them).
if [ -d "$DEV_HOME/.ssh.host" ]; then
    cp -a "$DEV_HOME/.ssh.host" "$ACTIVE_HOME/.ssh"
    chmod 700 "$ACTIVE_HOME/.ssh"
    chmod 600 "$ACTIVE_HOME"/.ssh/id_* 2>/dev/null || true
    chown -R "$REMOTE_USER":"$REMOTE_USER" "$ACTIVE_HOME/.ssh"
fi
if [ -d "$DEV_HOME/.config/nvim.host" ]; then
    mkdir -p "$ACTIVE_HOME/.config"
    cp -a "$DEV_HOME/.config/nvim.host" "$ACTIVE_HOME/.config/nvim"
    chown -R "$REMOTE_USER":"$REMOTE_USER" "$ACTIVE_HOME/.config/nvim"
fi

# When running as root, symlink bind-mounts and named volumes into /root
# so that $HOME-relative tools (Claude Code, git, etc.) find them.
if [ "$REMOTE_USER" = "root" ] && [ "$ACTIVE_HOME" != "$DEV_HOME" ]; then
    for item in .claude .cache .local; do
        [ -d "$DEV_HOME/$item" ] || continue
        [ -L "/root/$item" ] || rm -rf "/root/$item"
        ln -sfn "$DEV_HOME/$item" "/root/$item"
    done
    [ -f "$DEV_HOME/.claude.json" ] && ln -sf "$DEV_HOME/.claude.json" /root/.claude.json

    # Git: include the host gitconfig and mark the workspace safe.
    printf '[include]\n\tpath = %s/.gitconfig.host\n[safe]\n\tdirectory = %s\n' \
        "$DEV_HOME" "$WORKSPACE" > /root/.gitconfig

    GIT_COMMON_DIR=$(git -C "$WORKSPACE" rev-parse --git-common-dir 2>/dev/null || true)
    if [ -n "$GIT_COMMON_DIR" ] && [ "$GIT_COMMON_DIR" != "$WORKSPACE/.git" ]; then
        [ ! -d "$GIT_COMMON_DIR" ] && GIT_COMMON_DIR="$WORKSPACE/$GIT_COMMON_DIR"
        if [ -d "$GIT_COMMON_DIR" ]; then
            git config -f /root/.gitconfig --add safe.directory "$(dirname "$GIT_COMMON_DIR")"
        fi
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
    if ! chown -R "$TARGET_USER":"$TARGET_USER" /home/"$TARGET_USER" 2>&1; then
        echo "warning: failed to chown /home/$TARGET_USER" >&2
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
