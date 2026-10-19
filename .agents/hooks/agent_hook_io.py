"""Payload parsing and feedback output shared by the agent tool hooks.

The tool hooks run in Claude Code and Cursor (from `.claude/settings.json`; Cursor
imports it) and in Codex (from `.codex/hooks.json`). Each agent sends a different
payload and reads feedback from a different field:

- Claude Code: `tool_input.file_path`; feedback in `hookSpecificOutput.additionalContext`.
- Codex: `apply_patch` with the patch text in `tool_input.command`; feedback in
  `hookSpecificOutput.additionalContext`.
- Cursor: `file_path` at the top level or in `tool_input`; feedback in
  `additional_context` after a tool and `agent_message` before one.
"""

import json
import os
import re
from pathlib import Path
from typing import Any

_PATCH_FILE_LINE = re.compile(
    r"^\*\*\* (Add|Update|Delete) File: (.+)$|^\*\*\* Move to: (.+)$", re.MULTILINE
)
_PATH_KEYS = ("file_path", "path", "target_file", "filePath")


def read_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def is_cursor(payload: dict[str, Any]) -> bool:
    return "cursor_version" in payload or "conversation_id" in payload


def repo_root(payload: dict[str, Any]) -> Path:
    for key in ("CLAUDE_PROJECT_DIR", "CURSOR_PROJECT_DIR"):
        if os.environ.get(key):
            return Path(os.environ[key]).resolve()
    roots = payload.get("workspace_roots")
    if isinstance(roots, list) and roots:
        return Path(str(roots[0])).resolve()
    return Path(str(payload.get("cwd") or Path.cwd())).resolve()


def edited_files(payload: dict[str, Any]) -> list[tuple[Path, bool]]:
    """(absolute path, the tool creates the file) for each file the tool call writes."""
    base = Path(str(payload.get("cwd") or repo_root(payload)))
    tool_input = payload.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}

    patch = tool_input.get("command") or tool_input.get("patch") or ""
    if isinstance(patch, list):
        patch = "\n".join(str(part) for part in patch)
    if isinstance(patch, str) and "*** Begin Patch" in patch:
        files = []
        for action, path, moved_to in _PATCH_FILE_LINE.findall(patch):
            if action == "Delete":
                continue
            target = (moved_to or path).strip()
            files.append(((base / target).resolve(), action == "Add"))
        return files

    for source in (tool_input, payload):
        for key in _PATH_KEYS:
            value = source.get(key)
            if isinstance(value, str) and value:
                path = (base / value).resolve()
                return [(path, not path.exists())]
    return []


def give_feedback(payload: dict[str, Any], event: str, message: str) -> None:
    """Print feedback the agent reads as context. It never blocks the tool call."""
    if is_cursor(payload):
        key = "additional_context" if event == "PostToolUse" else "agent_message"
        output: dict[str, Any] = {key: message}
        if event == "PreToolUse":
            output["permission"] = "allow"
    else:
        output = {
            "hookSpecificOutput": {"hookEventName": event, "additionalContext": message}
        }
    print(json.dumps(output))
