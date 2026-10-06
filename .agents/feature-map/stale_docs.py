#!/usr/bin/env python3
"""Reminds an agent to update the feature map when it changed a component's code.

Given the files a branch changed, this maps each file to its components through
PATHS.md (longest prefix wins) and prints a reminder for every component whose code
changed but whose document did not. The agent decides whether the change alters
anything the document states. The agent Stop hook
(`.agents/hooks/pre_commit_on_stop.py`) runs this; with `--session`, each component
is named at most once per session.

Usage: stale_docs.py [--session ID] FILE [FILE ...]
"""

import argparse
import fnmatch
import json
import tempfile
from pathlib import Path

from check_feature_map import (
    CODE_SPAN,
    COMPONENTS_DIR,
    MAP_DIR,
    PATH_ROOTS,
    SLUG,
    _repo_paths,
)

_MAX_FILES_SHOWN = 3
# Changes here never alter what a component document states.
_IGNORED_PREFIXES = (".agents/", "backend/tests/", "web/tests/", "mobile/e2e/")
_IGNORED_MARKERS = ("/tests/", "/__tests__/", ".test.", ".spec.")


def _resolve(
    token: str, base: str | None, files: set[str], dirs: set[str]
) -> list[str]:
    path = token.split(":")[0].rstrip("/")
    candidates = ([f"{base}/{path}"] if base else []) + [
        root + path for root in PATH_ROOTS
    ]
    if "*" in path:
        # Keep the pattern, so a new file that matches it is owned too. The parent
        # may itself be a pattern (`*/onyxbot/...`), so match it against real dirs.
        return next(
            ([c] for c in candidates if fnmatch.filter(dirs, c.rsplit("/", 1)[0])),
            [],
        )
    return next(([c] for c in candidates if c in files or c in dirs), [])


def _ownership(names: set[str], changed: list[str]) -> list[tuple[str, list[str]]]:
    """(owned repo path, components) for every PATHS.md row that names components."""
    files, dirs, _ = _repo_paths()
    # A deleted file is gone from the index but its PATHS.md row still owns it.
    files |= set(changed)
    dirs |= {p.rsplit("/", i)[0] for p in changed for i in range(1, p.count("/") + 1)}
    owned: list[tuple[str, list[str]]] = []
    for line in (MAP_DIR / "PATHS.md").read_text().splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2:
            continue
        components = [part.strip() for part in cells[1].split(",")]
        if not all(SLUG.match(part) and part in names for part in components):
            continue
        base: str | None = None
        for token in CODE_SPAN.findall(cells[0]):
            for path in _resolve(token, base, files, dirs):
                owned.append((path, components))
                if base is None:
                    base = path if path in dirs else path.rsplit("/", 1)[0]
    return owned


def _owners(path: str, owned: list[tuple[str, list[str]]]) -> list[str]:
    best = -1
    owners: list[str] = []
    for prefix, components in owned:
        if "*" in prefix:
            if not fnmatch.fnmatch(path, prefix):
                continue
        elif path != prefix and not path.startswith(prefix + "/"):
            continue
        if len(prefix) > best:
            best, owners = len(prefix), list(components)
        elif len(prefix) == best:
            owners.extend(c for c in components if c not in owners)
    return owners


def stale_components(changed: list[str]) -> dict[str, list[str]]:
    names = {doc.stem for doc in COMPONENTS_DIR.glob("*.md")}
    updated_docs = {
        Path(path).stem
        for path in changed
        if path.startswith(".agents/feature-map/components/")
    }
    owned = _ownership(names, changed)
    stale: dict[str, list[str]] = {}
    for path in changed:
        if path.startswith(_IGNORED_PREFIXES) or any(
            m in path for m in _IGNORED_MARKERS
        ):
            continue
        for component in _owners(path, owned):
            if component not in updated_docs:
                stale.setdefault(component, []).append(path)
    return stale


def _already_reminded(session: str) -> tuple[Path, set[str]]:
    record = Path(tempfile.gettempdir()) / f"onyx-feature-map-reminders-{session}.json"
    try:
        return record, set(json.loads(record.read_text()))
    except (OSError, ValueError):
        return record, set()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()

    stale = stale_components(args.files)
    if args.session:
        record, reminded = _already_reminded(args.session)
        stale = {c: paths for c, paths in stale.items() if c not in reminded}
        if stale:
            record.write_text(json.dumps(sorted(reminded | set(stale))))
    if not stale:
        return 0

    lines = [
        "Feature map: this branch changes code owned by these components, but not their documents:"
    ]
    for component, paths in sorted(stale.items()):
        shown = ", ".join(paths[:_MAX_FILES_SHOWN])
        more = (
            f" (+{len(paths) - _MAX_FILES_SHOWN} more)"
            if len(paths) > _MAX_FILES_SHOWN
            else ""
        )
        lines.append(
            f"- {component} (.agents/feature-map/components/{component}.md): {shown}{more}"
        )
    lines.append(
        "If your change alters something a document states (an endpoint, permission, env var, "
        "default, data model field, section 4 behaviour or a section 5 contract), update that "
        "document now. If not, no action is needed. Each component is named once per session."
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
