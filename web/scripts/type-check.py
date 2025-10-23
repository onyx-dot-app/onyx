#!/usr/bin/env python3
"""Run TypeScript type checking for the web frontend.

Note: TypeScript type checking requires checking the entire project
due to type dependencies across files. We use --incremental to cache
results and speed up subsequent checks.
"""
import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Run TypeScript type-check in the web directory.

    Args from pre-commit are ignored since tsc must check the full project,
    but the files filter ensures this only runs when TS/TSX files change.
    """
    # Get the web directory (parent of scripts directory)
    web_dir = Path(__file__).parent.parent

    # Run the type-check npm script (which includes --incremental flag)
    result = subprocess.run(
        ["npm", "run", "type-check"],
        cwd=web_dir,
        check=False,
    )

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
