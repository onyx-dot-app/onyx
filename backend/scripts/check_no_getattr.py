"""Pre-commit hook that blocks newly added calls to the ``getattr`` builtin.

Only lines added in the relevant diff are checked (the staged diff locally, or
the ``--from-ref``/``--to-ref`` range when pre-commit/prek is invoked with one),
so existing ``getattr`` usage in the codebase is grandfathered.

Bypasses:
- one line: append a ``# allow-getattr`` comment to the line,
- one commit: ``SKIP=no-getattr git commit ...`` or ``git commit --no-verify``.
"""

import os
import re
import subprocess
import sys

# Matches calls to the ``getattr`` builtin; the lookbehind excludes attribute
# access (``obj.getattr(``) and dunder definitions (``__getattr__(``).
_GETATTR_CALL = re.compile(r"(?<![\w.])getattr\s*\(")
_ALLOW_MARKER = "allow-getattr"
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)")


def _diff_range() -> list[str]:
    """Returns the git diff arguments selecting the lines under review."""
    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    if from_ref and to_ref:
        return [from_ref, to_ref]
    return ["--cached"]


def main(file_paths: list[str]) -> int:
    """Reports newly added ``getattr`` calls in ``file_paths``, returning the exit code."""
    if not file_paths:
        return 0
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--unified=0",
            "--no-color",
            "--no-ext-diff",
            *_diff_range(),
            "--",
            *file_paths,
        ],
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    ).stdout

    current_file: str | None = None
    line_number = 0
    violations: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:]
            current_file = path[2:] if path.startswith("b/") else None
        elif (hunk := _HUNK_HEADER.match(line)) is not None:
            line_number = int(hunk.group(1))
        elif line.startswith("+") and current_file is not None:
            content = line[1:]
            if _GETATTR_CALL.search(content) and _ALLOW_MARKER not in content:
                violations.append(
                    f"{current_file}:{line_number}: new call to the getattr builtin"
                )
            line_number += 1

    for violation in violations:
        print(violation)
    if violations:
        print(
            "getattr hides attribute access from type checkers; restructure to "
            f"avoid it, mark the line with `# {_ALLOW_MARKER}`, or bypass the "
            "hook with `SKIP=no-getattr git commit ...`."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
