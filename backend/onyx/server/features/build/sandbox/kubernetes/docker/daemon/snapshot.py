"""Snapshot create/restore operations for the sandbox sidecar.

Shells out to the AWS CLI (already in the image) to upload/download tar.gz
archives to/from S3. Tarring/extraction happens via shell pipelines so we
don't buffer large snapshots in memory.
"""

import shlex
import subprocess
from pathlib import Path

SESSIONS_ROOT = Path("/workspace/sessions")


def create_snapshot(
    session_id: str,
    tenant_id: str,
    s3_bucket: str,
    snapshot_id: str,
) -> tuple[str, str]:
    """Create a snapshot of a session's outputs/attachments/.opencode-data.

    Returns:
        (status, storage_path) where status is "created" or "empty".
    """
    session_path = SESSIONS_ROOT / session_id
    if not (session_path / "outputs").is_dir():
        return ("empty", "")

    storage_path = f"{tenant_id}/snapshots/{session_id}/{snapshot_id}.tar.gz"
    s3_uri = f"s3://{s3_bucket}/{storage_path}"

    safe_session_path = shlex.quote(str(session_path))
    safe_s3_uri = shlex.quote(s3_uri)

    script = f"""
set -eo pipefail
cd {safe_session_path}
dirs="outputs"
[ -d attachments ] && [ "$(ls -A attachments 2>/dev/null)" ] && dirs="$dirs attachments"
[ -d .opencode-data ] && [ "$(ls -A .opencode-data 2>/dev/null)" ] && dirs="$dirs .opencode-data"
tar -czf - $dirs | aws s3 cp - {safe_s3_uri}
"""

    subprocess.run(["/bin/sh", "-c", script], check=True)
    return ("created", storage_path)


def restore_snapshot(
    session_id: str,
    s3_bucket: str,
    storage_path: str,
) -> None:
    """Download a snapshot from S3 and extract into the session directory."""
    session_path = SESSIONS_ROOT / session_id
    session_path.mkdir(parents=True, exist_ok=True)

    s3_uri = f"s3://{s3_bucket}/{storage_path}"
    safe_session_path = shlex.quote(str(session_path))
    safe_s3_uri = shlex.quote(s3_uri)

    script = f"""
set -eo pipefail
aws s3 cp {safe_s3_uri} - | tar -xzf - -C {safe_session_path}
"""

    subprocess.run(["/bin/sh", "-c", script], check=True)
