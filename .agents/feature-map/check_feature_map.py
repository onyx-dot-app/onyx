#!/usr/bin/env python3
"""Checks that the feature map is well formed and that every repo path it cites exists.

Runs as a pre-commit hook on every commit, so a PR that renames or deletes a file a
component document cites fails until the document is updated in the same PR.
Intentional non-paths (build outputs, runtime paths, shorthand, statements that a
file does not exist) go in `path-allowlist.txt`.
"""

import re
import subprocess
import sys
from pathlib import Path

MAP_DIR = Path(__file__).resolve().parent
REPO_ROOT = MAP_DIR.parent.parent
COMPONENTS_DIR = MAP_DIR / "components"
ALLOWLIST = MAP_DIR / "path-allowlist.txt"

SECTION_COUNT = 9
VERIFIED_LINE = re.compile(
    r"^\*\*Verified against:\*\* `[0-9a-f]{7,40}` \(\d{4}-\d{2}-\d{2}\)$", re.MULTILINE
)
SECTION_HEADING = re.compile(r"^## (\d+)\. ", re.MULTILINE)
CODE_SPAN = re.compile(r"`([^`\n]+)`")
WIKI_LINK = re.compile(r"\[\[([a-z][a-z0-9-]*)\]\]")
SLUG = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
INDEX_LINK = re.compile(r"\(components/([a-z0-9-]+)\.md\)")
PATH_SUFFIX = re.compile(
    r"\.(py|ts|tsx|js|mjs|json|md|yaml|yml|toml|go|rs|sh|txt|html|css|template)$"
)
# Roots that a short path such as `db/models.py` or `lib/utils.ts` resolves against.
PATH_ROOTS = (
    "",
    "backend/",
    "backend/onyx/",
    "backend/ee/",
    "backend/ee/onyx/",
    "backend/onyx/server/",
    "backend/onyx/server/features/",
    "backend/onyx/server/features/build/",
    "backend/onyx/db/",
    "backend/onyx/connectors/",
    "backend/onyx/tools/",
    "backend/onyx/tools/tool_implementations/",
    "backend/onyx/context/search/",
    "backend/onyx/background/celery/tasks/",
    "backend/tests/",
    "backend/alembic/versions/",
    "web/",
    "web/src/",
    "web/src/app/",
    "web/src/app/craft/",
    "web/src/lib/",
    "extensions/chrome/",
    "extensions/chrome/src/",
    "desktop/",
    "widget/",
    "mobile/",
    "mobile/src/",
    "deployment/",
    "cli/",
)


def _repo_paths() -> tuple[set[str], set[str], dict[str, list[str]]]:
    files = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    dirs: set[str] = set()
    by_name: dict[str, list[str]] = {}
    for path in files:
        parts = path.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
        by_name.setdefault(parts[-1], []).append(path)
    return set(files), dirs, by_name


def _allowlist() -> set[tuple[str, str]]:
    entries: set[tuple[str, str]] = set()
    if not ALLOWLIST.exists():
        return entries
    for raw in ALLOWLIST.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        doc, _, token = line.partition(": ")
        entries.add((doc.strip(), token.strip()))
    return entries


def _looks_like_path(token: str) -> str | None:
    if any(c.isspace() for c in token):
        return None
    path = token.split(":")[0].rstrip("/").rstrip(",").strip("()")
    if "/" not in path or path.startswith(("http", "/")):
        return None
    if any(c in path for c in "{*<$[") or "..." in path:
        return None
    if not PATH_SUFFIX.search(path) and not token.endswith("/"):
        return None
    return path


def _path_exists(
    path: str, files: set[str], dirs: set[str], by_name: dict[str, list[str]]
) -> bool:
    if any(root + path in files or root + path in dirs for root in PATH_ROOTS):
        return True
    name = path.rsplit("/", 1)[-1]
    return any(candidate.endswith(path) for candidate in by_name.get(name, []))


def check() -> list[str]:
    errors: list[str] = []
    components = sorted(COMPONENTS_DIR.glob("*.md"))
    names = {doc.stem for doc in components}

    for doc in components:
        text = doc.read_text()
        rel = doc.relative_to(MAP_DIR).as_posix()
        numbers = [int(n) for n in SECTION_HEADING.findall(text)]
        if numbers != list(range(1, SECTION_COUNT + 1)):
            errors.append(
                f"{rel}: sections must be `## 1.` to `## {SECTION_COUNT}.` in order, found {numbers}"
            )
        if not VERIFIED_LINE.search(text):
            errors.append(
                f"{rel}: missing a `**Verified against:** `<sha>` (YYYY-MM-DD)` line"
            )

    index_text = (MAP_DIR / "INDEX.md").read_text()
    errors.extend(
        f"INDEX.md: component `{name}` is not listed"
        for name in sorted(names - set(INDEX_LINK.findall(index_text)))
    )

    for line in (MAP_DIR / "PATHS.md").read_text().splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2 or cells[1].startswith(("**", "Component", "---")):
            continue
        parts = [part.strip() for part in cells[1].split(",")]
        # A cell of prose (a note about the path) names no component to check.
        if not all(SLUG.match(part) for part in parts):
            continue
        errors.extend(
            f"PATHS.md: unknown component `{name}`"
            for name in parts
            if name not in names
        )

    files, dirs, by_name = _repo_paths()
    allowed = _allowlist()
    for doc in sorted(MAP_DIR.rglob("*.md")):
        rel = doc.relative_to(MAP_DIR).as_posix()
        for number, line in enumerate(doc.read_text().splitlines(), start=1):
            errors.extend(
                f"{rel}:{number}: unknown component link [[{link}]]"
                for link in WIKI_LINK.findall(CODE_SPAN.sub("", line))
                if link not in names
            )
            for token in CODE_SPAN.findall(line):
                path = _looks_like_path(token)
                if path is None or (rel, token) in allowed:
                    continue
                if not _path_exists(path, files, dirs, by_name):
                    errors.append(
                        f"{rel}:{number}: `{token}` does not exist in the repo. "
                        "Update the reference, or add it to path-allowlist.txt if it is not a repo path."
                    )
    return errors


def main() -> int:
    errors = check()
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        print(
            f"\nfeature map: {len(errors)} problem(s). See .agents/feature-map/README.md.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
