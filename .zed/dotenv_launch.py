"""In-process `envFile` shim for Zed's debugger.

Zed passes debug configurations straight through to debugpy, and debugpy has no
`envFile` field -- that field is a VS Code Python-extension feature, resolved
before debugpy ever sees the request. Without this shim, every launch config
ported from `.vscode/launch.json` starts with an empty environment.

This script loads the env file into the current process, then runs the real
target in that same process. One process means breakpoints, stepping and
`justMyCode` behave exactly as they do under VS Code.

Usage:
    dotenv_launch.py <env-file> --module <name> [args...]
    dotenv_launch.py <env-file> --program <path> [args...]

Values already in the environment win, which matches VS Code, where `env`
overrides `envFile`.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


def resolve_env_file(raw: str) -> Path | None:
    """Find the env file relative to the CWD, then to the repo root."""
    candidates = (
        [Path(raw)] if Path(raw).is_absolute() else [Path(raw), REPO_ROOT / raw]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def main() -> None:
    argv = sys.argv[1:]
    if len(argv) < 3:
        raise SystemExit(
            f"usage: {Path(sys.argv[0]).name} <env-file> "
            "(--module <name> | --program <path>) [args...]"
        )

    raw_env_file, kind, target = argv[0], argv[1], argv[2]
    target_args = argv[3:]

    env_file = resolve_env_file(raw_env_file)
    if env_file is None:
        print(
            f"dotenv_launch: env file not found, starting without it: {raw_env_file}",
            file=sys.stderr,
        )
    else:
        load_dotenv(env_file, override=False)

    if kind == "--module":
        # Reproduce `python -m`, which puts the working directory on sys.path.
        sys.path.insert(0, "")
        sys.argv = [target, *target_args]
        runpy.run_module(target, run_name="__main__", alter_sys=True)
    elif kind == "--program":
        script = Path(target).resolve()
        sys.path.insert(0, str(script.parent))
        sys.argv = [str(script), *target_args]
        runpy.run_path(str(script), run_name="__main__")
    else:
        raise SystemExit(
            f"unknown target kind {kind!r}; expected --module or --program"
        )


if __name__ == "__main__":
    main()
