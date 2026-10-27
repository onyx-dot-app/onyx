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


_CONFLICT_COMMANDS = {
    "cherry-pick": ["cherry-pick", "upstream"],
    "merge": ["merge", "upstream"],
    "rebase": ["rebase", "upstream"],
    "rebase-with-commit": ["rebase", "upstream"],
    "rebase-apply": ["rebase", "--apply", "upstream"],
    "pull-rebase": ["pull", "--rebase", ".", "upstream"],
}


def _conflict(repo: Path, operation: str) -> None:
    result = subprocess.run(
        ["git", *_CONFLICT_COMMANDS[operation]],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, result.stdout


def _resolve(repo: Path, operation: str) -> None:
    (repo / "base.txt").write_text("resolved\n")
    _git(repo, "add", "base.txt")
    if operation in ("merge", "rebase-with-commit"):
        _git(repo, "commit", "-q", "--no-edit")
    if operation == "rebase-without-finish":
        subprocess.run(
            ["git", "-c", "core.editor=true", "rebase", "--continue"],
            cwd=repo,
            capture_output=True,
        )
    elif operation != "merge":
        command = "cherry-pick" if operation == "cherry-pick" else "rebase"
        _git(repo, "-c", "core.editor=true", command, "--continue")


def _diverge(repo: Path) -> None:
    _git(repo, "checkout", "-qb", "upstream")
    _commit(repo, "upstream.txt")
    _commit(repo, "base.txt", "upstream edit\n")
    _git(repo, "checkout", "-q", "main")


@pytest.mark.parametrize("operation", list(_CONFLICT_COMMANDS))
def test_only_conflict_resolutions_are_checked(repo: Path, operation: str) -> None:
    _diverge(repo)
    (repo / "local.txt").write_text("local\n")
    _git(repo, "add", "local.txt")
    _commit(repo, "base.txt", "local edit\n")
    _start(repo)
    _conflict(repo, operation)
    _resolve(repo, operation)
    _stop(repo)
    assert _checked(repo) == {"base.txt"}


def test_rebase_pairs_repeated_subjects_in_order(repo: Path) -> None:
    _diverge(repo)
    (repo / "base.txt").write_text("local edit\n")
    _git(repo, "commit", "-qam", "Same subject")
    (repo / "local.txt").write_text("local\n")
    _git(repo, "add", "local.txt")
    _git(repo, "commit", "-qm", "Same subject")
    _start(repo)
    _conflict(repo, "rebase")
    _resolve(repo, "rebase")
    _stop(repo)
    assert _checked(repo) == {"base.txt"}


def test_clean_autosquash_checks_nothing(repo: Path) -> None:
    _commit(repo, "local.txt")
    _commit(repo, "other.txt")
    (repo / "local.txt").write_text("fixed\n")
    _git(repo, "commit", "-qam", "fixup! Update local.txt")
    _start(repo)
    _git(
        repo,
        "-c",
        "sequence.editor=true",
        "rebase",
        "-qi",
        "--autosquash",
        "HEAD~3",
    )
    _stop(repo)
    assert _checked(repo) == set()


def test_rebase_onto_checks_only_replayed_commits(repo: Path) -> None:
    _git(repo, "checkout", "-qb", "upstream")
    _commit(repo, "upstream.txt")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "base.txt", "skipped\n")
    _commit(repo, "local.txt")
    _start(repo)
    _git(repo, "rebase", "-q", "--onto", "upstream", "HEAD~1")
    _stop(repo)
    assert _checked(repo) == set()


def test_rebase_skips_patch_already_upstream(repo: Path) -> None:
    _git(repo, "checkout", "-qb", "upstream")
    _commit(repo, "base.txt", "shared\n")
    _git(repo, "checkout", "-q", "main")
    (repo / "base.txt").write_text("shared\n")
    _git(repo, "commit", "-qam", "Local copy of the upstream change")
    _commit(repo, "base.txt", "local\n")
    _start(repo)
    _git(repo, "rebase", "-q", "upstream")
    _stop(repo)
    assert _checked(repo) == set()


def test_unfinished_rebase_checks_commits_from_the_turn(repo: Path) -> None:
    _commit(repo, "local.txt")
    _start(repo)
    _git(
        repo,
        "-c",
        "sequence.editor=sed -i.bak s/^pick/edit/",
        "rebase",
        "-qi",
        "HEAD~1",
    )
    _commit(repo, "new.txt")
    _stop(repo)
    assert _checked(repo) == {"new.txt"}


def test_rebase_across_turns_checks_each_turn_once(repo: Path) -> None:
    _git(repo, "checkout", "-qb", "upstream")
    _commit(repo, "base.txt", "upstream edit\n")
    _commit(repo, "other.txt", "upstream edit\n")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "base.txt", "local edit\n")
    _commit(repo, "other.txt", "local edit\n")
    _start(repo)
    _conflict(repo, "rebase")
    _resolve(repo, "rebase-without-finish")
    _stop(repo)
    assert "base.txt" in _checked(repo)
    _start(repo)
    (repo / "other.txt").write_text("resolved\n")
    _git(repo, "add", "other.txt")
    _git(repo, "-c", "core.editor=true", "rebase", "--continue")
    _stop(repo)
    assert _checked(repo) == {"other.txt"}


def test_quit_rebase_does_not_hide_later_commits(repo: Path) -> None:
    _diverge(repo)
    _commit(repo, "base.txt", "local edit\n")
    _conflict(repo, "rebase")
    _git(repo, "rebase", "--quit")
    _git(repo, "reset", "-q", "--hard")
    _start(repo)
    _commit(repo, "new.txt")
    _stop(repo)
    assert _checked(repo) == {"new.txt"}


def test_unrelated_history_merge_checks_only_resolutions(repo: Path) -> None:
    _git(repo, "checkout", "-q", "--orphan", "unrelated")
    _git(repo, "rm", "-rfq", ".")
    _commit(repo, "imported.txt")
    _git(repo, "checkout", "-q", "main")
    _start(repo)
    _git(repo, "merge", "-q", "--no-commit", "--allow-unrelated-histories", "unrelated")
    _git(repo, "commit", "-q", "--no-edit")
    _stop(repo)
    assert _checked(repo) == set()


def test_octopus_merge_checks_edits_from_the_turn(repo: Path) -> None:
    for branch in ("one", "two"):
        _git(repo, "checkout", "-qb", branch, "main")
        _commit(repo, f"{branch}.txt")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main.txt")
    _start(repo)
    _git(repo, "merge", "-q", "--no-commit", "one", "two")
    _commit(repo, "base.txt", "edit\n")
    _stop(repo)
    assert _checked(repo) == {"base.txt"}


def test_clean_octopus_merge_checks_nothing(repo: Path) -> None:
    _commit(repo, "base.txt", "".join(f"{line}\n" for line in range(20)))
    for branch, line in (("one", 1), ("two", 18)):
        _git(repo, "checkout", "-qb", branch, "main")
        lines = (repo / "base.txt").read_text().splitlines()
        lines[line] = branch
        _commit(repo, "base.txt", "\n".join(lines) + "\n")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main.txt")
    _start(repo)
    _git(repo, "merge", "-q", "--no-commit", "one", "two")
    _git(repo, "commit", "-q", "--no-edit")
    _stop(repo)
    assert _checked(repo) == set()


def test_rebase_merges_checks_nothing_when_clean(repo: Path) -> None:
    _diverge(repo)
    _git(repo, "checkout", "-qb", "topic", "main")
    _commit(repo, "topic.txt")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "local.txt")
    _git(repo, "merge", "-q", "--no-ff", "--no-edit", "topic")
    _start(repo)
    _git(repo, "rebase", "-q", "--rebase-merges", "upstream")
    _stop(repo)
    assert _checked(repo) == set()


def test_rebase_resolution_keeping_upstream_checks_resolved_file(repo: Path) -> None:
    _diverge(repo)
    (repo / "local.txt").write_text("local\n")
    _git(repo, "add", "local.txt")
    _commit(repo, "base.txt", "local edit\n")
    _start(repo)
    _conflict(repo, "rebase")
    _git(repo, "checkout", "-q", "--ours", "base.txt")
    _git(repo, "add", "base.txt")
    _git(repo, "-c", "core.editor=true", "rebase", "--continue")
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
