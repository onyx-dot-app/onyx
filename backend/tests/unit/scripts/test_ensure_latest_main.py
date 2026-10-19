"""The latest-main hook (`.agents/hooks/ensure_latest_main.py`) runs against
throwaway git repos: it tells the agent to rebase only when the branch conflicts with
origin/main or is stale (merge base more than 3 days old) and is silent otherwise,
fetches at most once an hour on prompts, never changes the working tree, and always
exits 0."""

import importlib.util
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
# The hook's limit is 3 days (`_STALE_AFTER_DAYS`); these sit either side of it.
_PAST_LIMIT_DAYS = 4
_WITHIN_LIMIT_DAYS = 2


def _git(cwd: Path, *args: str, **env: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**_GIT_ENV, **env},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _commit(
    repo: Path,
    name: str,
    content: str = "x\n",
    age_days: float = 0,
) -> None:
    """Commit `name`, dated `age_days` ago (the date the hook's staleness uses)."""
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    when = f"{int(time.time() - age_days * 24 * 60 * 60)} +0000"
    _git(repo, "add", name)
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        f"add {name}",
        GIT_AUTHOR_DATE=when,
        GIT_COMMITTER_DATE=when,
    )


def _run(
    repo: Path, event: str | None = None, **env: str
) -> subprocess.CompletedProcess[str]:
    payload: dict[str, str] = {"cwd": str(repo)}
    if event:
        payload["hook_event_name"] = event
    return _run_raw(repo, json.dumps(payload), **env)


def _run_raw(repo: Path, stdin: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run the hook with `stdin` as its payload, from `repo` as the cwd."""
    result = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=stdin,
        cwd=repo,
        env={**_GIT_ENV, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    return result


def _make_remote(tmp_path: Path, age_days: float) -> Path:
    """A bare `origin` with one commit on main, plus a clone that pushes to it."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    _git(seed, "checkout", "-q", "-b", "main")
    _commit(seed, "a.txt", age_days=age_days)
    _git(seed, "push", "-q", "origin", "main")
    return seed


def _make_checkout(remote: Path) -> Path:
    path = remote.parent / "checkout"
    _git(remote.parent, "clone", "-q", str(remote.parent / "origin.git"), str(path))
    return path


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """origin whose main was last committed to just now."""
    return _make_remote(tmp_path, age_days=0)


@pytest.fixture
def checkout(remote: Path) -> Path:
    """A clone of origin that is up to date."""
    return _make_checkout(remote)


@pytest.fixture
def stale_remote(tmp_path: Path) -> Path:
    """origin whose first main commit is 4 days old (past the 3-day limit)."""
    return _make_remote(tmp_path, age_days=_PAST_LIMIT_DAYS)


@pytest.fixture
def stale_checkout(stale_remote: Path) -> Path:
    """A clone of `stale_remote`, up to date but with an old merge base once it diverges."""
    return _make_checkout(stale_remote)


def _push_new_commit(remote: Path, name: str = "b.txt") -> None:
    _commit(remote, name)
    _git(remote, "push", "-q", "origin", "main")


def _make_conflict(checkout: Path, remote: Path) -> None:
    """`feat` and origin/main both rewrite a.txt, so merging them conflicts."""
    _git(checkout, "checkout", "-q", "-b", "feat")
    _commit(checkout, "a.txt", "feat\n")
    _commit(remote, "a.txt", "main\n")
    _git(remote, "push", "-q", "origin", "main")


def _stamp(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--absolute-git-dir")) / _STAMP


def _age_stamp(repo: Path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(_stamp(repo), (then, then))


def test_up_to_date_is_silent(checkout: Path) -> None:
    assert _run(checkout, "SessionStart").stdout == ""


def test_up_to_date_with_an_old_main_is_silent(stale_checkout: Path) -> None:
    # Main has been quiet for 4 days, but the branch contains all of it.
    _git(stale_checkout, "checkout", "-q", "-b", "feat")
    _commit(stale_checkout, "feat.txt")
    assert _run(stale_checkout, "SessionStart").stdout == ""


def test_fresh_and_clean_behind_main_is_silent(checkout: Path, remote: Path) -> None:
    _push_new_commit(remote)
    assert _run(checkout, "SessionStart").stdout == ""


def test_fresh_and_clean_branch_behind_main_is_silent(
    checkout: Path, remote: Path
) -> None:
    _git(checkout, "checkout", "-q", "-b", "feat")
    _commit(checkout, "feat.txt")
    _push_new_commit(remote)
    assert _run(checkout, "SessionStart").stdout == ""


def test_merge_base_just_inside_the_limit_is_silent(tmp_path: Path) -> None:
    remote = _make_remote(tmp_path, age_days=_WITHIN_LIMIT_DAYS)
    checkout = _make_checkout(remote)
    _git(checkout, "checkout", "-q", "-b", "feat")
    _commit(checkout, "feat.txt")
    _push_new_commit(remote)
    assert _run(checkout, "SessionStart").stdout == ""


def test_stale_branch_says_to_rebase_and_lists_agent_files(
    stale_checkout: Path, stale_remote: Path
) -> None:
    _git(stale_checkout, "checkout", "-q", "-b", "feat")
    _commit(stale_checkout, "feat.txt")
    _commit(stale_remote, ".agents/feature-map/x.md")
    _push_new_commit(stale_remote, "c.txt")
    out = _run(stale_checkout, "SessionStart").stdout
    assert "`feat` is 2 commits behind origin/main" in out
    assert "it is stale" in out
    assert "4 days ago (more than 3)" in out
    assert "merge conflicts" not in out
    assert ".agents/feature-map/x.md" in out
    assert "git rebase origin/main" in out


def test_stale_main_says_to_pull(stale_checkout: Path, stale_remote: Path) -> None:
    _push_new_commit(stale_remote)
    out = _run(stale_checkout, "SessionStart").stdout
    assert "`main` is 1 commit behind origin/main" in out
    assert "it is stale" in out
    assert "git pull --ff-only origin main" in out


def test_conflicting_branch_says_to_rebase_even_when_fresh(
    checkout: Path, remote: Path
) -> None:
    _make_conflict(checkout, remote)
    out = _run(checkout, "SessionStart").stdout
    assert "it has merge conflicts with origin/main" in out
    assert "it is stale" not in out
    assert "git rebase origin/main" in out


def test_conflicting_and_stale_branch_gives_both_reasons(
    stale_checkout: Path, stale_remote: Path
) -> None:
    _make_conflict(stale_checkout, stale_remote)
    out = _run(stale_checkout, "SessionStart").stdout
    assert "it has merge conflicts with origin/main and it is stale" in out


def test_hook_never_changes_the_working_tree(
    stale_checkout: Path, stale_remote: Path
) -> None:
    _git(stale_checkout, "checkout", "-q", "-b", "feat")
    _commit(stale_checkout, "feat.txt")
    (stale_checkout / "a.txt").write_text("local edit\n")
    (stale_checkout / "scratch.txt").write_text("untracked\n")
    _push_new_commit(stale_remote)
    head = _git(stale_checkout, "rev-parse", "HEAD")

    out = _run(stale_checkout, "SessionStart").stdout

    assert "uncommitted changes" in out
    assert _git(stale_checkout, "rev-parse", "HEAD") == head
    assert _git(stale_checkout, "branch", "--show-current") == "feat"
    assert (stale_checkout / "a.txt").read_text() == "local edit\n"
    assert (stale_checkout / "scratch.txt").read_text() == "untracked\n"
    assert _git(stale_checkout, "status", "--porcelain", "--untracked-files=no") == (
        "M a.txt"
    )


def test_only_untracked_files_still_warn_about_uncommitted_changes(
    stale_checkout: Path, stale_remote: Path
) -> None:
    (stale_checkout / "scratch.txt").write_text("untracked\n")
    _push_new_commit(stale_remote)
    out = _run(stale_checkout, "SessionStart").stdout
    assert "uncommitted changes" in out


def test_clean_tree_does_not_warn_about_uncommitted_changes(
    stale_checkout: Path, stale_remote: Path
) -> None:
    _push_new_commit(stale_remote)
    assert "uncommitted changes" not in _run(stale_checkout, "SessionStart").stdout


def test_session_start_offline_reports_against_last_known_main(
    stale_checkout: Path, stale_remote: Path
) -> None:
    _push_new_commit(stale_remote)
    _git(stale_checkout, "fetch", "-q", "origin", "main")
    _git(
        stale_checkout,
        "remote",
        "set-url",
        "origin",
        str(stale_checkout / "missing.git"),
    )
    out = _run(stale_checkout, "SessionStart").stdout
    assert "Could not fetch origin/main" in out
    assert "`main` is 1 commit behind origin/main" in out


def test_session_start_offline_and_current_is_silent(checkout: Path) -> None:
    _git(checkout, "remote", "set-url", "origin", str(checkout / "missing.git"))
    assert _run(checkout, "SessionStart").stdout == ""


def test_no_event_is_treated_as_session_start(
    stale_checkout: Path, stale_remote: Path
) -> None:
    _push_new_commit(stale_remote)
    assert "it is stale" in _run(stale_checkout).stdout


def test_skip_variable_silences_the_hook(
    stale_checkout: Path, stale_remote: Path
) -> None:
    _push_new_commit(stale_remote)
    assert (
        _run(stale_checkout, "SessionStart", ONYX_SKIP_MAIN_SYNC_CHECK="1").stdout == ""
    )


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_falsy_skip_values_do_not_disable_the_hook(
    stale_checkout: Path, stale_remote: Path, value: str
) -> None:
    _push_new_commit(stale_remote)
    out = _run(stale_checkout, "SessionStart", ONYX_SKIP_MAIN_SYNC_CHECK=value).stdout
    assert "it is stale" in out


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_truthy_skip_values_disable_the_hook(
    stale_checkout: Path, stale_remote: Path, value: str
) -> None:
    _push_new_commit(stale_remote)
    assert (
        _run(stale_checkout, "SessionStart", ONYX_SKIP_MAIN_SYNC_CHECK=value).stdout
        == ""
    )


@pytest.mark.parametrize(
    "stdin",
    [
        "[]",
        "null",
        "42",
        '"text"',
        "{not json",
        '{"cwd": 5, "hook_event_name": ["UserPromptSubmit"]}',
        '{"cwd": ["x"]}',
        '{"cwd": ""}',
        "\xff\xfe",
    ],
)
def test_malformed_payload_falls_back_to_the_cwd_and_exits_zero(
    stale_checkout: Path, stale_remote: Path, stdin: str
) -> None:
    _push_new_commit(stale_remote)
    # Run from inside the checkout: with no usable `cwd` in the payload the hook
    # checks the directory it was started in, and treats the event as session start.
    out = _run_raw(stale_checkout, stdin).stdout
    assert "it is stale" in out


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


def test_prompt_is_silent_when_behind_but_fresh_and_clean(
    checkout: Path, remote: Path
) -> None:
    _push_new_commit(remote)
    assert _run(checkout, "UserPromptSubmit").stdout == ""


def test_prompt_reports_when_stale_and_fetch_is_due(
    stale_checkout: Path, stale_remote: Path
) -> None:
    _push_new_commit(stale_remote)
    out = _run(stale_checkout, "UserPromptSubmit").stdout
    assert "`main` is 1 commit behind origin/main" in out
    assert "Could not fetch" not in out


def test_prompt_reports_a_conflict_when_fetch_is_due(
    checkout: Path, remote: Path
) -> None:
    _make_conflict(checkout, remote)
    assert "merge conflicts" in _run(checkout, "UserPromptSubmit").stdout


def test_prompt_fetches_at_most_once_an_hour(
    stale_checkout: Path, stale_remote: Path
) -> None:
    assert _run(stale_checkout, "UserPromptSubmit").stdout == ""
    assert _stamp(stale_checkout).exists()

    # A fetch within the hour would see this commit.
    _push_new_commit(stale_remote)
    assert _run(stale_checkout, "UserPromptSubmit").stdout == ""

    _age_stamp(stale_checkout, 2 * 60 * 60)
    assert "1 commit behind" in _run(stale_checkout, "UserPromptSubmit").stdout
    assert time.time() - _stamp(stale_checkout).stat().st_mtime < 60


def test_prompt_uses_the_cached_main_between_fetches(
    stale_checkout: Path, stale_remote: Path
) -> None:
    _push_new_commit(stale_remote)
    _git(stale_checkout, "fetch", "-q", "origin", "main")
    _stamp(stale_checkout).touch()
    assert "1 commit behind" in _run(stale_checkout, "UserPromptSubmit").stdout


def test_session_start_counts_as_a_fetch_for_the_throttle(
    stale_checkout: Path, stale_remote: Path
) -> None:
    _run(stale_checkout, "SessionStart")
    _push_new_commit(stale_remote)
    assert _run(stale_checkout, "UserPromptSubmit").stdout == ""


def test_prompt_offline_tries_once_and_stays_silent(checkout: Path) -> None:
    _git(checkout, "remote", "set-url", "origin", str(checkout / "missing.git"))
    _stamp(checkout).touch()
    _age_stamp(checkout, 2 * 60 * 60)

    assert _run(checkout, "UserPromptSubmit").stdout == ""
    # The failed attempt still counts, so the next prompt does not retry.
    assert time.time() - _stamp(checkout).stat().st_mtime < 60


def test_single_branch_clone_still_gets_origin_main(
    stale_remote: Path, tmp_path: Path
) -> None:
    _git(stale_remote, "checkout", "-q", "-b", "feat")
    _commit(stale_remote, "feat.txt")
    _git(stale_remote, "push", "-q", "origin", "feat")
    _git(stale_remote, "checkout", "-q", "main")
    single = tmp_path / "single"
    _git(
        tmp_path,
        "clone",
        "-q",
        "--single-branch",
        "--branch",
        "feat",
        str(tmp_path / "origin.git"),
        str(single),
    )
    _push_new_commit(stale_remote, "c.txt")
    # A plain `git fetch origin main` would not create origin/main here.
    out = _run(single, "SessionStart").stdout
    assert "`feat` is 1 commit behind origin/main" in out
    assert "it is stale" in out


def _start_conflicting_merge(checkout: Path, remote: Path) -> None:
    _make_conflict(checkout, remote)
    _git(checkout, "fetch", "-q", "origin", "main")
    merge = subprocess.run(
        ["git", "merge", "origin/main"],
        cwd=checkout,
        env=_GIT_ENV,
        capture_output=True,
        text=True,
    )
    assert merge.returncode == 1
    assert (
        Path(_git(checkout, "rev-parse", "--absolute-git-dir")) / "MERGE_HEAD"
    ).exists()


def test_unfinished_merge_says_to_finish_or_abort_it(
    checkout: Path, remote: Path
) -> None:
    _start_conflicting_merge(checkout, remote)
    out = _run(checkout, "SessionStart").stdout
    assert "A merge is already in progress" in out
    assert "git merge --continue" in out
    assert "git merge --abort" in out
    assert "commit or stash" not in out
    assert "git rebase origin/main" not in out


def test_unfinished_rebase_is_not_told_to_start_another_update(
    checkout: Path, remote: Path
) -> None:
    _make_conflict(checkout, remote)
    _git(checkout, "fetch", "-q", "origin", "main")
    rebase = subprocess.run(
        ["git", "rebase", "origin/main"],
        cwd=checkout,
        env=_GIT_ENV,
        capture_output=True,
        text=True,
    )
    assert rebase.returncode != 0
    out = _run(checkout, "SessionStart").stdout
    assert "git rebase origin/main" not in out
    assert "commit or stash" not in out


def _load_hook() -> object:
    spec = importlib.util.spec_from_file_location("ensure_latest_main", _HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ssh_command_extends_the_configured_one(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = _load_hook()
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.delenv("GIT_SSH", raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    ssh_env = hook._ssh_env  # type: ignore[attr-defined]
    batch = "-o BatchMode=yes -o ConnectTimeout=10"

    assert ssh_env(checkout) == {"GIT_SSH_COMMAND": f"ssh {batch}"}

    _git(checkout, "config", "core.sshCommand", "ssh -i /keys/work")
    assert ssh_env(checkout) == {"GIT_SSH_COMMAND": f"ssh -i /keys/work {batch}"}

    monkeypatch.setenv("GIT_SSH_COMMAND", "wrapper --flag")
    assert ssh_env(checkout) == {"GIT_SSH_COMMAND": f"wrapper --flag {batch}"}

    monkeypatch.delenv("GIT_SSH_COMMAND")
    monkeypatch.setenv("GIT_SSH", "/usr/local/bin/my-ssh")
    assert ssh_env(checkout) == {}
