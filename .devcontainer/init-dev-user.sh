#!/usr/bin/env bash
set -euo pipefail

# Remap the dev user's UID/GID to match the workspace owner so that
# bind-mounted files are accessible without running as root.
#
# Standard Docker:   Workspace is owned by the host user's UID (e.g. 1000).
#                    We remap dev to that UID -- fast and seamless.
#
# Rootless Docker:   Workspace appears as root-owned (UID 0) inside the
#                    container due to user-namespace mapping.
#                    • remoteUser=root  → symlink bind-mounts into /root
#                      (container root IS the host user; no permission tricks)
#                    • remoteUser=dev   → grant access with POSIX ACLs

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
    # Workspace is root-owned inside the container.  Grant dev access
    # via POSIX ACLs (preserves ownership, works across the namespace
    # boundary).
    if command -v setfacl &>/dev/null; then
        setfacl -Rm  "u:${TARGET_USER}:rwX" "$WORKSPACE"
        setfacl -Rdm "u:${TARGET_USER}:rwX" "$WORKSPACE"   # default ACL for new files

        # Git refuses to operate in repos owned by a different UID.
        # Host gitconfig is mounted readonly as ~/.gitconfig.host.
        # Create a real ~/.gitconfig that includes it plus container overrides.
        printf '[include]\n\tpath = %s/.gitconfig.host\n[safe]\n\tdirectory = %s\n' \
            "$DEV_HOME" "$WORKSPACE" > "$DEV_HOME/.gitconfig"
        chown "$TARGET_USER":"$TARGET_USER" "$DEV_HOME/.gitconfig"

        # If this is a worktree, the main .git dir is bind-mounted at its
        # host absolute path. Grant dev access so git operations work.
        GIT_COMMON_DIR=$(git -C "$WORKSPACE" rev-parse --git-common-dir 2>/dev/null || true)
        if [ -n "$GIT_COMMON_DIR" ] && [ "$GIT_COMMON_DIR" != "$WORKSPACE/.git" ]; then
            [ ! -d "$GIT_COMMON_DIR" ] && GIT_COMMON_DIR="$WORKSPACE/$GIT_COMMON_DIR"
            if [ -d "$GIT_COMMON_DIR" ]; then
                setfacl -Rm "u:${TARGET_USER}:rwX" "$GIT_COMMON_DIR"
                setfacl -Rdm "u:${TARGET_USER}:rwX" "$GIT_COMMON_DIR"
                git config -f "$DEV_HOME/.gitconfig" --add safe.directory "$(dirname "$GIT_COMMON_DIR")"
            fi
        fi

        # Also fix bind-mounted dirs under ~dev that appear root-owned.
        for dir in /home/"$TARGET_USER"/.claude; do
            [ -d "$dir" ] && setfacl -Rm "u:${TARGET_USER}:rwX" "$dir" && setfacl -Rdm "u:${TARGET_USER}:rwX" "$dir"
        done
        [ -f /home/"$TARGET_USER"/.claude.json ] && \
            setfacl -m "u:${TARGET_USER}:rw" /home/"$TARGET_USER"/.claude.json
    else
        echo "warning: setfacl not found; dev user may not have write access to workspace" >&2
        echo "         install the 'acl' package or set DEVCONTAINER_REMOTE_USER=root" >&2
    fi
fi
