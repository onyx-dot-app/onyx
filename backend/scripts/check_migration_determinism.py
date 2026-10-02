#!/usr/bin/env python3
"""Fail when a tenant-chain migration seeds rows with run-dependent values.

The template schema is migrated once, snapshotted and cloned into every new
tenant, and the deploy gate compares it with a fresh build of the chain. A
row a revision inserts must therefore be the same on every schema: fixed ids
and literal values, no generated uuids, clock reads, randomness or env reads.
Schema defaults such as server_default now() are not rows and are fine.
Revisions at or before the marker are history and are left alone by walking
the chain from it.

Usage, from the repo root:
    python3 backend/scripts/check_migration_determinism.py backend/alembic/versions/<rev>_*.py ...
"""

import ast
import re
import sys
from pathlib import Path

# Head of the chain when the rule landed. Everything at or before it is history.
_RULE_LANDED_AT = "25053020dd5a"
# A deliberate exception, such as a value the gate is known to ignore, opts out per statement.
ALLOW_MARKER = "migration-determinism: allow"
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_VERSIONS_DIR = _BACKEND_DIR / "alembic" / "versions"
_REVISION_LINE = re.compile(r'^revision(?:\s*:[^=]+)?\s*=\s*"(\w+)"', re.MULTILINE)
_DOWN_REVISION_LINE = re.compile(r"^down_revision(?:\s*:[^=]+)?\s*=(.*)$", re.MULTILINE)
_REVISION_ID = re.compile(r'"(\w+)"')
_INSERT_SQL = re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)
# Only inside an INSERT statement: a schema default or an UPDATE may use these.
_RUN_DEPENDENT_SQL = re.compile(
    r"\b(?:now|clock_timestamp|gen_random_uuid|uuid_generate_v\d|random)\s*\(|\bcurrent_timestamp\b",
    re.IGNORECASE,
)
# Run-dependent anywhere in a migration, since the value only exists to be written.
_RUN_DEPENDENT_CALLS = {
    "uuid1",
    "uuid4",
    "utcnow",
    "time",
    "getenv",
    "random",
    "randint",
    "choice",
    "token_hex",
    "token_urlsafe",
}
_CLOCKS = {"datetime", "date"}
# Run-dependent unless it defines a column default, where it is schema, not a row.
_DEFAULT_CALLS = {"now", "gen_random_uuid"}
_SCHEMA_CALLS = {"Column", "create_table", "add_column", "alter_column"}


class _RunDependentFinder(ast.NodeVisitor):
    """Collects values that differ between runs, erring toward flagging. The
    allow marker clears the rare deliberate exception."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self._statement: ast.stmt | None = None
        self._schema_depth = 0
        self.found: set[int] = set()

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.stmt):
            self._statement = node
        super().visit(node)

    def _flag(self, node: ast.expr) -> None:
        """The marker exempts one node: on its own lines or its statement's first."""
        if self._statement is None:
            return
        end = node.end_lineno or node.lineno
        marked = [
            self._lines[self._statement.lineno - 1],
            *self._lines[node.lineno - 1 : end],
        ]
        if not any(ALLOW_MARKER in line for line in marked):
            self.found.add(node.lineno)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # downgrade may restore what it removed, with whatever values it had.
        if node.name != "downgrade":
            self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        # A docstring may describe values without producing one.
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _terminal_name(node.value) == "environ":
            self._flag(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _terminal_name(node.func)
        receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
        if name in _RUN_DEPENDENT_CALLS or (
            name == "now" and _terminal_name(receiver) in _CLOCKS
        ):
            self._flag(node)
        elif name in _DEFAULT_CALLS and not self._schema_depth:
            self._flag(node)
        elif name == "get" and _terminal_name(receiver) == "environ":
            self._flag(node)
        schema = name in _SCHEMA_CALLS
        self._schema_depth += schema
        self.generic_visit(node)
        self._schema_depth -= schema

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str) or not _INSERT_SQL.search(node.value):
            return
        if _RUN_DEPENDENT_SQL.search(node.value):
            self._flag(node)


def _terminal_name(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def find_run_dependent_values(source: str) -> list[int]:
    """One-based line numbers of run-dependent values outside downgrade."""
    finder = _RunDependentFinder(source.splitlines())
    finder.visit(ast.parse(source))
    return sorted(finder.found)


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
    pending = [_RULE_LANDED_AT]
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
        failures.extend(f"{path}:{line}" for line in find_run_dependent_values(source))
    if not failures:
        return 0
    print(
        "Migration rows must be the same on every schema. Use fixed ids and literal values:"
    )
    print("\n".join(f"  {failure}" for failure in failures))
    print(f"A deliberate exception may carry `# {ALLOW_MARKER}`.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
