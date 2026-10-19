#!/usr/bin/env python3
"""PostToolUse hook for Claude Code: migrate a web file to Opal when an agent edits it.

After an Edit, MultiEdit or Write of a `.ts`/`.tsx` file under `web/`, the hook runs
oxlint on that file and keeps the design-system diagnostics:

- `opal/no-replaced-refresh-import`: a refresh-components import that Opal replaces;
- `react/forbid-elements`: a raw `<button>`, `<input>`, `<select>` or `<textarea>`;
- `no-restricted-imports`: `lucide-react`, `react-icons` or `@/components/*`.

Baseline files only warn on the last two rules, so pre-commit passes them. The hook
still reports those warnings, except legacy `@/components/*` imports, which often
have no replacement yet. When it reports something, it exits with code 2 so the
agent migrates the file before it continues.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_BLOCK = 2
_TIMEOUT_SECONDS = 30
_RULES = {
    "opal(no-replaced-refresh-import)",
    "react(forbid-elements)",
    "eslint(no-restricted-imports)",
}
_BASELINE_MARKER = "Design-system baseline"


def _repo_root() -> Path:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir:
        return Path(project_dir)
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


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


def main() -> int:
    payload = json.load(sys.stdin)
    file_path = payload.get("tool_input", {}).get("file_path")
    if not file_path or not file_path.endswith((".ts", ".tsx")):
        return 0

    web = _repo_root() / "web"
    oxlint = web / "node_modules" / ".bin" / "oxlint"
    try:
        relative_path = Path(file_path).resolve().relative_to(web.resolve()).as_posix()
    except ValueError:
        return 0
    if not oxlint.exists() or not (web / relative_path).exists():
        return 0

    try:
        result = subprocess.run(
            [str(oxlint), "-f", "json", relative_path],
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
        print(
            "Migrate this file to Opal before you continue:\n"
            + "\n".join(reported)
            + "\nEach Opal component has a README.md next to it under "
            "web/lib/opal/src/. Read it for the props. Do not change behavior.",
            file=sys.stderr,
        )
        return _BLOCK

    rc = (web / ".oxlintrc.json").read_text()
    glob = f'"{_baseline_glob(relative_path)}"'
    if _BASELINE_MARKER in rc and glob in rc.split(_BASELINE_MARKER, 1)[1]:
        remaining = [d for d in diagnostics if d.get("code") in _RULES]
        if not remaining:
            print(
                f"{relative_path} is now clean of the design-system rules. Remove "
                f"{glob} from the design-system baseline in web/.oxlintrc.json.",
                file=sys.stderr,
            )
            return _BLOCK
    return 0


if __name__ == "__main__":
    sys.exit(main())
