"""Privilege boundary shared by startup and exec operations."""

import os
from collections.abc import Sequence

GUEST_PYTHON = "/opt/onyx-guest/venv/bin/python"
SETPRIV = "/usr/bin/setpriv"


def user_command(command: Sequence[str]) -> list[str]:
    return [
        SETPRIV,
        "--reuid=1000",
        "--regid=1000",
        "--clear-groups",
        "--inh-caps=-all",
        "--ambient-caps=-all",
        "--bounding-set=-all",
        "--no-new-privs",
        "--",
        *command,
    ]


def user_environment() -> dict[str, str]:
    return {
        **os.environ,
        "HOME": "/home/sandbox",
        "USER": "sandbox",
        "LOGNAME": "sandbox",
        "TMPDIR": "/tmp",  # noqa: S108 -- guest-local user scratch directory
        "XDG_DATA_HOME": "/workspace/opencode-data",
        "OPENCODE_DATA_HOME": "/workspace/opencode-data",
    }


def require_root() -> None:
    if os.getuid() != 0 or os.geteuid() != 0:
        raise PermissionError("operation requires root")


def drop_to_user(operation: str, metadata: str) -> None:
    if os.getuid() == 0:
        os.execve(  # noqa: S606 -- absolute privilege-drop executable
            SETPRIV,
            user_command([GUEST_PYTHON, "-I", "-m", "onyx_guest", operation, metadata]),
            user_environment(),
        )
    if os.getuid() != 1000 or os.geteuid() != 1000:
        raise PermissionError("operation requires sandbox UID 1000")
