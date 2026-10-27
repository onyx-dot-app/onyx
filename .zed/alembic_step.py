"""Prompt for N, then move the schema up or down by N alembic revisions.

An empty answer goes all the way: `head` for up, `base` for down.

Zed joins task `args` into one command line for the user's shell without
quoting, so the prompt lives here rather than in shell syntax that only some
shells (sh, bash) accept.

Usage:
    alembic_step.py (up | down)
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ZED_DIR = Path(__file__).resolve().parent

DIRECTIONS = {
    "up": ("upgrade", "head", "+"),
    "down": ("downgrade", "base", "-"),
}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in DIRECTIONS:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} (up | down)")

    command, default, sign = DIRECTIONS[sys.argv[1]]
    answer = input(f"Revisions to {command} (empty = {default}): ").strip()
    if not answer:
        revision = default
    elif answer.isdigit() and int(answer) > 0:
        revision = f"{sign}{int(answer)}"
    else:
        raise SystemExit(f"expected a positive whole number, got {answer!r}")

    launcher = ZED_DIR / "dotenv_launch.py"
    sys.argv = [
        str(launcher),
        ".vscode/.env",
        "--module",
        "alembic",
        command,
        revision,
    ]
    runpy.run_path(str(launcher), run_name="__main__")


if __name__ == "__main__":
    main()
