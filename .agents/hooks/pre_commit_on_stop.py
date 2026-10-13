#!/usr/bin/env python3
"""Turn hooks for coding agents (Claude Code and Codex).

On `UserPromptSubmit` the hook records HEAD and the contents of every dirty file.
On `Stop` it compares against that record, so it only looks at the files this turn
changed (edited, created or committed), never scratch files or older edits. For
those files it:

- runs pre-commit;
- when the feature map has `stale_docs.py`, names the feature-map components whose
  code the turn changed but whose documents the branch did not.

When either has something to say, the hook exits with code 2 and prints it to
stderr. Both agents treat that as "keep going". A second stop in the same turn
(`stop_hook_active`) is let through, so a check the agent cannot fix never loops.
Without a record for the session, the stop does nothing.
"""

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

_BLOCK = 2
_TIMEOUT_SECONDS = 540
_MAX_OUTPUT_LINES = 80
_REMINDER_TIMEOUT_SECONDS = 60
_STALE_DOCS = Path(".agents/feature-map/stale_docs.py")
_FEATURE_MAP_DIR = ".agents/feature-map/"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def _git_paths(repo: Path, *args: str) -> set[str]:
    # -z keeps paths with non-ASCII characters unquoted.
    return {path for path in _git(repo, *args, "-z").split("\0") if path}


def _dirty_files(repo: Path) -> set[str]:
    """Uncommitted changes, including deletions and untracked files."""
    return _git_paths(repo, "diff", "--name-only", "HEAD") | _git_paths(
        repo, "ls-files", "--others", "--exclude-standard"
    )


def _digests(repo: Path, files: list[str]) -> dict[str, str]:
    """Content hash per file; an empty string for a file that does not exist."""
    return {
        path: (
            hashlib.sha256((repo / path).read_bytes()).hexdigest()
            if (repo / path).is_file()
            else ""
        )
        for path in files
    }


def _snapshot_path(repo: Path, session: str) -> Path:
    git_dir = Path(_git(repo, "rev-parse", "--absolute-git-dir").strip())
    return git_dir / "agent-turns" / f"{re.sub(r'[^A-Za-z0-9_-]', '_', session)}.json"


def _record_turn_start(repo: Path, session: str) -> None:
    snapshot = _snapshot_path(repo, session)
    snapshot.parent.mkdir(exist_ok=True)
    snapshot.write_text(
        json.dumps(
            {
                "head": _git(repo, "rev-parse", "HEAD").strip(),
                "files": _digests(repo, sorted(_dirty_files(repo))),
            }
        )
    )


def _turn_changes(repo: Path, session: str) -> set[str] | None:
    """Files the turn edited, created, deleted or committed; None without a record."""
    try:
        start: dict[str, Any] = json.loads(_snapshot_path(repo, session).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    start_files: dict[str, str] = start.get("files", {})
    changed = {
        path
        for path, digest in _digests(repo, sorted(_dirty_files(repo))).items()
        if start_files.get(path) != digest
    }
    try:
        changed |= _git_paths(repo, "diff", "--name-only", start["head"], "HEAD")
    except (subprocess.CalledProcessError, KeyError):
        pass
    return changed


def _pre_commit(repo: Path) -> str | None:
    on_path = shutil.which("pre-commit")
    if on_path:
        return on_path
    in_venv = repo / ".venv" / "bin" / "pre-commit"
    return str(in_venv) if in_venv.exists() else None


def _pre_commit_failures(repo: Path, files: list[str]) -> str | None:
    pre_commit = _pre_commit(repo)
    if not files or pre_commit is None:
        return None

    # pre-commit spots formatter rewrites through `git diff`, which cannot see
    # untracked files, so compare contents to catch rewrites of new files too.
    before = _digests(repo, files)
    # A new session lets a timeout stop the hooks pre-commit started, not only
    # pre-commit itself.
    try:
        proc = subprocess.Popen(
            [pre_commit, "run", "--files", *files],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as e:
        return f"Could not run pre-commit ({e}); run it yourself before finishing."
    try:
        stdout, stderr = proc.communicate(timeout=_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return "pre-commit timed out; run it yourself before finishing."
    rewritten = sorted(
        path
        for path, digest in _digests(repo, files).items()
        if before.get(path) != digest
    )
    if proc.returncode == 0 and not rewritten:
        return None

    lines = [
        line
        for line in (stdout + stderr).splitlines()
        if not line.rstrip().endswith(("Passed", "Skipped"))
    ]
    return (
        "pre-commit failed on the files you changed this turn. Fix these before you "
        "finish. "
        "Formatters may already have rewritten some files.\n"
        + "\n".join(lines[-_MAX_OUTPUT_LINES:])
        + ("\nRewritten by hooks: " + ", ".join(rewritten) if rewritten else "")
    )


def _branch_doc_changes(repo: Path) -> set[str]:
    """Feature-map files the branch changed, committed or not."""
    base = "HEAD"
    for upstream in ("origin/main", "main"):
        try:
            base = _git(repo, "merge-base", "HEAD", upstream).strip()
            break
        except subprocess.CalledProcessError:
            continue
    changed = _git_paths(repo, "diff", "--name-only", base) | _git_paths(
        repo, "ls-files", "--others", "--exclude-standard"
    )
    return {path for path in changed if path.startswith(_FEATURE_MAP_DIR)}


def _stale_doc_reminder(repo: Path, session: str, turn: set[str]) -> str | None:
    """Components the turn's code touched whose documents the branch never updated."""
    script = repo / _STALE_DOCS
    if not script.is_file() or not turn:
        return None
    files = turn | _branch_doc_changes(repo)
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--session", session, *sorted(files)],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=_REMINDER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None
    return result.stdout.strip() or None


def main() -> int:
    payload: dict[str, Any]
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    session: str | None = payload.get("session_id")
    if not session or payload.get("stop_hook_active"):
        return 0

    try:
        repo = Path(
            _git(
                Path(payload.get("cwd") or os.getcwd()), "rev-parse", "--show-toplevel"
            ).strip()
        )
        if payload.get("hook_event_name") == "UserPromptSubmit":
            _record_turn_start(repo, session)
            return 0
        turn = _turn_changes(repo, session)
    except (subprocess.CalledProcessError, OSError):
        return 0
    if not turn:
        return 0
    try:
        reminder = _stale_doc_reminder(repo, session, turn)
    except (subprocess.CalledProcessError, OSError):
        reminder = None
    files = sorted(path for path in turn if (repo / path).is_file())
    messages = [
        message for message in (_pre_commit_failures(repo, files), reminder) if message
    ]
    if not messages:
        return 0
    print("\n\n".join(messages), file=sys.stderr)
    return _BLOCK


if __name__ == "__main__":
    sys.exit(main())
