#!/usr/bin/env bash
set -euo pipefail

# Remap the dev user's UID/GID to match the workspace owner so that
# bind-mounted files are accessible without running as root.
#
# Standard Docker:   Workspace is owned by the host user's UID (e.g. 1000).
#                    We remap dev to that UID — fast and seamless.
#
# Rootless Docker:   Workspace appears as root-owned (UID 0) inside the
#                    container due to user-namespace mapping.  We can't remap
#                    dev to UID 0 (that's root), so we grant access with
#                    POSIX ACLs instead.

WORKSPACE=/workspace
TARGET_USER=dev

WS_UID=$(stat -c '%u' "$WORKSPACE")
WS_GID=$(stat -c '%g' "$WORKSPACE")
DEV_UID=$(id -u "$TARGET_USER")
DEV_GID=$(id -g "$TARGET_USER")

DEV_HOME=/home/"$TARGET_USER"

# Ensure directories that tools expect exist under ~dev.
# ~/.local is a named Docker volume — ensure subdirs exist and are owned by dev.
mkdir -p "$DEV_HOME"/.local/state "$DEV_HOME"/.local/share
chown -R "$TARGET_USER":"$TARGET_USER" "$DEV_HOME"/.local

# Copy host configs mounted as *.host into their real locations.
# This gives the dev user owned copies without touching host originals.
if [ -d "$DEV_HOME/.ssh.host" ]; then
    cp -a "$DEV_HOME/.ssh.host" "$DEV_HOME/.ssh"
    chmod 700 "$DEV_HOME/.ssh"
    chmod 600 "$DEV_HOME"/.ssh/id_* 2>/dev/null || true
    chown -R "$TARGET_USER":"$TARGET_USER" "$DEV_HOME/.ssh"
fi
if [ -d "$DEV_HOME/.config/nvim.host" ]; then
    mkdir -p "$DEV_HOME/.config"
    cp -a "$DEV_HOME/.config/nvim.host" "$DEV_HOME/.config/nvim"
    chown -R "$TARGET_USER":"$TARGET_USER" "$DEV_HOME/.config/nvim"
fi

# Already matching — nothing to do.
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
        echo "         install the 'acl' package or set remoteUser to root" >&2
    fi
fi
