#!/usr/bin/env python3
"""Stop hook for coding agents (Claude Code and Codex). Before the agent ends its
turn it:

- runs pre-commit on the files the agent changed and has not committed;
- when the feature map has `stale_docs.py`, names the feature-map components whose
  code the branch changed but whose documents it did not.

When either has something to say, the hook exits with code 2 and prints it to
stderr. Both agents treat that as "keep going". A second stop in the same turn
(`stop_hook_active`) is let through, so a check the agent cannot fix never loops.
"""

import hashlib
import json
import os
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


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def _git_paths(repo: Path, *args: str) -> set[str]:
    # -z keeps paths with non-ASCII characters unquoted.
    return {path for path in _git(repo, *args, "-z").split("\0") if path}


def _changed_files(repo: Path) -> list[str]:
    changed = _git_paths(repo, "diff", "--name-only", "--diff-filter=d", "HEAD")
    changed |= _git_paths(repo, "ls-files", "--others", "--exclude-standard")
    return sorted(path for path in changed if (repo / path).is_file())


def _digests(repo: Path, files: list[str]) -> dict[str, str]:
    return {
        path: hashlib.sha256((repo / path).read_bytes()).hexdigest()
        for path in files
        if (repo / path).is_file()
    }


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
    proc = subprocess.Popen(
        [pre_commit, "run", "--files", *files],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
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
        "pre-commit failed on your uncommitted changes. Fix these before you finish. "
        "Formatters may already have rewritten some files.\n"
        + "\n".join(lines[-_MAX_OUTPUT_LINES:])
        + ("\nRewritten by hooks: " + ", ".join(rewritten) if rewritten else "")
    )


def _branch_changes(repo: Path) -> set[str]:
    """Every file the branch changed, committed or not, including deletions."""
    base = "HEAD"
    for upstream in ("origin/main", "main"):
        try:
            base = _git(repo, "merge-base", "HEAD", upstream).strip()
            break
        except subprocess.CalledProcessError:
            continue
    return _git_paths(repo, "diff", "--name-only", base) | _git_paths(
        repo, "ls-files", "--others", "--exclude-standard"
    )


def _stale_doc_reminder(repo: Path, session: str | None) -> str | None:
    script = repo / _STALE_DOCS
    if not script.is_file():
        return None
    changed = _branch_changes(repo)
    if not changed:
        return None
    session_args = ["--session", session] if session else []
    try:
        result = subprocess.run(
            [sys.executable, str(script), *session_args, *sorted(changed)],
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
    if payload.get("stop_hook_active"):
        return 0

    try:
        repo = Path(
            _git(
                Path(payload.get("cwd") or os.getcwd()), "rev-parse", "--show-toplevel"
            ).strip()
        )
        messages = [
            message
            for message in (
                _pre_commit_failures(repo, _changed_files(repo)),
                _stale_doc_reminder(repo, payload.get("session_id")),
            )
            if message
        ]
    except (subprocess.CalledProcessError, OSError):
        return 0
    if not messages:
        return 0
    print("\n\n".join(messages), file=sys.stderr)
    return _BLOCK


if __name__ == "__main__":
    sys.exit(main())
