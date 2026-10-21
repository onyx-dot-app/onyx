#!/usr/bin/env python3
"""Session-start hook: bootstrap the private Onyx agent context.

Onyx staff keep agent skills, knowledge and session hooks in the private
`onyx-agent-context` repo. This hook gets a new checkout to the point where the
agent can set the rest up:

1. When the user already has the context's hooks registered, and the script they
   point at still exists, it does nothing; those hooks take over.
2. When the context is on disk (see "Onyx agent context" in `AGENTS.md`), it tells
   the agent where it is and to offer the `agent-context-setup` skill.
3. When it is missing and the git email is at `onyx.app`, it clones it next to the
   main checkout (inside the checkout when that folder is the filesystem root or
   not writable, as in the devcontainer), at most once a week, and reports how
   that went.
4. Otherwise it is silent and makes no network calls.

Claude Code and Codex run it from `.claude/settings.json` and `.codex/hooks.json`;
Cursor runs the Claude Code one through its third-party import, and reads the
message from a JSON response. It never prompts for credentials and always exits
0. Set
`ONYX_SKIP_AGENT_CONTEXT_BOOTSTRAP=1` to turn it off.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_REPO_NAME = "onyx-agent-context"
_IN_REPO_NAME = ".agent-context"
_ENTRY_FILE = "AGENTS.md"
_ENV_PATH = "ONYX_AGENT_CONTEXT"
_CLONE_URL_ENV = "ONYX_AGENT_CONTEXT_URL"
_CLONE_URL = "https://github.com/onyx-dot-app/onyx-agent-context.git"
_SKIP_ENV = "ONYX_SKIP_AGENT_CONTEXT_BOOTSTRAP"
_STAFF_EMAIL_SUFFIX = "@onyx.app"
# Entries the context's own setup writes into the user's agent settings.
_REGISTERED_MARKER = "Onyx agent context: "
_SESSION_HOOK = "session_start.py"
# Files older setups (the context's old installer, `ods install-skill`) left behind.
_OLD_REPO_FILES = (".onyx-agent-context.json", ".agents-local.md", ".claude/CLAUDE.md")
_OLD_HOME_PATHS = (".claude/skills/onyx-infra", ".claude/skills/onyx-llm-context")
_USER_SKILL_HOMES = (
    ".claude/skills",
    ".cursor/skills",
    ".agents/skills",
    ".copilot/skills",
)
_CONTEXT_REPO_NAMES = ("onyx-agent-context", "onyx-llm-context")
_USER_SETTINGS = (".claude/settings.json", ".codex/hooks.json")
_STAMP_NAME = "onyx-agent-context-clone-attempt"
_RETRY_SECONDS = 7 * 24 * 60 * 60
_GIT_TIMEOUT_SECONDS = 10
_CLONE_TIMEOUT_SECONDS = 30
_PREFIX = "[agent-context-bootstrap]"


def _git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return result.stdout.strip()


def _main_checkout(repo: Path) -> Path:
    listing = _git(repo, "worktree", "list", "--porcelain") or ""
    for line in listing.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree ") :])
    return repo


def _find(repo: Path, main: Path) -> Path | None:
    explicit = os.environ.get(_ENV_PATH, "").strip()
    candidates = (
        [Path(explicit).expanduser()]
        if explicit
        else [main.parent / _REPO_NAME, repo / _IN_REPO_NAME, main / _IN_REPO_NAME]
    )
    for candidate in candidates:
        if (candidate / _ENTRY_FILE).is_file():
            return candidate
    return None


def _registered_commands(value: object) -> list[str]:
    """Commands of hook entries the context's setup wrote, anywhere in `value`."""
    if isinstance(value, dict):
        if str(value.get("statusMessage", "")).startswith(_REGISTERED_MARKER):
            return [str(value.get("command", ""))]
        return [c for v in value.values() for c in _registered_commands(v)]
    if isinstance(value, list):
        return [c for v in value for c in _registered_commands(v)]
    return []


def _hooks_registered() -> bool:
    """True when a registered session hook points at a script that exists."""
    home = Path.home()
    for name in _USER_SETTINGS:
        try:
            settings = json.loads((home / name).read_text())
        except (OSError, ValueError):
            continue
        for command in _registered_commands(settings):
            try:
                words = shlex.split(command)
            except ValueError:
                continue
            if any(w.endswith(_SESSION_HOOK) and Path(w).is_file() for w in words):
                return True
    return False


def _older_setup_note(repo: Path) -> str:
    home = Path.home()
    found = [repo / name for name in _OLD_REPO_FILES if (repo / name).is_file()]
    found += [home / name for name in _OLD_HOME_PATHS if (home / name).exists()]
    # The current setup's skill links only exist once its hooks are registered,
    # which this note is never shown for.
    for name in _USER_SKILL_HOMES:
        try:
            links = [p for p in (home / name).iterdir() if p.is_symlink()]
        except OSError:
            continue
        found += [
            link
            for link in links
            if any(repo_name in os.readlink(link) for repo_name in _CONTEXT_REPO_NAMES)
        ]
    if not found:
        return ""
    return (
        f" This machine also has files from an older agent-context setup, such as "
        f"`{found[0]}`; the setup skill migrates them."
    )


def _writable(folder: Path) -> bool:
    try:
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False


def _clone_target(main: Path) -> Path:
    parent = main.parent
    if parent != parent.parent and _writable(parent):
        return parent / _REPO_NAME
    return main / _IN_REPO_NAME


def _clone_due(repo: Path) -> bool:
    """True when the last clone attempt is over a week old; marks a new attempt."""
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return False
    stamp = Path(common) / _STAMP_NAME
    try:
        if time.time() - stamp.stat().st_mtime < _RETRY_SECONDS:
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


def _clone(url: str, target: Path) -> bool:
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh")
        + " -o BatchMode=yes -o ConnectTimeout=10",
    }
    try:
        proc = subprocess.Popen(
            ["git", "clone", "--quiet", url, str(target)],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    try:
        ok = proc.wait(timeout=_CLONE_TIMEOUT_SECONDS) == 0
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        ok = False
    return ok and (target / _ENTRY_FILE).is_file()


def _offer(context: Path, how: str) -> str:
    lead = f"{_PREFIX} {how} " if how else f"{_PREFIX} "
    return (
        f"{lead}The Onyx agent context is at `{context}`. Read its "
        f"`{_ENTRY_FILE}` and follow it. Its session hooks are not set up for this "
        "user yet: offer the user its `agent-context-setup` skill."
    )


def _report(repo: Path) -> str | None:
    if _hooks_registered():
        return None
    main = _main_checkout(repo)
    context = _find(repo, main)
    if context:
        return _offer(context, "") + _older_setup_note(repo)
    if os.environ.get(_ENV_PATH, "").strip():
        return None
    email = (_git(repo, "config", "user.email") or "").lower()
    if not email.endswith(_STAFF_EMAIL_SUFFIX) or not _clone_due(repo):
        return None
    target = _clone_target(main)
    if target.exists():
        return None
    url = os.environ.get(_CLONE_URL_ENV, "").strip() or _CLONE_URL
    if _clone(url, target):
        return _offer(target, f"Cloned `{_REPO_NAME}` for you.")
    return (
        f"{_PREFIX} Could not clone `{url}` to `{target}` (no access, or offline). "
        "Tell the user once; it is retried next week."
    )


def _session_folder(payload: dict[str, object]) -> Path:
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        return Path(cwd)
    roots = payload.get("workspace_roots")
    if isinstance(roots, list) and roots and isinstance(roots[0], str):
        return Path(roots[0])
    return Path(os.getcwd())


def main() -> int:
    if os.environ.get(_SKIP_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        return 0
    try:
        decoded = json.loads(sys.stdin.read() or "{}")
        payload = decoded if isinstance(decoded, dict) else {}
        top = _git(_session_folder(payload), "rev-parse", "--show-toplevel")
        report = _report(Path(top)) if top else None
    except Exception:  # a session-start hook must never break the session
        return 0
    if report and "cursor_version" in payload:
        print(json.dumps({"additional_context": report}))
    elif report:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
