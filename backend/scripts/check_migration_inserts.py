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

import ast
import re
import sys
from pathlib import Path

# Head of the chain when the rule landed. Everything at or before it is history.
_INSERTS_BANNED_AFTER = "25053020dd5a"
# A backfill that only moves rows which already exist opts out per statement.
ALLOW_MARKER = "migration-inserts: allow"
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_VERSIONS_DIR = _BACKEND_DIR / "alembic" / "versions"
_REVISION_LINE = re.compile(r'^revision(?:\s*:[^=]+)?\s*=\s*"(\w+)"', re.MULTILINE)
_DOWN_REVISION_LINE = re.compile(r"^down_revision(?:\s*:[^=]+)?\s*=(.*)$", re.MULTILINE)
_REVISION_ID = re.compile(r'"(\w+)"')
_INSERT_SQL = re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)
_SESSION_WRITES = {"add_all", "merge", "bulk_save_objects", "bulk_insert_mappings"}


class _InsertFinder(ast.NodeVisitor):
    """Collects row writes, erring toward flagging: any SQL text that spells
    INSERT INTO counts, and the allow marker clears the rare false positive."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self._inserts = {"insert"}
        self._sessions: set[str] = set()
        self._statement: ast.stmt | None = None
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

    def _is_session(self, receiver: ast.expr) -> bool:
        if not isinstance(receiver, ast.Name):
            return False
        return receiver.id in self._sessions or receiver.id.endswith("session")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # downgrade may restore a seed it removed.
        if node.name == "downgrade":
            return
        self._sessions.update(
            arg.arg
            for arg in node.args.args + node.args.kwonlyargs
            if isinstance(arg.annotation, ast.Name) and arg.annotation.id == "Session"
        )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._inserts.update(
            alias.asname
            for alias in node.names
            if alias.name == "insert" and alias.asname
        )

    def visit_Expr(self, node: ast.Expr) -> None:
        # A docstring may describe inserts without performing one.
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in self._inserts:
            self._flag(node)
        elif isinstance(func, ast.Attribute):
            if func.attr == "insert" and not _is_list_insert(node):
                self._flag(node)
            elif func.attr == "bulk_insert" or func.attr in _SESSION_WRITES:
                self._flag(node)
            elif func.attr == "add" and self._is_session(func.value):
                self._flag(node)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _INSERT_SQL.search(node.value):
            self._flag(node)


def _is_list_insert(node: ast.Call) -> bool:
    """`items.insert(0, x)` takes an index first, the Core construct never does."""
    return bool(node.args) and isinstance(node.args[0], ast.Constant)


def find_inserts(source: str) -> list[int]:
    """One-based line numbers of row writes outside downgrade."""
    finder = _InsertFinder(source.splitlines())
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
