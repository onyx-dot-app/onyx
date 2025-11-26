#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import pathlib
import shlex
import subprocess
import sys
import typing
from contextlib import contextmanager

# Add backend/ to the PYTHONPATH
if __name__ == "__main__":
    sys.path.append(str(pathlib.Path(__file__).parent.parent))

from scripts.lib import logger as _logger


logger = _logger.getLogger()


class Args(typing.NamedTuple):
    check: bool


@contextmanager
def in_toplevel_dir() -> typing.Generator[None, None, None]:
    """Temporarily change the working directory to the repository's toplevel directory."""
    prev_dir = os.getcwd()
    toplevel_dir = pathlib.Path(__file__).parent.parent.parent
    try:
        os.chdir(toplevel_dir)
        yield
    finally:
        os.chdir(prev_dir)


def _exec(cmd: str, **kwargs: typing.Any) -> int:
    """Subprocess.run wrapper with sensible defaults."""
    kwargs.setdefault("check", True)
    kwargs.setdefault("stdout", subprocess.DEVNULL)
    logger.debug("Running: %s" % cmd)
    return subprocess.run(shlex.split(cmd), **kwargs).returncode


def _assert_up_to_date(filepath: str) -> None:
    """Checks the given filepath (relative to script dir) for changes."""
    if _exec(f"git diff --quiet {filepath}", check=False) == 0:
        return
    logger.error(f"{filepath} is out of date.", extra={"file": filepath, "line": 1})
    logger.info("Run:\n\t$ ./backend/scripts/compile_requirements.py")
    logger.info(
        "For additional help, see https://github.com/onyx-dot-app/onyx/tree/main/backend/requirements/README.md"
    )
    raise SystemExit(1)


def parse_args() -> Args:
    parser = argparse.ArgumentParser(
        description="Compile Python requirements from pyproject.toml using uv.",
        epilog="See also: https://github.com/onyx-dot-app/onyx/tree/main/backend/requirements/README.md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check for lockfile drift before running compilation",
    )
    args = parser.parse_args()
    return Args(check=args.check)


def main() -> int:
    args = parse_args()
    with in_toplevel_dir():
        if (
            args.check
            and _exec("git diff --quiet uv.lock backend/requirements/", check=False)
            != 0
        ):
            logger.error("Changes detected before running uv lock and export.")
            logger.info(
                "Please commit or stash your changes before running this script with --check."
            )
            raise SystemExit(1)

        logger.info("Locking dependencies from pyproject.toml...")
        _exec("uv lock")
        if args.check:
            _assert_up_to_date("uv.lock")

        for arg, output in [
            ("--extra backend", "default"),
            ("--group dev", "dev"),
            ("--extra ee", "ee"),
            ("--extra model_server", "model_server"),
        ]:
            output_filename = f"backend/requirements/{output}.txt"
            _exec(
                f"uv export --no-emit-project --no-default-groups --no-hashes {arg} -o {output_filename}"
            )
            if args.check:
                _assert_up_to_date(output_filename)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
