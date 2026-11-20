#!/usr/bin/env python3
"""Fail when a connector in the registry has no customer docs page.

A connector is a `DocumentSource` key of `CONNECTOR_CLASS_MAP` in
`backend/onyx/connectors/registry.py`. Its page is found under
`documentation/admins/connectors/official/` as `<source>.mdx`, a `<source>/`
folder, or `<group>/<source>.mdx`. A source whose page has another name, or
that has no page on purpose, is listed in `connector_docs.txt` as
`<source> <page path under official/>` or `<source> none: <reason>`.

Usage, from the repo root:
    python3 backend/lint/check_connector_docs.py
"""

import ast
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO_ROOT / "backend/onyx/connectors/registry.py"
_DOCS = _REPO_ROOT / "documentation/admins/connectors/official"
_MAP_PATH = Path(__file__).resolve().parent / "connector_docs.txt"


def registered_sources(source: str, constants: dict[str, str]) -> list[str]:
    """The source values of the `DocumentSource.X` keys in the registry."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Dict):
            found.extend(
                constants[key.attr]
                for key in node.keys
                if isinstance(key, ast.Attribute)
                and isinstance(key.value, ast.Name)
                and key.value.id == "DocumentSource"
                and key.attr in constants
            )
    return sorted(set(found))


def source_constants(source: str) -> dict[str, str]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == "DocumentSource":
            return {
                stmt.targets[0].id: stmt.value.value
                for stmt in node.body
                if isinstance(stmt, ast.Assign)
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            }
    raise RuntimeError("Bug: DocumentSource is not in configs/constants.py")


def parse_map(text: str) -> tuple[dict[str, str], list[str]]:
    """`{source: page or "none"}` and the errors in the file."""
    entries: dict[str, str] = {}
    errors: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        source, _, target = line.partition(" ")
        target = target.strip()
        if not target or (target.startswith("none") and not target[5:].strip()):
            errors.append(
                f"connector_docs.txt:{number}: give a page or 'none: <reason>'"
            )
        elif source in entries:
            errors.append(f"connector_docs.txt:{number}: {source} is listed twice")
        else:
            entries[source] = "none" if target.startswith("none") else target
    return entries, errors


def has_page(docs: Path, source: str) -> bool:
    return (
        (docs / f"{source}.mdx").is_file()
        or (docs / source).is_dir()
        or any(docs.glob(f"*/{source}.mdx"))
    )


def check(sources: list[str], entries: dict[str, str], docs: Path) -> list[str]:
    errors: list[str] = []
    for source in sources:
        target = entries.get(source)
        if target == "none":
            continue
        if target is not None:
            if not (docs / target).exists():
                errors.append(
                    f"connector_docs.txt: {source} points to a missing page {target}"
                )
        elif not has_page(docs, source):
            errors.append(
                f"Connector '{source}' has no page in documentation/admins/connectors/official/. "
                "Add one, or list it in backend/lint/connector_docs.txt."
            )
    errors.extend(
        f"connector_docs.txt: {source} is not a registered connector"
        for source in sorted(set(entries) - set(sources))
    )
    return errors


def main() -> int:
    constants = source_constants(
        (_REPO_ROOT / "backend/onyx/configs/constants.py").read_text()
    )
    sources = registered_sources(_REGISTRY.read_text(), constants)
    entries, errors = parse_map(_MAP_PATH.read_text() if _MAP_PATH.exists() else "")
    errors += check(sources, entries, _DOCS)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
