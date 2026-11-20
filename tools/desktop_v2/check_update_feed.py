#!/usr/bin/env python3
"""Fail when desktop-v2 builds for an OS that the update feed does not serve.

The app checks `latest.json` for updates on every OS it runs on. A build for
an OS with no `latest.json` platform entry ships an app that never updates.

The check reads `.github/workflows/desktop-v2.yml`:

- An OS is built when a job that runs `tauri build` runs on it. The runner
  comes from `runs-on`, or from the matrix values that `runs-on` names.
- An OS is served when the workflow names a Tauri updater platform key for
  it outside a comment, such as "darwin-aarch64" or "windows-x86_64".

`# update-feed: allow <os> <reason>` in the workflow exempts an OS, for
example while the app turns off its updater there.

Usage, from the repo root:
    python3 tools/desktop_v2/check_update_feed.py
"""

import re
import sys
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = _REPO_ROOT / ".github/workflows/desktop-v2.yml"
_RUNNER_OS = (("macos", "darwin"), ("windows", "windows"), ("ubuntu", "linux"))
_FEED_KEY = re.compile(r"\b(darwin|windows|linux)-(x86_64|aarch64|i686|armv7)\b")
_ALLOW = re.compile(r"#\s*update-feed:\s*allow\s+(darwin|windows|linux)\b(.*)")
_MATRIX_REF = re.compile(r"\$\{\{\s*matrix\.([\w-]+)\s*\}\}")


def _runner_os(runner: str) -> str | None:
    for prefix, os_name in _RUNNER_OS:
        if runner.startswith(prefix):
            return os_name
    return None


def _runners(job: dict[str, Any]) -> list[str]:
    runs_on = job.get("runs-on", "")
    if not isinstance(runs_on, str):
        return []
    ref = _MATRIX_REF.fullmatch(runs_on.strip())
    if ref is None:
        return [runs_on]
    matrix = job.get("strategy", {}).get("matrix", {})
    key = ref.group(1)
    values = [str(v) for v in matrix.get(key, []) if isinstance(matrix.get(key), list)]
    values += [str(i[key]) for i in matrix.get("include", []) if key in i]
    return values


def built_oses(workflow: dict[str, Any]) -> set[str]:
    built: set[str] = set()
    for job in workflow.get("jobs", {}).values():
        steps = job.get("steps", [])
        if not any("tauri build" in str(step.get("run", "")) for step in steps):
            continue
        for runner in _runners(job):
            os_name = _runner_os(runner)
            if os_name:
                built.add(os_name)
    return built


def served_oses(text: str) -> set[str]:
    """OSes with a feed key outside a comment line."""
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    return {match.group(1) for match in _FEED_KEY.finditer(code)}


def allowed_oses(text: str) -> tuple[set[str], list[str]]:
    allowed: set[str] = set()
    errors: list[str] = []
    for match in _ALLOW.finditer(text):
        if not re.search(r"\w", match.group(2)):
            errors.append(f"`update-feed: allow {match.group(1)}` needs a reason")
        else:
            allowed.add(match.group(1))
    return allowed, errors


def check(text: str) -> list[str]:
    allowed, errors = allowed_oses(text)
    missing = built_oses(yaml.safe_load(text)) - served_oses(text) - allowed
    for os_name in sorted(missing):
        errors.append(
            f"desktop-v2 builds for {os_name}, but the release writes no "
            f"'{os_name}-<arch>' entry to latest.json. Add the entry, or add "
            f"`# update-feed: allow {os_name} <reason>` and turn off the updater there."
        )
    return errors


def main() -> int:
    errors = check(WORKFLOW.read_text())
    for error in errors:
        print(f"{WORKFLOW.relative_to(_REPO_ROOT)}: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
