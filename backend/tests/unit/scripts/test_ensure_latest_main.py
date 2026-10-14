"""The latest-main hook (`.agents/hooks/ensure_latest_main.py`) runs against
throwaway git repos: it reports the state of a branch at session start, stays quiet
on later prompts unless the branch is behind, fetches at most once an hour on
prompts, never changes the working tree, and always exits 0."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parents[4] / ".agents/hooks/ensure_latest_main.py"
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
_STAMP = "onyx-main-sync-check"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _commit(repo: Path, name: str, content: str = "x\n") -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")


def _run(
    repo: Path, event: str | None = None, **env: str
) -> subprocess.CompletedProcess[str]:
    payload: dict[str, str] = {"cwd": str(repo)}
    if event:
        payload["hook_event_name"] = event
    result = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        env={**_GIT_ENV, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    return result


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare `origin` with one commit on main, plus a clone that pushes to it."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    _git(seed, "checkout", "-q", "-b", "main")
    _commit(seed, "a.txt")
    _git(seed, "push", "-q", "origin", "main")
    return seed


@pytest.fixture
def checkout(remote: Path) -> Path:
    """A clone of origin that is up to date."""
    path = remote.parent / "checkout"
    _git(remote.parent, "clone", "-q", str(remote.parent / "origin.git"), str(path))
    return path


def _push_new_commit(remote: Path, name: str = "b.txt") -> None:
    _commit(remote, name)
    _git(remote, "push", "-q", "origin", "main")


def _stamp(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--absolute-git-dir")) / _STAMP


def _age_stamp(repo: Path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(_stamp(repo), (then, then))


def test_session_start_up_to_date_says_so(checkout: Path) -> None:
    out = _run(checkout, "SessionStart").stdout
    assert "includes the latest origin/main" in out


def test_session_start_on_main_behind_says_to_pull(
    checkout: Path, remote: Path
) -> None:
    _push_new_commit(remote)
    out = _run(checkout, "SessionStart").stdout
    assert "`main` is 1 commit behind origin/main" in out
    assert "git pull --ff-only origin main" in out


def test_session_start_on_branch_behind_says_to_rebase_and_lists_agent_files(
    checkout: Path, remote: Path
) -> None:
    _git(checkout, "checkout", "-q", "-b", "feat")
    _commit(checkout, "feat.txt")
    _commit(remote, ".agents/feature-map/x.md")
    _push_new_commit(remote, "c.txt")
    out = _run(checkout, "SessionStart").stdout
    assert "`feat` is 2 commits behind origin/main" in out
    assert ".agents/feature-map/x.md" in out
    assert "git rebase origin/main" in out


def test_hook_never_changes_the_working_tree(checkout: Path, remote: Path) -> None:
    _git(checkout, "checkout", "-q", "-b", "feat")
    _commit(checkout, "feat.txt")
    (checkout / "a.txt").write_text("local edit\n")
    (checkout / "scratch.txt").write_text("untracked\n")
    _push_new_commit(remote)
    head = _git(checkout, "rev-parse", "HEAD")

    out = _run(checkout, "SessionStart").stdout

    assert "uncommitted changes" in out
    assert _git(checkout, "rev-parse", "HEAD") == head
    assert _git(checkout, "branch", "--show-current") == "feat"
    assert (checkout / "a.txt").read_text() == "local edit\n"
    assert (checkout / "scratch.txt").read_text() == "untracked\n"


def test_session_start_offline_reports_against_last_known_main(
    checkout: Path, remote: Path
) -> None:
    _push_new_commit(remote)
    _git(checkout, "fetch", "-q", "origin", "main")
    _git(checkout, "remote", "set-url", "origin", str(checkout / "missing.git"))
    out = _run(checkout, "SessionStart").stdout
    assert "Could not fetch origin/main" in out
    assert "`main` is 1 commit behind origin/main" in out


def test_session_start_offline_and_current_notes_the_failed_fetch(
    checkout: Path,
) -> None:
    _git(checkout, "remote", "set-url", "origin", str(checkout / "missing.git"))
    out = _run(checkout, "SessionStart").stdout
    assert "Could not fetch origin/main" in out
    assert "No newer commits known" in out


def test_no_event_is_treated_as_session_start(checkout: Path) -> None:
    assert "includes the latest origin/main" in _run(checkout).stdout


def test_skip_variable_silences_the_hook(checkout: Path, remote: Path) -> None:
    _push_new_commit(remote)
    assert _run(checkout, "SessionStart", ONYX_SKIP_MAIN_SYNC_CHECK="1").stdout == ""


def test_outside_a_repository_is_silent(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert (
        _run(plain, "SessionStart", GIT_CEILING_DIRECTORIES=str(tmp_path)).stdout == ""
    )


def test_repository_without_origin_is_silent(tmp_path: Path) -> None:
    repo = tmp_path / "solo"
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _commit(repo, "a.txt")
    assert _run(repo, "SessionStart").stdout == ""


def test_prompt_is_silent_when_not_behind(checkout: Path) -> None:
    assert _run(checkout, "UserPromptSubmit").stdout == ""


def test_prompt_reports_when_behind_and_fetch_is_due(
    checkout: Path, remote: Path
) -> None:
    _push_new_commit(remote)
    out = _run(checkout, "UserPromptSubmit").stdout
    assert "`main` is 1 commit behind origin/main" in out
    assert "Could not fetch" not in out


def test_prompt_fetches_at_most_once_an_hour(checkout: Path, remote: Path) -> None:
    assert _run(checkout, "UserPromptSubmit").stdout == ""
    assert _stamp(checkout).exists()

    # A fetch within the hour would see this commit.
    _push_new_commit(remote)
    assert _run(checkout, "UserPromptSubmit").stdout == ""

    _age_stamp(checkout, 2 * 60 * 60)
    assert "1 commit behind" in _run(checkout, "UserPromptSubmit").stdout
    assert time.time() - _stamp(checkout).stat().st_mtime < 60


def test_prompt_uses_the_cached_main_between_fetches(
    checkout: Path, remote: Path
) -> None:
    _push_new_commit(remote)
    _git(checkout, "fetch", "-q", "origin", "main")
    _stamp(checkout).touch()
    assert "1 commit behind" in _run(checkout, "UserPromptSubmit").stdout


def test_session_start_counts_as_a_fetch_for_the_throttle(
    checkout: Path, remote: Path
) -> None:
    _run(checkout, "SessionStart")
    _push_new_commit(remote)
    assert _run(checkout, "UserPromptSubmit").stdout == ""


def test_prompt_offline_tries_once_and_stays_silent(checkout: Path) -> None:
    _git(checkout, "remote", "set-url", "origin", str(checkout / "missing.git"))
    _stamp(checkout).touch()
    _age_stamp(checkout, 2 * 60 * 60)

    assert _run(checkout, "UserPromptSubmit").stdout == ""
    # The failed attempt still counts, so the next prompt does not retry.
    assert time.time() - _stamp(checkout).stat().st_mtime < 60
