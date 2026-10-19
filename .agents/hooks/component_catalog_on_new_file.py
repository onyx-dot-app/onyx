#!/usr/bin/env python3
"""Tool hook: point at the component catalog when an agent creates a web component.

When a tool call creates a `.tsx` file under `web/src/` or `web/lib/opal/src/`, the
hook adds context that tells the agent to check the frontend component catalog for
an existing component first. It never blocks the write. `agent_hook_io` handles each
agent's payload and output format.

Claude Code and Cursor run it on PreToolUse, before the file exists. Codex runs it on
PostToolUse, because Codex does not show PreToolUse context to the model; the
`*** Add File:` lines in the patch still mark the new files.
"""

import sys

from agent_hook_io import edited_files, give_feedback, read_payload, repo_root

_CATALOG = ".agents/skills/frontend-components/CATALOG.md"
_ROOTS = ("web/src/", "web/lib/opal/src/")
_SKIPPED_SUFFIXES = (".stories.tsx", ".test.tsx")


def main() -> int:
    payload = read_payload(sys.stdin.read())
    repo = repo_root()
    new_files = []
    for path, creates in edited_files(payload):
        if (
            not creates
            or path.suffix != ".tsx"
            or path.name.endswith(_SKIPPED_SUFFIXES)
        ):
            continue
        try:
            relative_path = path.relative_to(repo).as_posix()
        except ValueError:
            continue
        if relative_path.startswith(_ROOTS):
            new_files.append(relative_path)
    if not new_files:
        return 0

    event = str(payload.get("hook_event_name") or "PreToolUse")
    event = "PostToolUse" if event.lower() == "posttooluse" else "PreToolUse"
    give_feedback(
        payload,
        event,
        f"You are creating new component files: {', '.join(new_files)}. Before you "
        f"design them further, check {_CATALOG} for an Opal component, Opal layout or "
        "refresh-component that already does the job, and use it. Build new UI only "
        "from catalog components. If nothing matches, say so and say why.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
