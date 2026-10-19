#!/usr/bin/env python3
"""PostToolUse hook: migrate a web file to Opal when an agent edits it.

After an agent writes a `.ts`/`.tsx` file under `web/`, the hook runs oxlint on that
file and keeps the design-system diagnostics:

- `opal/no-replaced-refresh-import`: a refresh-components import that Opal replaces;
- `react/forbid-elements`: a raw `<button>`, `<input>`, `<select>` or `<textarea>`;
- `no-restricted-imports`: `lucide-react`, `react-icons` or `@/components/*`.

Baseline files only warn on the last two rules, so pre-commit passes them. The hook
still reports those warnings, except legacy `@/components/*` imports, which often
have no replacement yet. It gives the findings to the agent as context so the agent
migrates the file before it continues. `agent_hook_io` handles each agent's payload
and output format.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from agent_hook_io import edited_files, give_feedback, read_payload, repo_root

_TIMEOUT_SECONDS = 30
_RULES = {
    "opal(no-replaced-refresh-import)",
    "react(forbid-elements)",
    "eslint(no-restricted-imports)",
}
_BASELINE_MARKER = "Design-system baseline"


def _is_reported(diagnostic: dict[str, object]) -> bool:
    if diagnostic.get("code") not in _RULES:
        return False
    if diagnostic.get("severity") == "error":
        return True
    return "'@/components/" not in str(diagnostic.get("message", ""))


def _format(diagnostic: dict[str, object]) -> str:
    labels = diagnostic.get("labels")
    line = ""
    if isinstance(labels, list) and labels:
        span = labels[0].get("span", {}) if isinstance(labels[0], dict) else {}
        line = f":{span.get('line', '')}"
    help_text = diagnostic.get("help")
    suffix = f" {help_text}" if help_text else ""
    return f"- {diagnostic.get('filename')}{line}: {diagnostic.get('message')}{suffix}"


def _baseline_glob(relative_path: str) -> str:
    return re.sub(r"\[([^\]/]+)\]", r"[[]\1]", relative_path)


def _web_files(web: Path, paths: list[Path]) -> list[str]:
    files = []
    for path in paths:
        if path.suffix not in (".ts", ".tsx") or not path.exists():
            continue
        try:
            files.append(path.relative_to(web.resolve()).as_posix())
        except ValueError:
            continue
    return files


def main() -> int:
    payload = read_payload(sys.stdin.read())
    web = repo_root(payload) / "web"
    oxlint = web / "node_modules" / ".bin" / "oxlint"
    files = _web_files(web, [path for path, _ in edited_files(payload)])
    if not files or not oxlint.exists():
        return 0

    try:
        result = subprocess.run(
            [str(oxlint), "-f", "json", *files],
            cwd=web,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        diagnostics = json.loads(result.stdout).get("diagnostics", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return 0

    reported = [_format(d) for d in diagnostics if _is_reported(d)]
    if reported:
        give_feedback(
            payload,
            "PostToolUse",
            "Migrate these files to Opal before you continue:\n"
            + "\n".join(reported)
            + "\nEach Opal component has a README.md next to it under "
            "web/lib/opal/src/. Read it for the props. Do not change behavior.",
        )
        return 0

    rc = (web / ".oxlintrc.json").read_text()
    baseline = rc.split(_BASELINE_MARKER, 1)[1] if _BASELINE_MARKER in rc else ""
    dirty = {d.get("filename") for d in diagnostics if d.get("code") in _RULES}
    clean = [
        f'"{_baseline_glob(path)}"'
        for path in files
        if path not in dirty and f'"{_baseline_glob(path)}"' in baseline
    ]
    if clean:
        give_feedback(
            payload,
            "PostToolUse",
            "These files are now clean of the design-system rules. Remove them from "
            "the design-system baseline in web/.oxlintrc.json: " + ", ".join(clean),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
