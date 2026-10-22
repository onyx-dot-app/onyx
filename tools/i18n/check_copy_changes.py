"""Reject English copy changes whose translations have not changed."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

CATALOG_PATH: Path = Path("web/src/i18n/messages")


def flatten(value: object, prefix: str = "") -> dict[str, str]:
    if isinstance(value, str):
        return {prefix: value}
    if not isinstance(value, dict):
        raise ValueError(f"Invalid message at {prefix}")
    messages: dict[str, str] = {}
    for key, child in value.items():
        if not isinstance(key, str):
            raise ValueError("Message keys must be strings")
        messages.update(flatten(child, f"{prefix}.{key}" if prefix else key))
    return messages


def read_catalog(path: Path, base: str | None = None) -> dict[str, str]:
    source: str = (
        subprocess.check_output(["git", "show", f"{base}:{path.as_posix()}"], text=True)
        if base
        else path.read_text()
    )
    return flatten(json.loads(source))


def default_base() -> str:
    """Check working edits against HEAD, or the last commit in a clean checkout."""
    changes: str = subprocess.check_output(
        ["git", "status", "--porcelain", "--", CATALOG_PATH.as_posix()], text=True
    )
    if changes:
        return "HEAD"
    parent: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^"],
        capture_output=True,
        text=True,
        check=False,
    )
    return "HEAD^" if parent.returncode == 0 else "HEAD"


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    args: argparse.Namespace = parser.parse_args()
    base: str = args.base or os.environ.get("PRE_COMMIT_FROM_REF") or default_base()
    previous: dict[str, str] = read_catalog(CATALOG_PATH / "en.json", base)
    current: dict[str, str] = read_catalog(CATALOG_PATH / "en.json")
    changed: list[str] = [
        key for key, text in current.items() if previous.get(key) != text
    ]
    if not changed:
        return 0
    baseline_paths: set[str] = set(
        subprocess.check_output(
            [
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                base,
                "--",
                CATALOG_PATH.as_posix(),
            ],
            text=True,
        ).splitlines()
    )
    failures: list[str] = []
    for path in sorted(CATALOG_PATH.glob("*.json")):
        if path.name == "en.json":
            continue
        old: dict[str, str] = (
            read_catalog(path, base) if path.as_posix() in baseline_paths else {}
        )
        new: dict[str, str] = read_catalog(path)
        failures.extend(
            f"{path.stem}: {key}"
            for key in changed
            if key not in new or new[key] == old.get(key)
        )
    if failures:
        print("English copy changed without corresponding translation updates:")
        print("\n".join(f"  {failure}" for failure in failures))
        print(
            "Update each listed translation. This check cannot assess translation quality."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
