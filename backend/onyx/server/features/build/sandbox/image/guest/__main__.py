"""Binary stdin/stdout command protocol for Kata guest exec."""

import json
import os
import signal
import sys
import time

from . import PROTOCOL_VERSION
from .input import FramedInput
from .security import drop_to_user, require_root
from .supervisor import (
    BOOTSTRAP_READY,
    HISTORY_RESTORED,
    STATE_ROOT,
    release_history,
    serve,
    serve_user,
)

ROOT_OPERATIONS = frozenset(
    {"status", "serve", "push-managed", "restore-history", "release-history"}
)
INPUT_OPERATIONS = frozenset(
    {
        "upload-file",
        "write-file",
        "restore-snapshot",
        "_restore-history",
    }
)


def timeout_handler(_signum: int, _frame: object) -> None:
    raise TimeoutError("guest operation timed out")


def _validate_metadata(operation: str, metadata: str) -> None:
    if len(metadata.encode("utf-8")) > 64 * 1024:
        raise ValueError("guest operation metadata exceeds 64 KiB limit")
    if operation in ROOT_OPERATIONS - {"push-managed"} or operation == "serve-user":
        bootstrap_metadata = json.loads(metadata)
        if not isinstance(bootstrap_metadata, dict) or bootstrap_metadata != {}:
            raise ValueError("operation metadata must be an empty JSON object")


def main(source: FramedInput | None = None) -> None:
    if len(sys.argv) != 3:
        raise ValueError("usage: onyx_guest OPERATION METADATA_JSON")
    operation, metadata = sys.argv[1:]
    if operation not in ROOT_OPERATIONS:
        drop_to_user(operation, metadata)
    else:
        require_root()
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGALRM})
    service = operation in {"serve", "serve-user"}
    if source is None and not service:
        source = FramedInput(os.fdopen(0, "rb", buffering=0, closefd=False))
    try:
        signal.signal(signal.SIGALRM, timeout_handler)
        started = time.monotonic()
        watchdog_seconds = (
            3611
            if operation == "run"
            else 316
            if operation == "restore-history"
            else 301
        )
        if not service:
            signal.alarm(watchdog_seconds)
        _validate_metadata(operation, metadata)
        if operation == "serve":
            serve()
            return
        if operation == "serve-user":
            serve_user()
            return
        if source is None:
            raise RuntimeError("guest operation input is not available")
        if operation == "status":
            source.require_empty()
            response: object = {
                "protocol": PROTOCOL_VERSION,
                "ready": BOOTSTRAP_READY.is_file(),
                "history_restored": HISTORY_RESTORED.is_file(),
            }
        elif operation in {"restore-history", "release-history"}:
            release_history(
                restore=operation == "restore-history",
                source=source,
                deadline=started + watchdog_seconds,
            )
            response = {"status": "ok"}
        elif operation == "push-managed":
            import fcntl

            # Only managed pushes need the root archive and request imports.
            from .extract import MAX_BUNDLE_BYTES, safe_extract_then_atomic_swap
            from .models import ManagedRequest

            request = ManagedRequest.model_validate_json(metadata)
            body = b"".join(source.chunks(max_bytes=MAX_BUNDLE_BYTES))
            with (STATE_ROOT / "managed.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                safe_extract_then_atomic_swap(body, request.mount_path)
            response = {"status": "ok"}
        else:
            import tempfile
            from pathlib import Path

            # User request and archive imports must follow the setpriv boundary.
            from .models import MAX_HISTORY_ARCHIVE_BYTES, RunRequest

            run_request = (
                RunRequest.model_validate_json(metadata) if operation == "run" else None
            )
            run_deadline = (
                started + run_request.timeout_seconds
                if run_request is not None
                else None
            )
            if run_deadline is not None:
                remaining = run_deadline + 11 - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("guest operation timed out")
                signal.setitimer(signal.ITIMER_REAL, remaining)
            from .operations import MAX_INPUT_BYTES, execute, run, spool_stdin

            with tempfile.NamedTemporaryFile(
                prefix="onyx-guest-", suffix=".input"
            ) as spool:
                if operation in INPUT_OPERATIONS or (
                    run_request is not None and run_request.has_stdin
                ):
                    spool_stdin(
                        source,
                        spool.file,
                        max_bytes=MAX_HISTORY_ARCHIVE_BYTES
                        if operation == "_restore-history"
                        else MAX_INPUT_BYTES,
                    )
                else:
                    source.require_empty()
                if run_request is not None and run_deadline is not None:
                    try:
                        raise SystemExit(
                            run(run_request, spool.file, deadline=run_deadline)
                        )
                    finally:
                        signal.setitimer(signal.ITIMER_REAL, 0)
                response = execute(operation, metadata, spool.file, Path(spool.name))
        if response is not None:
            print(json.dumps(response, separators=(",", ":")))
    except Exception:
        if source is not None and not service:
            try:
                source.drain_after_error()
            except Exception:
                pass
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"{type(error).__name__}: {error}"[: 16 * 1024], file=sys.stderr)
        raise SystemExit(1) from None
