#!/usr/bin/env python3
"""Turn hooks for coding agents (Claude Code and Codex).

On `UserPromptSubmit` the hook records HEAD, the HEAD reflog and every dirty file.
On `Stop` it compares against that record, so it only looks at the files this turn
changed (edited, created or committed), never scratch files or older edits. For
those files it:

- runs pre-commit;
- when the feature map has `stale_docs.py`, builds an editing brief: the parts of
  the feature-map documents that cite the changed code, and the questions that
  decide whether they need an edit. `stale_docs.py` prints nothing when no part
  cites the code and every changed file is mapped, so ownership alone never blocks.
  It measures each change from the HEAD of the turn's start, so edits the turn
  committed count too.

A pre-commit failure exits with code 2 and prints to stderr, with the brief after
it. A brief alone blocks the stop once with `{"decision": "block", "reason": ...}`,
so the model reads it; Claude Code and Codex both accept that output. The next stop
(`stop_hook_active`) runs pre-commit once more, so the edits the brief led to are
checked too. Any later stop in the turn is let through, so nothing loops, and
`stale_docs.py --session` names each section or key of a document once per
session. Without a record for the session, the stop does nothing.
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


def _head_reflog(repo: Path) -> bytes:
    path = Path(_git(repo, "rev-parse", "--git-path", "logs/HEAD").strip())
    try:
        return (repo / path).read_bytes()
    except FileNotFoundError:
        return b""


def _automatic_merge(repo: Path, *merge_args: str) -> str | None:
    """Tree of Git's automatic merge, with conflict markers where it conflicts."""
    result = subprocess.run(
        ["git", "merge-tree", "--write-tree", *merge_args],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    # Exit code 1 means the automatic merge had conflicts; the tree still exists.
    if result.returncode not in (0, 1) or not result.stdout:
        return None
    return result.stdout.split()[0]


def _merge_resolution_files(repo: Path, merge: str) -> set[str]:
    """Files a merge commit changed beyond Git's automatic merge of its parents."""
    first, *others = _git(repo, "rev-list", "--parents", "-n", "1", merge).split()[1:]
    combined = first
    for index, parent in enumerate(others, start=1):
        tree = _automatic_merge(repo, "--allow-unrelated-histories", combined, parent)
        if tree is None:
            return _git_paths(repo, "diff", "--name-only", first, merge)
        # An octopus merge folds each parent into the result of the ones before.
        combined = (
            tree
            if index == len(others)
            else _git(
                repo, "commit-tree", tree, "-p", combined, "-p", parent, "-m", "merge"
            ).strip()
        )
    return _git_paths(repo, "diff", "--name-only", combined, merge) if others else set()


def _committed_files(repo: Path, offset: int, digest: str) -> set[str]:
    """Read local commits and conflict resolutions, not imported branch updates."""
    log = _head_reflog(repo)
    if hashlib.sha256(log[:offset]).hexdigest() != digest:
        return set()  # The reflog was expired or rewritten during the turn.
    files: set[str] = set()
    for entry in log[offset:].decode("utf-8", errors="replace").splitlines():
        refs, separator, action = entry.partition("\t")
        if not separator:
            continue
        before, after = refs.split()[:2]
        if action.startswith("commit (merge):"):
            files |= _merge_resolution_files(repo, after)
        elif action.startswith(
            (
                "commit:",
                "commit (amend):",
                "commit (cherry-pick):",
                "cherry-pick:",
                "revert:",
                # A conflict resolved during a rebase; clean picks are skipped.
                "rebase (continue):",
            )
        ):
            files |= _git_paths(repo, "diff", "--name-only", before, after)
    return files


def _head(repo: Path) -> str | None:
    """The HEAD commit; None in a repository with no commits."""
    result = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "HEAD^{commit}"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None


def _record_turn_start(repo: Path, session: str) -> None:
    snapshot = _snapshot_path(repo, session)
    snapshot.parent.mkdir(exist_ok=True)
    reflog = _head_reflog(repo)
    snapshot.write_text(
        json.dumps(
            {
                "head": _head(repo),
                "reflog_offset": len(reflog),
                "reflog_digest": hashlib.sha256(reflog).hexdigest(),
                "files": _digests(repo, sorted(_dirty_files(repo))),
            }
        )
    )


def _read_turn_start(repo: Path, session: str) -> dict[str, Any] | None:
    try:
        start = json.loads(_snapshot_path(repo, session).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return start if isinstance(start, dict) else None


def _set_recheck(repo: Path, session: str, recheck: bool) -> None:
    """Mark whether the next stop of the turn runs pre-commit again."""
    start = _read_turn_start(repo, session)
    if start is not None and start.get("recheck", False) != recheck:
        start["recheck"] = recheck
        _snapshot_path(repo, session).write_text(json.dumps(start))


def _turn_changes(repo: Path, session: str) -> set[str] | None:
    """Files the turn edited, created, deleted or committed; None without a record."""
    start = _read_turn_start(repo, session)
    if start is None:
        return None
    start_files: dict[str, str] = start.get("files", {})
    changed = {
        path
        for path, digest in _digests(repo, sorted(_dirty_files(repo))).items()
        if start_files.get(path) != digest
    }
    try:
        offset = start.get("reflog_offset")
        digest = start.get("reflog_digest")
        if isinstance(offset, int) and offset >= 0 and isinstance(digest, str):
            changed |= _committed_files(repo, offset, digest)
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


def _editing_brief(
    repo: Path, session: str, turn: set[str], base: str | None
) -> str | None:
    """The feature-map parts that cite the turn's code; documents it edited are skipped.

    `base` is HEAD at the turn's start; the brief measures each change from it.
    """
    script = repo / _STALE_DOCS
    if not script.is_file() or not turn:
        return None
    options = ["--session", session] + (["--base", base] if base else [])
    try:
        result = subprocess.run(
            [sys.executable, str(script), *options, "--", *sorted(turn)],
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
    if not session:
        return 0
    continued = bool(payload.get("stop_hook_active"))

    try:
        repo = Path(
            _git(
                Path(payload.get("cwd") or os.getcwd()), "rev-parse", "--show-toplevel"
            ).strip()
        )
        if payload.get("hook_event_name") == "UserPromptSubmit":
            _record_turn_start(repo, session)
            return 0
        if continued:
            start = _read_turn_start(repo, session)
            # Only the stop right after a brief runs again, and only once.
            if start is None or not start.get("recheck"):
                return 0
            _set_recheck(repo, session, False)
        turn = _turn_changes(repo, session)
        start = _read_turn_start(repo, session) or {}
    except (subprocess.CalledProcessError, OSError):
        return 0
    if not turn:
        return 0
    brief = None
    if not continued:
        head = start.get("head")
        try:
            brief = _editing_brief(
                repo, session, turn, head if isinstance(head, str) else None
            )
        except (subprocess.CalledProcessError, OSError):
            brief = None
    files = sorted(path for path in turn if (repo / path).is_file())
    failure = _pre_commit_failures(repo, files)
    if brief:
        # The next stop checks the edits the brief leads to, with or without a
        # failure now.
        try:
            _set_recheck(repo, session, True)
        except OSError:
            pass
    if failure:
        print(
            "\n\n".join(message for message in (failure, brief) if message),
            file=sys.stderr,
        )
        return _BLOCK
    if brief:
        print(json.dumps({"decision": "block", "reason": brief}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
