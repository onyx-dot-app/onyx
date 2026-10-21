"""External dependency tests for the agent-context bootstrap hook
(`.agents/hooks/bootstrap_agent_context.py`).

These need a real `git` binary and the filesystem, not Onyx services. The hook runs
against throwaway checkouts and a local stand-in for the context repo: it is
silent once the context's hooks are registered, points the agent at a context on
disk, clones a missing one for Onyx staff at most once a week, and stays silent
for everyone else."""

import json
import os
import subprocess
import sys
from pathlib import Path

_HOOK = Path(__file__).resolve().parents[4] / ".agents/hooks/bootstrap_agent_context.py"
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "ONYX_AGENT_CONTEXT": "",
    "ONYX_SKIP_AGENT_CONTEXT_BOOTSTRAP": "",
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _setup(
    tmp_path: Path, email: str = "someone@onyx.app"
) -> tuple[Path, dict[str, str]]:
    """An onyx checkout in a workspace folder, a context remote, and a fake home."""
    remote = tmp_path / "remote" / "onyx-agent-context"
    remote.mkdir(parents=True)
    _git(remote, "init", "-q", "-b", "main")
    (remote / "AGENTS.md").write_text("entry\n")
    _git(remote, "add", "-A")
    _git(remote, "commit", "-q", "-m", "init")
    onyx = tmp_path / "ws" / "onyx"
    onyx.mkdir(parents=True)
    _git(onyx, "init", "-q", "-b", "main")
    _git(onyx, "commit", "-q", "--allow-empty", "-m", "init")
    _git(onyx, "config", "user.email", email)
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "ONYX_AGENT_CONTEXT_URL": str(remote)}
    return onyx, env


def _run(repo: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps({"cwd": str(repo), "hook_event_name": "SessionStart"}),
        cwd=repo,
        env={**_GIT_ENV, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_clones_a_missing_context_for_staff_next_to_the_main_checkout(
    tmp_path: Path,
) -> None:
    onyx, env = _setup(tmp_path)
    worktree = tmp_path / "ws" / "worktrees" / "feature"
    _git(onyx, "worktree", "add", "-q", str(worktree))

    out = _run(worktree, env)

    clone = tmp_path / "ws" / "onyx-agent-context"
    assert (clone / "AGENTS.md").is_file()
    assert "Cloned `onyx-agent-context` for you." in out
    assert f"`{clone}`" in out
    assert "agent-context-setup" in out


def test_points_at_a_context_already_on_disk(tmp_path: Path) -> None:
    onyx, env = _setup(tmp_path, email="someone@example.com")
    context = tmp_path / "ws" / "onyx-agent-context"
    context.mkdir()
    (context / "AGENTS.md").write_text("entry\n")

    out = _run(onyx, env)

    assert f"`{context}`" in out
    assert "Cloned" not in out


def test_is_silent_once_the_context_hooks_are_registered(tmp_path: Path) -> None:
    onyx, env = _setup(tmp_path)
    settings = Path(env["HOME"]) / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps({"statusMessage": "Onyx agent context: load the context"})
    )

    assert _run(onyx, env) == ""
    assert not (tmp_path / "ws" / "onyx-agent-context").exists()


def test_never_clones_for_other_emails(tmp_path: Path) -> None:
    onyx, env = _setup(tmp_path, email="someone@example.com")

    assert _run(onyx, env) == ""
    assert not (tmp_path / "ws" / "onyx-agent-context").exists()


def test_reports_a_failed_clone_once_a_week(tmp_path: Path) -> None:
    onyx, env = _setup(tmp_path)
    env["ONYX_AGENT_CONTEXT_URL"] = str(tmp_path / "missing")

    assert "Could not clone" in _run(onyx, env)
    assert _run(onyx, env) == ""


def test_can_be_turned_off(tmp_path: Path) -> None:
    onyx, env = _setup(tmp_path)

    assert _run(onyx, {**env, "ONYX_SKIP_AGENT_CONTEXT_BOOTSTRAP": "1"}) == ""
    assert not (tmp_path / "ws" / "onyx-agent-context").exists()


def test_answers_cursor_with_json_and_reads_its_workspace_root(tmp_path: Path) -> None:
    onyx, env = _setup(tmp_path, email="someone@example.com")
    context = tmp_path / "ws" / "onyx-agent-context"
    context.mkdir()
    (context / "AGENTS.md").write_text("entry\n")
    payload = {
        "hook_event_name": "sessionStart",
        "cursor_version": "2.0.0",
        "workspace_roots": [str(onyx)],
    }

    result = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        cwd=tmp_path,
        env={**_GIT_ENV, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert f"`{context}`" in json.loads(result.stdout)["additional_context"]
