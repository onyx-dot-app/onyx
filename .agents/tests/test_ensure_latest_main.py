"""Unit tests for the latest-main hook (`.agents/hooks/ensure_latest_main.py`).

These run no git process and touch no files. The tests that run the hook against
real git repos live in
`.agents/tests/test_ensure_latest_main_repos.py`.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_HOOK = Path(__file__).resolve().parents[2] / ".agents/hooks/ensure_latest_main.py"
_REPO = Path("/nonexistent/repo")  # never read: `_git` is stubbed


def _load_hook() -> ModuleType:
    # The hook imports its sibling `agent_hook_io`, as it does when run as a script.
    if str(_HOOK.parent) not in sys.path:
        sys.path.insert(0, str(_HOOK.parent))
    spec = importlib.util.spec_from_file_location("ensure_latest_main", _HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ssh_command_extends_the_configured_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hook = _load_hook()
    configured: dict[str, str | None] = {"core.sshCommand": None}
    # No git process runs: `_git` answers the one `git config` lookup from a dict.
    monkeypatch.setattr(
        hook, "_git", lambda _repo, *args: configured.get(args[-1]), raising=True
    )
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.delenv("GIT_SSH", raising=False)
    batch = "-o BatchMode=yes -o ConnectTimeout=10"

    assert hook._ssh_env(_REPO) == {"GIT_SSH_COMMAND": f"ssh {batch}"}

    configured["core.sshCommand"] = "ssh -i /keys/work"
    assert hook._ssh_env(_REPO) == {"GIT_SSH_COMMAND": f"ssh -i /keys/work {batch}"}

    monkeypatch.setenv("GIT_SSH_COMMAND", "wrapper --flag")
    assert hook._ssh_env(_REPO) == {"GIT_SSH_COMMAND": f"wrapper --flag {batch}"}

    monkeypatch.delenv("GIT_SSH_COMMAND")
    monkeypatch.setenv("GIT_SSH", "/usr/local/bin/my-ssh")
    assert hook._ssh_env(_REPO) == {}
