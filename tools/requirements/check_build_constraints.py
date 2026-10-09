#!/usr/bin/env python3
"""Fail if build-constraints.in disagrees with any project's build requirements.

`uv pip compile` cannot read `[build-system] requires`, so the pins live both in
tools/requirements/build-constraints.in and in each pyproject.toml. A mismatch would otherwise only
surface as an unsatisfiable resolution when a release builds wheels.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
PROJECTS = ("cli", "tools/ods", "tools/ods-audit")


def main() -> int:
    lines: list[str] = (HERE / "build-constraints.in").read_text().splitlines()
    expected: set[str] = {
        stripped
        for stripped in (line.strip() for line in lines)
        if stripped and not stripped.startswith("#")
    }
    failed: bool = False
    for project in PROJECTS:
        pyproject = REPO_ROOT / project / "pyproject.toml"
        with pyproject.open("rb") as handle:
            requires: set[str] = set(tomllib.load(handle)["build-system"]["requires"])
        if requires != expected:
            failed = True
            print(f"{pyproject}: build requirements differ from build-constraints.in")
            for req in sorted(requires ^ expected):
                side = "pyproject.toml" if req in requires else "build-constraints.in"
                print(f"  only in {side}: {req}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
