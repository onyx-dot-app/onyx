"""Root bootstrap and OpenCode startup after the history gate opens."""

import fcntl
import os
import signal
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import MAX_HISTORY_ARCHIVE_BYTES
from .input import FramedInput
from .security import GUEST_PYTHON, require_root, user_command, user_environment

STATE_ROOT = Path("/run/onyx")
BOOTSTRAP_READY = STATE_ROOT / "bootstrap-ready"
HISTORY_RESTORED = STATE_ROOT / "history-restored"
HISTORY_LOCK = STATE_ROOT / "history.lock"


@contextmanager
def history_lock() -> Iterator[None]:
    require_root()
    with HISTORY_LOCK.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def release_history(*, restore: bool, source: FramedInput, deadline: float) -> None:
    with history_lock():
        if restore and HISTORY_RESTORED.exists():
            for _chunk in source.chunks(max_bytes=MAX_HISTORY_ARCHIVE_BYTES):
                pass
        elif restore:
            if time.monotonic() >= deadline:
                raise TimeoutError("guest history restore timed out")
            process: subprocess.Popen[bytes] | None = None
            # An alarm between spawn and transfer would give stdin two owners.
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
            try:
                signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
                process = subprocess.Popen(
                    user_command(
                        [
                            GUEST_PYTHON,
                            "-I",
                            "-m",
                            "onyx_guest",
                            "_restore-history",
                            "{}",
                        ]
                    ),
                    stdin=source.source,
                    env=user_environment(),
                    start_new_session=True,
                )
                source.transfer()
                returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except BaseException:
                if process is not None:
                    # The root helper lacks CAP_KILL; signal as the child's UID.
                    os.seteuid(1000)
                    try:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    finally:
                        os.seteuid(0)
                    process.wait()
                raise
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            if returncode != 0:
                raise subprocess.CalledProcessError(returncode, process.args)
        else:
            source.require_empty()
        HISTORY_RESTORED.touch(mode=0o600, exist_ok=True)


def _prepare_directories() -> None:
    for name in ("/workspace", "/workspace/managed", str(STATE_ROOT)):
        path = Path(name)
        if path.is_symlink():
            raise RuntimeError(f"trusted directory is a symlink: {name}")
        path.mkdir(parents=True, exist_ok=True)
        os.chown(path, 0, 0)
        path.chmod(0o700 if path == STATE_ROOT else 0o755)
    for name in (
        "/workspace/sessions",
        "/workspace/opencode-data",
        "/home/sandbox",
        "/tmp",  # noqa: S108 -- guest-local user scratch directory
    ):
        path = Path(name)
        if path.is_symlink():
            raise RuntimeError(f"mutable directory is a symlink: {name}")
        path.mkdir(parents=True, exist_ok=True)
        os.chown(path, 1000, 1000)


def serve() -> None:
    require_root()

    def stop(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    _prepare_directories()
    BOOTSTRAP_READY.unlink(missing_ok=True)
    subprocess.run(
        ["/bin/bash", "/opt/onyx-guest/firewall-init.sh", "ca"],
        stdin=subprocess.DEVNULL,
        env={
            **os.environ,
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        },
        check=True,
    )
    BOOTSTRAP_READY.touch(mode=0o600)
    while not HISTORY_RESTORED.is_file():
        time.sleep(0.1)
    os.execve(  # noqa: S606 -- absolute privilege-drop executable
        "/usr/bin/setpriv",
        user_command([GUEST_PYTHON, "-I", "-m", "onyx_guest", "serve-user", "{}"]),
        user_environment(),
    )


def serve_user() -> None:
    child = subprocess.Popen(
        ["/bin/bash", "/opt/onyx-guest/entrypoint.sh"],
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    def forward_signal(signum: int, _frame: object) -> None:
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, forward_signal)
    signal.signal(signal.SIGINT, forward_signal)
    while True:
        try:
            pid, status = os.waitpid(-1, 0)
        except ChildProcessError:
            return
        if pid == child.pid:
            child.returncode = os.waitstatus_to_exitcode(status)
            raise SystemExit(
                child.returncode if child.returncode >= 0 else 128 - child.returncode
            )
