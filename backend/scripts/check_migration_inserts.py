#!/usr/bin/env python3
"""Fail when a tenant-chain migration inserts rows outside downgrade.

A seed row written by a revision lands in the template snapshot and from
there in every cloned tenant, while existing tenants and the single-tenant
setup path never see it. New revisions keep to schema changes and fixes to
rows that already exist. Revisions at or before the marker are history and
are left alone by walking the chain from it.

Usage, from the repo root:
    python3 backend/scripts/check_migration_inserts.py backend/alembic/versions/<rev>_*.py ...
"""

import re
import sys
from pathlib import Path

# Head of the chain when the rule landed. Everything at or before it is history.
_INSERTS_BANNED_AFTER = "25053020dd5a"
# A backfill that only moves rows which already exist opts out per line.
ALLOW_MARKER = "migration-inserts: allow"
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_VERSIONS_DIR = _BACKEND_DIR / "alembic" / "versions"
_REVISION_LINE = re.compile(r'^revision(?:\s*:[^=]+)?\s*=\s*"(\w+)"', re.MULTILINE)
_DOWN_REVISION_LINE = re.compile(r"^down_revision(?:\s*:[^=]+)?\s*=(.*)$", re.MULTILINE)
_REVISION_ID = re.compile(r'"(\w+)"')
# downgrade may restore a seed it removed. Everything else is scanned, so
# module-level helpers and import aliases cannot hide an insert.
_DOWNGRADE_BODY = re.compile(r"^def downgrade\b.*?(?=^\S|\Z)", re.MULTILINE | re.DOTALL)
# `insert as pg_insert` renames the construct, so calls are matched by alias.
_INSERT_ALIAS = re.compile(r"\bimport\b.*\binsert\s+as\s+(\w+)")
_INSERT_PATTERNS = (
    re.compile(r"\bINSERT\s+INTO\b|\bINSERT\s*$", re.IGNORECASE),
    re.compile(r"\bop\.bulk_insert\("),
    # Bare, module-qualified and table-method forms of the Core construct.
    re.compile(r"(?<!\w)insert\("),
    # An ORM session in a migration exists to write rows, whatever it is named.
    re.compile(r"\b(?:Session|sessionmaker)\("),
    re.compile(r"\.(?:add_all|merge|bulk_save_objects|bulk_insert_mappings)\("),
    re.compile(r"\b\w*session\.add\("),
)


def _downgrade_lines(source: str) -> set[int]:
    skipped: set[int] = set()
    for match in _DOWNGRADE_BODY.finditer(source):
        first_line = source.count("\n", 0, match.start()) + 1
        last_line = source.count("\n", 0, match.end() - 1) + 1
        skipped.update(range(first_line, last_line + 1))
    return skipped


def _insert_patterns(source: str) -> list[re.Pattern[str]]:
    aliases = _INSERT_ALIAS.findall(source)
    if not aliases:
        return list(_INSERT_PATTERNS)
    alias_call = re.compile(rf"(?<!\w)(?:{'|'.join(map(re.escape, aliases))})\(")
    return [*_INSERT_PATTERNS, alias_call]


def find_inserts(source: str) -> list[int]:
    """One-based line numbers outside downgrade where a row insert appears."""
    skipped = _downgrade_lines(source)
    patterns = _insert_patterns(source)
    return [
        number
        for number, line in enumerate(source.splitlines(), start=1)
        if number not in skipped
        and ALLOW_MARKER not in line
        and any(pattern.search(line) for pattern in patterns)
    ]


def _parents(source: str) -> list[str]:
    """Revision ids named on the down_revision line, one or several at a merge."""
    match = _DOWN_REVISION_LINE.search(source)
    return _REVISION_ID.findall(match.group(1)) if match else []


def revisions_before_rule() -> set[str]:
    """Walk the chain from the marker to base by reading the version files.

    Parsed rather than loaded through alembic so the hook runs without the
    backend on the import path."""
    parents_by_revision: dict[str, list[str]] = {}
    for path in _VERSIONS_DIR.glob("*.py"):
        source = path.read_text()
        match = _REVISION_LINE.search(source)
        if match:
            parents_by_revision[match.group(1)] = _parents(source)
    exempt: set[str] = set()
    pending = [_INSERTS_BANNED_AFTER]
    while pending:
        revision = pending.pop()
        if revision in exempt:
            continue
        exempt.add(revision)
        pending.extend(parents_by_revision.get(revision, []))
    return exempt


def main(paths: list[str]) -> int:
    chain_files = [
        Path(path) for path in paths if Path(path).resolve().parent == _VERSIONS_DIR
    ]
    if not chain_files:
        return 0
    exempt = revisions_before_rule()
    failures: list[str] = []
    for path in chain_files:
        source = path.read_text()
        match = _REVISION_LINE.search(source)
        if match and match.group(1) in exempt:
            continue
        failures.extend(f"{path}:{line}" for line in find_inserts(source))
    if not failures:
        return 0
    print("Migrations do not insert rows. Seed defaults from application code instead:")
    print("\n".join(f"  {failure}" for failure in failures))
    print(f"A backfill of rows that already exist may carry `# {ALLOW_MARKER}`.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
