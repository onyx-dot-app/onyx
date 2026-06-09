"""Init-container entrypoint: restore opencode's chat-history db from S3.

Runs to completion before any regular container starts (kubelet-ordered),
so opencode-serve can never open the store mid-restore. Exit codes:
0 = restored or nothing to restore (fresh sandbox); nonzero = failure,
which fails pod startup so provisioning retries instead of silently
starting with empty history.
"""

import os
import subprocess
import sys
import time
from uuid import UUID

from sandbox_daemon.snapshot import opencode_data_storage_path
from sandbox_daemon.snapshot import OPENCODE_DB_PATH

SQLITE_MAGIC = b"SQLite format 3\x00"

# This is the pod's first proxied egress: the egress proxy identifies pods
# by source IP from a K8s informer that may not have seen this pod yet, so
# early requests can 403 with "unidentified_sandbox". Retry until the
# proxy knows us.
_RETRY_BUDGET_SECONDS = 90
_RETRY_DELAY_SECONDS = 3
_ATTEMPT_TIMEOUT_SECONDS = 60


def _is_missing_object(stderr: str) -> bool:
    # s5cmd's "key does not exist" messages: `cat` on a plain key stats it
    # first ("given object ... not found"); list/wildcard paths say "no
    # object found".
    lowered = stderr.lower()
    if "no object found" in lowered:
        return True
    return "given object" in lowered and "not found" in lowered


def _download(s3_uri: str, dest: str) -> tuple[int, str]:
    with open(dest, "wb") as f:
        # Single-stream, small parts: the default 5x50MiB buffers could
        # blow the init container's memory limit.
        try:
            proc = subprocess.run(
                ["s5cmd", "cat", "--concurrency", "1", "--part-size", "16", s3_uri],
                stdout=f,
                stderr=subprocess.PIPE,
                text=False,
                timeout=_ATTEMPT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return 1, f"timed out after {_ATTEMPT_TIMEOUT_SECONDS}s"
    return proc.returncode, proc.stderr.decode(errors="replace").strip()


def main() -> int:
    sandbox_id = UUID(os.environ["ONYX_SANDBOX_ID"])
    tenant_id = os.environ["ONYX_TENANT_ID"]
    s3_bucket = os.environ["SANDBOX_S3_BUCKET"]
    s3_uri = f"s3://{s3_bucket}/{opencode_data_storage_path(tenant_id, sandbox_id)}"

    OPENCODE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = OPENCODE_DB_PATH.with_suffix(".db.restore")

    deadline = time.monotonic() + _RETRY_BUDGET_SECONDS
    while True:
        returncode, stderr = _download(s3_uri, str(tmp_path))
        if returncode == 0:
            break
        tmp_path.unlink(missing_ok=True)
        if _is_missing_object(stderr):
            print(f"[opencode-restore] no snapshot at {s3_uri}; starting fresh")
            return 0
        if time.monotonic() >= deadline:
            print(f"[opencode-restore] download failed: {stderr}", file=sys.stderr)
            return 1
        print(f"[opencode-restore] download failed, retrying: {stderr}")
        time.sleep(_RETRY_DELAY_SECONDS)

    with open(tmp_path, "rb") as f:
        magic = f.read(len(SQLITE_MAGIC))
    if magic != SQLITE_MAGIC:
        tmp_path.unlink(missing_ok=True)
        print(
            f"[opencode-restore] {s3_uri} is not a sqlite db; refusing",
            file=sys.stderr,
        )
        return 1

    tmp_path.rename(OPENCODE_DB_PATH)
    print(f"[opencode-restore] restored {OPENCODE_DB_PATH} from {s3_uri}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
