#!/usr/bin/env python3
"""Stop hook for coding agents (Claude Code and Codex): run pre-commit on the files
the agent changed before it ends its turn.

When pre-commit fails, the hook exits with code 2 and prints the failing hooks to
stderr. Both agents treat that as "keep going", so the agent fixes the problems
first. A second stop in the same turn (`stop_hook_active`) is let through, so a
check the agent cannot fix never loops.
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
        files = _changed_files(repo)
    except (subprocess.CalledProcessError, OSError):
        return 0
    pre_commit = _pre_commit(repo)
    if not files or pre_commit is None:
        return 0

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
        print(
            "pre-commit timed out; run it yourself before finishing.", file=sys.stderr
        )
        return _BLOCK
    rewritten = sorted(
        path
        for path, digest in _digests(repo, files).items()
        if before.get(path) != digest
    )
    if proc.returncode == 0 and not rewritten:
        return 0

    lines = [
        line
        for line in (stdout + stderr).splitlines()
        if not line.rstrip().endswith(("Passed", "Skipped"))
    ]
    print(
        "pre-commit failed on your uncommitted changes. Fix these before you finish. "
        "Formatters may already have rewritten some files.\n"
        + "\n".join(lines[-_MAX_OUTPUT_LINES:])
        + ("\nRewritten by hooks: " + ", ".join(rewritten) if rewritten else ""),
        file=sys.stderr,
    )
    return _BLOCK


if __name__ == "__main__":
    sys.exit(main())
