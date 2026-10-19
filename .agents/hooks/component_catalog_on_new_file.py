#!/usr/bin/env python3
"""PreToolUse hook for Claude Code: point at the component catalog before a new web component.

Before a Write creates a `.tsx` file under `web/src/` or `web/lib/opal/src/`, the hook
adds context that tells the agent to check the frontend component catalog for an
existing component first. It never blocks the write.
"""

import json
import os
import sys
from pathlib import Path

_CATALOG = ".agents/skills/frontend-components/CATALOG.md"
_ROOTS = ("web/src/", "web/lib/opal/src/")
_SKIPPED_SUFFIXES = (".stories.tsx", ".test.tsx")


def main() -> int:
    payload = json.load(sys.stdin)
    file_path = payload.get("tool_input", {}).get("file_path")
    if (
        not file_path
        or not file_path.endswith(".tsx")
        or file_path.endswith(_SKIPPED_SUFFIXES)
    ):
        return 0
    path = Path(file_path)
    if path.exists():
        return 0

    repo = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path.cwd())).resolve()
    try:
        relative_path = path.resolve().relative_to(repo).as_posix()
    except ValueError:
        return 0
    if not relative_path.startswith(_ROOTS):
        return 0

    context = (
        f"You are creating a new component file, {relative_path}. Before you design it, "
        f"check {_CATALOG} for an Opal component, Opal layout or refresh-component that "
        "already does the job, and use it. Build new UI only from catalog components. "
        "If nothing matches, say so and say why."
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": context,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
