"""Snapshot create/restore operations for the sandbox sidecar.

Shells out to s5cmd (baked into the image via multi-stage COPY) to
upload/download tar.gz archives to/from S3. Tarring/extraction happens
via shell pipelines so we don't buffer large snapshots in memory.
"""

import shlex
import subprocess
from pathlib import Path
from uuid import UUID

from sandbox_daemon.models import SnapshotCreateStatus

SESSIONS_ROOT = Path("/workspace/sessions")
# Must match onyx.server.features.build.sandbox.base.BUN_CACHE_DIR — the
# daemon can't import from the main package at runtime, hence the copy.
BUN_CACHE_DIR = SESSIONS_ROOT / ".bun-cache"
BUN_IMAGE_CACHE_DIR = Path("/home/sandbox/.bun/install/cache")


class SnapshotError(RuntimeError):
    """Raised when a snapshot subprocess fails. Carries stderr from the
    underlying tool (s5cmd / tar) so the manager can see the cause.
    """


def _run(script: str) -> None:
    """Run a shell script with stderr merged into stdout for the error.

    We deliberately merge stderr into stdout (rather than capturing them
    separately) so a failure anywhere in a `tar | s5cmd` pipeline always
    surfaces *something* in the SnapshotError — `set -o pipefail` can
    otherwise tear the stream down before stderr buffers flush, leaving
    a useless "no output" diagnostic.
    """
    try:
        subprocess.run(
            ["/bin/bash", "-c", script],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        detail = (e.stdout or "").strip() or "no output"
        raise SnapshotError(f"exit {e.returncode}: {detail}") from e


def create_snapshot(
    session_id: UUID,
    tenant_id: str,
    s3_bucket: str,
    snapshot_id: UUID,
) -> tuple[SnapshotCreateStatus, str]:
    """Create a snapshot of a session's outputs/attachments/.opencode-data.

    Returns:
        (status, storage_path). storage_path is empty when status is "empty".
    """
    session_path = SESSIONS_ROOT / str(session_id)
    if not (session_path / "outputs").is_dir():
        return ("empty", "")

    # Reject symlinks at the top level — the agent has rw access to the
    # session dir and could swap one of these for a symlink pointing at
    # /etc or the sidecar's IRSA token mount. GNU tar's default already
    # archives symlinks as symlinks (so the target isn't exfiltrated), but
    # we fail-loud here so the operator notices the tamper.
    for sub in ("outputs", "attachments", ".opencode-data"):
        candidate = session_path / sub
        if candidate.is_symlink():
            raise SnapshotError(f"{sub} is a symlink; refusing to snapshot")

    storage_path = f"{tenant_id}/snapshots/{session_id}/{snapshot_id}.tar.gz"
    s3_uri = f"s3://{s3_bucket}/{storage_path}"

    safe_session_path = shlex.quote(str(session_path))
    safe_s3_uri = shlex.quote(s3_uri)

    # node_modules + .next are excluded; restore_snapshot rebuilds them.
    # Including them would also break post-restore dedup since extracted
    # files get fresh inodes.
    #
    # Don't use `set -eo pipefail` for the pipeline — pipefail tears the
    # streams down before tar / s5cmd can flush diagnostics, so a failure
    # surfaces as exit-1-with-no-output. Inspect PIPESTATUS explicitly
    # instead and echo what each side returned before erroring out.
    script = f"""
set -e
cd {safe_session_path}
dirs="outputs"
if [ -d attachments ] && [ "$(ls -A attachments 2>/dev/null)" ]; then
    dirs="$dirs attachments"
fi
if [ -d .opencode-data ] && [ "$(ls -A .opencode-data 2>/dev/null)" ]; then
    dirs="$dirs .opencode-data"
fi

set +e
tar --exclude='outputs/web/node_modules' --exclude='outputs/web/.next' \\
    -czf - $dirs | s5cmd --log info pipe {safe_s3_uri}
tar_ec=${{PIPESTATUS[0]-0}}
s5_ec=${{PIPESTATUS[1]-0}}
set -e

if [ "$tar_ec" -ne 0 ] || [ "$s5_ec" -ne 0 ]; then
    echo "snapshot pipeline failed: tar=$tar_ec s5cmd=$s5_ec" >&2
    echo "  S3_ENDPOINT_URL=${{S3_ENDPOINT_URL-<unset>}}" >&2
    echo "  AWS_ENDPOINT_URL=${{AWS_ENDPOINT_URL-<unset>}}" >&2
    echo "  AWS_REGION=${{AWS_REGION-<unset>}}" >&2
    echo "  s3_uri={safe_s3_uri}" >&2
    exit 1
fi
"""

    _run(script)
    return ("created", storage_path)


def restore_snapshot(
    session_id: UUID,
    s3_bucket: str,
    storage_path: str,
) -> None:
    """Download snapshot from S3, extract, then bun-install to rebuild node_modules."""
    session_path = SESSIONS_ROOT / str(session_id)
    session_path.mkdir(parents=True, exist_ok=True)

    s3_uri = f"s3://{s3_bucket}/{storage_path}"
    safe_session_path = shlex.quote(str(session_path))
    safe_s3_uri = shlex.quote(s3_uri)

    # Keep in sync with docker_sandbox_manager.restore_snapshot's install.
    script = f"""
set -eo pipefail
s5cmd cat {safe_s3_uri} | tar -xzf - -C {safe_session_path}

web_dir={safe_session_path}/outputs/web
if [ -f "$web_dir/bun.lock" ]; then
    (
        flock -x 9
        if [ ! -f {BUN_CACHE_DIR}/.ready ]; then
            rm -rf {BUN_CACHE_DIR}
            cp -r {BUN_IMAGE_CACHE_DIR} {BUN_CACHE_DIR} \\
                || {{ echo "ERROR: bun cache bootstrap failed" >&2; exit 1; }}
            touch {BUN_CACHE_DIR}/.ready
        fi
    ) 9>{BUN_CACHE_DIR}.lock
    cd "$web_dir"
    BUN_INSTALL_CACHE_DIR={BUN_CACHE_DIR} \\
        bun install --frozen-lockfile --backend=hardlink
fi
"""

    _run(script)
