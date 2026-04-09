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

# Already matching — nothing to do.
if [ "$WS_UID" = "$DEV_UID" ] && [ "$WS_GID" = "$DEV_GID" ]; then
    exit 0
fi

# Ensure directories that neovim/tools expect exist under ~dev
# (they may not be bind-mounted and the image doesn't create them).
# chown only the dirs we create — bind-mounted dirs are handled below
# via UID remapping (standard Docker) or ACLs (rootless Docker).
mkdir -p /home/"$TARGET_USER"/.local/state /home/"$TARGET_USER"/.local/share
chown "$TARGET_USER":"$TARGET_USER" /home/"$TARGET_USER"/.local /home/"$TARGET_USER"/.local/state

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

        # Also fix writable bind-mounted dirs under ~dev that appear root-owned.
        # Skip readonly mounts (e.g. ~/.config/nvim) — they're readable by all.
        for dir in /home/"$TARGET_USER"/.local /home/"$TARGET_USER"/.claude; do
            [ -d "$dir" ] && setfacl -Rm "u:${TARGET_USER}:rwX" "$dir" && setfacl -Rdm "u:${TARGET_USER}:rwX" "$dir"
        done
        [ -f /home/"$TARGET_USER"/.claude.json ] && \
            setfacl -m "u:${TARGET_USER}:rw" /home/"$TARGET_USER"/.claude.json
    else
        echo "warning: setfacl not found; dev user may not have write access to workspace" >&2
        echo "         install the 'acl' package or set remoteUser to root" >&2
    fi
fi
