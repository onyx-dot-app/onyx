#!/usr/bin/env python3
"""Session-start hook for coding agents (Claude Code and Codex).

The feature map in `.agents/feature-map/`, the skills and these hooks are only as
current as the checkout, and a branch that drifts from main costs a much more
involved conflict resolution later. At session start this hook fetches `origin/main`
and tells the agent to rebase on it, but only when the branch has to be updated:

1. it would conflict with `origin/main` (`git merge-tree --write-tree` reports
   conflicts), or
2. it is stale: the merge base with `origin/main` is more than `_STALE_AFTER_DAYS`
   days old.

A branch that is merely a few commits behind, recently, gets no message; neither
does one that already contains `origin/main`. Both agents add a `SessionStart`
hook's stdout to the model's context.

On `UserPromptSubmit` it repeats the check for a long session, but fetches at most
once an hour per checkout (the time of the last attempt is the mtime of
`.git/onyx-main-sync-check`).

It never changes the working tree: no pull, rebase, merge or checkout. It only
updates the `origin/main` remote-tracking ref (and FETCH_HEAD), which is what
`git fetch` always does. It always exits 0, and a fetch that fails or hangs (offline,
no `origin`, no credentials) falls back to the last known `origin/main` with a note.

Set `ONYX_SKIP_MAIN_SYNC_CHECK=1` to turn it off.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_REMOTE = "origin"
_BRANCH = "main"
_REF = f"{_REMOTE}/{_BRANCH}"
_FETCH_TIMEOUT_SECONDS = 20
_PROMPT_FETCH_INTERVAL_SECONDS = 60 * 60
# A branch whose merge base with origin/main is older than this is stale.
_STALE_AFTER_DAYS = 3
_SECONDS_PER_DAY = 24 * 60 * 60
_STAMP_NAME = "onyx-main-sync-check"
_GIT_TIMEOUT_SECONDS = 10
_MAX_LISTED_FILES = 8
_AGENT_CONTEXT_DIR = ".agents/"
_SKIP_ENV = "ONYX_SKIP_MAIN_SYNC_CHECK"


def _git(repo: Path, *args: str) -> str | None:
    """Stdout of a git command, or None when it fails or times out."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return result.stdout.strip()


def _would_conflict(repo: Path) -> bool:
    """True when merging origin/main into HEAD would conflict.

    `git merge-tree --write-tree` exits 1 for conflicts. Any other failure (git
    older than 2.38, unrelated or shallow history) is not evidence of a conflict.
    Only objects are written; the index and working tree are untouched.
    """
    try:
        result = subprocess.run(
            ["git", "merge-tree", "--write-tree", "HEAD", _REF],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 1


def _fetch(repo: Path) -> bool:
    """Refresh origin/main; False when the fetch fails or exceeds its time limit."""
    # Never prompt for credentials, and fail fast on a dead connection rather
    # than hang session start.
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh")
        + " -o BatchMode=yes -o ConnectTimeout=10",
    }
    try:
        # A new session lets a timeout stop the helpers git started (ssh,
        # git-remote-https), not only git itself. DEVNULL keeps a surviving helper
        # from holding a pipe open.
        proc = subprocess.Popen(
            [
                "git",
                "fetch",
                "--quiet",
                "--no-tags",
                "--no-recurse-submodules",
                _REMOTE,
                _BRANCH,
            ],
            cwd=repo,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    try:
        return proc.wait(timeout=_FETCH_TIMEOUT_SECONDS) == 0
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        return False


def _fetch_due(repo: Path) -> bool:
    """True when the last fetch attempt is over an hour old; marks a new attempt.

    The stamp records attempts, not successes, so a checkout that is offline
    does not wait for a fetch to fail on every prompt.
    """
    git_dir = _git(repo, "rev-parse", "--absolute-git-dir")
    if not git_dir:
        return False
    stamp = Path(git_dir) / _STAMP_NAME
    try:
        if time.time() - stamp.stat().st_mtime < _PROMPT_FETCH_INTERVAL_SECONDS:
            return False
    except FileNotFoundError:
        pass
    except OSError:
        return False
    try:
        stamp.touch()
    except OSError:
        return False
    return True


def _mark_fetched(repo: Path) -> None:
    git_dir = _git(repo, "rev-parse", "--absolute-git-dir")
    try:
        if git_dir:
            (Path(git_dir) / _STAMP_NAME).touch()
    except OSError:
        pass


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _agent_context_changes(repo: Path, base: str) -> list[str]:
    """Files under `.agents/` that origin/main changed since `base`."""
    out = _git(repo, "diff", "--name-only", base, _REF, "--", _AGENT_CONTEXT_DIR)
    return out.splitlines() if out else []


def _report(repo: Path, fetched: bool | None) -> str | None:
    """The message for the agent, or None when the branch needs no update.

    `fetched` is None when no fetch was tried.
    """
    if _git(repo, "rev-parse", "--verify", "--quiet", f"{_REF}^{{commit}}") is None:
        return None  # no origin/main to compare with (no remote, not fetched yet)

    if _git(repo, "merge-base", "--is-ancestor", _REF, "HEAD") is not None:
        return None  # HEAD already contains everything on origin/main: nothing to do

    base = _git(repo, "merge-base", "HEAD", _REF)
    reasons: list[str] = []
    if _would_conflict(repo):
        reasons.append(f"it has merge conflicts with {_REF}")
    base_time = _git(repo, "show", "-s", "--format=%ct", base) if base else None
    if base_time and base_time.isdigit():
        age_seconds = time.time() - int(base_time)
        if age_seconds > _STALE_AFTER_DAYS * _SECONDS_PER_DAY:
            reasons.append(
                f"it is stale: it last synced with {_REF} "
                f"{int(age_seconds // _SECONDS_PER_DAY)} days ago "
                f"(more than {_STALE_AFTER_DAYS})"
            )
    if not reasons:
        return None

    branch = _git(repo, "branch", "--show-current") or "HEAD (detached)"
    on_main = branch == _BRANCH
    dirty = bool(_git(repo, "status", "--porcelain", "--untracked-files=no"))
    stale_note = (
        ""
        if fetched is not False
        else (
            f"Could not fetch {_REF} (offline or no access to `{_REMOTE}`), so this "
            f"compares against the last {_REF} this checkout saw, which may itself "
            "be out of date. "
        )
    )

    behind = int(_git(repo, "rev-list", "--count", f"HEAD..{_REF}") or 0)
    lines = [
        f"[ensure-latest-main] {stale_note}`{branch}` is {_plural(behind, 'commit')} "
        f"behind {_REF} and needs to be rebased on it: {' and '.join(reasons)}. "
        "Before you start work, update it; a branch kept current avoids a much more "
        "involved conflict resolution later, and keeps the feature map in "
        "`.agents/feature-map/` and the repo's other agent context current."
    ]
    changed = _agent_context_changes(repo, base) if base else []
    if changed:
        shown = ", ".join(changed[:_MAX_LISTED_FILES])
        more = len(changed) - _MAX_LISTED_FILES
        lines.append(
            f"{_REF} has changed {_plural(len(changed), 'file')} under "
            f"`{_AGENT_CONTEXT_DIR}` since this branch diverged: {shown}"
            + (f", and {more} more" if more > 0 else "")
            + "."
        )

    if dirty:
        lines.append(
            "The working tree has uncommitted changes: commit or stash them first, "
            "and do not discard them."
        )
    if on_main:
        lines.append(
            f"Update with `git pull --ff-only {_REMOTE} {_BRANCH}`. If that refuses "
            "because local main has commits of its own, do not force it; tell the user."
        )
    else:
        lines.append(
            f"Update with `git fetch {_REMOTE} {_BRANCH} && git rebase {_REF}`, or "
            f"`git merge {_REF}` if the branch is shared or already pushed. If it "
            "conflicts, resolve the conflicts, or abort and ask the user."
        )
    lines.append(
        "This hook changed nothing in your working tree. Skip the update only if the "
        "user told you to stay on this base."
    )
    return "\n".join(lines)


def main() -> int:
    if os.environ.get(_SKIP_ENV):
        return 0
    payload: dict[str, Any]
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        payload = {}
    start = Path(payload.get("cwd") or os.getcwd())
    quiet = payload.get("hook_event_name") == "UserPromptSubmit"
    try:
        top = _git(start, "rev-parse", "--show-toplevel")
        if not top:
            return 0
        repo = Path(top)
        fetched: bool | None = None
        if not quiet:
            fetched = _fetch(repo)
            _mark_fetched(repo)
        elif _fetch_due(repo):
            fetched = _fetch(repo)
        report = _report(repo, fetched)
    except Exception:  # a session-start hook must never break the session
        return 0
    if report:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
