"""Exercise turn hooks with real Git repositories and a controlled pre-commit."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parents[4] / ".agents/hooks/pre_commit_on_stop.py"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, name: str, content: str = "new\n") -> None:
    (repo / name).write_text(content)
    _git(repo, "add", name)
    _git(repo, "commit", "-qm", f"Update {name}")


def _run(repo: Path, event: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        cwd=repo,
        input=json.dumps(
            {"cwd": str(repo), "session_id": "test", "hook_event_name": event}
        ),
        text=True,
        capture_output=True,
        timeout=30,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name, value in {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }.items():
        monkeypatch.setenv(name, value)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-qb", "main")
    _commit(repo, "base.txt")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "pre-commit"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['CHECKED_FILES']).write_text(json.dumps(sys.argv[3:]))\n"
        "if os.environ.get('REWRITE'):\n"
        "    Path(sys.argv[3]).write_text('formatted\\n')\n"
        "sys.exit(int(os.environ.get('CHECK_EXIT', '0')))\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CHECKED_FILES", str(tmp_path / "checked.json"))
    return repo


def _checked(repo: Path) -> set[str]:
    path = repo.parent / "checked.json"
    return set(json.loads(path.read_text())) if path.exists() else set()


def _start(repo: Path) -> None:
    assert _run(repo, "UserPromptSubmit").returncode == 0


def _stop(repo: Path) -> None:
    result = _run(repo, "Stop")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("operation", ["checkout", "merge", "rebase"])
def test_branch_updates_exclude_imported_files(repo: Path, operation: str) -> None:
    _git(repo, "checkout", "-qb", "upstream")
    _commit(repo, "upstream.txt")
    _git(repo, "checkout", "-q", "main")
    if operation == "rebase":
        _commit(repo, "old-local.txt")
    _start(repo)
    _git(repo, operation, "upstream")
    _commit(repo, "local.txt")
    _stop(repo)
    assert _checked(repo) == {"local.txt"}


def test_pull_excludes_upstream_lockfile(repo: Path, tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    _git(tmp_path, "clone", "-q", str(repo), str(remote))
    _commit(remote, "bun.lock")
    _start(repo)
    _git(repo, "pull", "--ff-only", str(remote), "main")
    _stop(repo)
    assert _checked(repo) == set()


def test_commit_before_rebase_is_still_checked(repo: Path) -> None:
    _git(repo, "checkout", "-qb", "upstream")
    _commit(repo, "upstream.txt")
    _git(repo, "checkout", "-q", "main")
    _start(repo)
    _commit(repo, "local.txt")
    _git(repo, "rebase", "upstream")
    _stop(repo)
    assert _checked(repo) == {"local.txt"}


def test_amend_checks_only_new_changes(repo: Path) -> None:
    _commit(repo, "old.txt")
    _start(repo)
    (repo / "new.txt").write_text("new")
    _git(repo, "add", "new.txt")
    _git(repo, "commit", "--amend", "--no-edit")
    _stop(repo)
    assert _checked(repo) == {"new.txt"}


def test_dirty_baseline_and_untracked_edits(repo: Path) -> None:
    (repo / "scratch.txt").write_text("keep")
    (repo / "base.txt").write_text("old edit")
    _start(repo)
    (repo / "base.txt").write_text("new edit")
    (repo / "new.txt").write_text("new")
    _stop(repo)
    assert _checked(repo) == {"base.txt", "new.txt"}


def test_expired_reflog_does_not_check_imported_files(repo: Path) -> None:
    _start(repo)
    _git(repo, "reflog", "expire", "--expire=all", "--all")
    (repo / "new.txt").write_text("new")
    _stop(repo)
    assert _checked(repo) == {"new.txt"}


def test_reminder_is_advisory(repo: Path) -> None:
    script = repo / ".agents/feature-map/stale_docs.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('Review feature documentation')\n")
    _git(repo, "add", ".agents")
    _git(repo, "commit", "-qm", "Add reminder")
    _start(repo)
    (repo / "base.txt").write_text("edit")
    result = _run(repo, "Stop")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "systemMessage": "Review feature documentation"
    }
    assert result.stderr == ""


@pytest.mark.parametrize("failure", ["CHECK_EXIT", "REWRITE"])
def test_failures_and_rewrites_still_block(
    repo: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    _start(repo)
    (repo / "base.txt").write_text("edit")
    monkeypatch.setenv(failure, "1")
    result = _run(repo, "Stop")
    assert result.returncode == 2
    assert "pre-commit failed" in result.stderr


@pytest.mark.parametrize("operation", ["cherry-pick", "revert"])
def test_explicit_commit_operations_are_checked(repo: Path, operation: str) -> None:
    _git(repo, "checkout", "-qb", "topic")
    _commit(repo, "base.txt", "topic edit\n")
    commit = _git(repo, "rev-parse", "HEAD")
    if operation == "cherry-pick":
        _git(repo, "checkout", "-q", "main")
    _start(repo)
    _git(repo, operation, "--no-edit", commit)
    _stop(repo)
    assert _checked(repo) == {"base.txt"}


def test_linked_worktree_uses_its_own_reflog(repo: Path) -> None:
    linked = repo.parent / "linked"
    _git(repo, "worktree", "add", "-b", "linked", str(linked))
    _start(linked)
    _commit(repo, "other-worktree.txt")
    _commit(linked, "local.txt")
    _stop(linked)
    assert _checked(linked) == {"local.txt"}
