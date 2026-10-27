#!/usr/bin/env python3
"""Turn hooks for coding agents (Claude Code and Codex).

On `UserPromptSubmit` the hook records the HEAD reflog and every dirty file.
On `Stop` it compares against that record, so it only looks at the files this turn
changed (edited, created or committed), never scratch files or older edits. For
those files it:

- runs pre-commit;
- when the feature map has `stale_docs.py`, names the feature-map components whose
  code the turn changed but whose documents the branch did not.

Only pre-commit failures exit with code 2 and print to stderr. Documentation
reminders use a non-blocking UI message. A second stop in the same turn
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
    parents = _git(repo, "rev-list", "--parents", "-n", "1", merge).split()[1:]
    automatic = (
        _automatic_merge(repo, "--allow-unrelated-histories", *parents)
        if len(parents) == 2
        else None
    )
    if automatic is not None:
        return _git_paths(repo, "diff", "--name-only", automatic, merge)
    # merge-tree takes two branches; otherwise keep files that match no parent.
    return set.intersection(
        *(_git_paths(repo, "diff", "--name-only", parent, merge) for parent in parents)
    )


def _replay_files(
    repo: Path, before: str, after: str, originals: list[str]
) -> tuple[set[str], int | None]:
    """Files a rebase step changed beyond an automatic replay of one original.

    Returns the files and the index of the closest original. The closest replay
    leaves only resolution edits. A step that replays no original, such as a
    commit at an edit stop, keeps its whole diff.
    """
    closest = _git_paths(repo, "diff", "--name-only", before, after)
    closest_index: int | None = None
    for index, original in enumerate(originals):
        if not closest:
            break
        automatic = _automatic_merge(
            repo, "--merge-base", f"{original}^", before, original
        )
        if automatic is None:
            continue
        files = _git_paths(repo, "diff", "--name-only", automatic, after)
        if len(files) < len(closest):
            closest, closest_index = files, index
    return closest, closest_index


def _rebase_originals(repo: Path, original_tip: str, onto: str) -> list[str]:
    return _git(
        repo, "rev-list", "--reverse", "--no-merges", f"{onto}..{original_tip}"
    ).split()


def _rebase_in_progress(repo: Path) -> tuple[str, str] | None:
    """(original tip, onto) from Git's state for a rebase in progress."""
    for name in ("rebase-merge", "rebase-apply"):
        state = Path(_git(repo, "rev-parse", "--git-path", name).strip())
        try:
            return (
                (repo / state / "orig-head").read_text().strip(),
                (repo / state / "onto").read_text().strip(),
            )
        except OSError:
            continue
    return None


_Entry = tuple[str, str, str]  # (before, after, action)

# `git pull --rebase` names its start entry after the pull command.
_REBASE_STEP = re.compile(r"(?:rebase|pull .*?)(?: -i)? \((?P<step>[a-z]+)\):")
_COMMIT_ACTIONS = (
    "commit:",
    "commit (amend):",
    "commit (cherry-pick):",
    "cherry-pick:",
    "revert:",
    "rebase (continue):",
)


def _reflog_entries(chunk: bytes) -> list[_Entry]:
    entries: list[_Entry] = []
    for line in chunk.decode("utf-8", errors="replace").splitlines():
        refs, separator, action = line.partition("\t")
        if separator:
            before, after = refs.split()[:2]
            entries.append((before, after, action))
    return entries


def _committed_files(
    repo: Path, offset: int, digest: str, rebase: tuple[str, str] | None
) -> set[str]:
    """Read local commits and conflict resolutions, not imported branch updates."""
    log = _head_reflog(repo)
    if hashlib.sha256(log[:offset]).hexdigest() != digest:
        return set()  # The reflog was expired or rewritten during the turn.
    originals = _rebase_originals(repo, *rebase) if rebase else None
    files: set[str] = set()
    for before, after, action in _reflog_entries(log[offset:]):
        match = _REBASE_STEP.match(action)
        step = match["step"] if match else None
        if step == "start":
            originals = _rebase_originals(repo, before, after)
        elif step in ("finish", "abort"):
            originals = None
        elif originals is not None and (step or action.startswith(_COMMIT_ACTIONS)):
            replayed, index = _replay_files(repo, before, after, originals)
            files |= replayed
            if index is not None:
                # Replays keep their order, so the next one likely follows this one.
                originals = originals[index + 1 :] + originals[: index + 1]
        elif action.startswith("commit (merge):"):
            files |= _merge_resolution_files(repo, after)
        elif action.startswith(_COMMIT_ACTIONS):
            files |= _git_paths(repo, "diff", "--name-only", before, after)
    return files


def _record_turn_start(repo: Path, session: str) -> None:
    snapshot = _snapshot_path(repo, session)
    snapshot.parent.mkdir(exist_ok=True)
    reflog = _head_reflog(repo)
    snapshot.write_text(
        json.dumps(
            {
                "reflog_offset": len(reflog),
                "reflog_digest": hashlib.sha256(reflog).hexdigest(),
                "rebase": _rebase_in_progress(repo),
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
        offset = start.get("reflog_offset")
        digest = start.get("reflog_digest")
        rebase = start.get("rebase")
        if isinstance(offset, int) and offset >= 0 and isinstance(digest, str):
            changed |= _committed_files(
                repo, offset, digest, (rebase[0], rebase[1]) if rebase else None
            )
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
    failure = _pre_commit_failures(repo, files)
    if failure:
        print(
            "\n\n".join(message for message in (failure, reminder) if message),
            file=sys.stderr,
        )
        return _BLOCK
    if reminder:
        print(json.dumps({"systemMessage": reminder}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
