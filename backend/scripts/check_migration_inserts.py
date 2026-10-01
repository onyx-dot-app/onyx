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
# downgrade may restore a seed it removed, so it is the only body not visited.
_INSERT_SQL = re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)
_SESSION_FACTORIES = {"Session", "sessionmaker"}
_SESSION_WRITES = {"add_all", "merge", "bulk_save_objects", "bulk_insert_mappings"}


class _InsertFinder(ast.NodeVisitor):
    """Collects the statements that write rows.

    Names bound to the insert construct and to ORM sessions are tracked per
    scope, so an aliased import, a sessionmaker factory or a short variable
    name cannot hide a write, and a set named like a session elsewhere cannot
    produce one."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self._inserts: set[str] = set()
        self._sessions: list[set[str]] = [set()]
        self._statement: ast.stmt | None = None
        self.found: set[int] = set()

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.stmt):
            self._statement = node
        super().visit(node)

    def _flag(self, node: ast.expr) -> None:
        """The marker exempts one node: on its own lines or its statement's first."""
        statement = self._statement
        if statement is None:
            return
        end = node.end_lineno or node.lineno
        marked = [
            self._lines[statement.lineno - 1],
            *self._lines[node.lineno - 1 : end],
        ]
        if any(ALLOW_MARKER in line for line in marked):
            return
        self.found.add(node.lineno)

    def _is_session_call(self, node: ast.expr) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name):
            return func.id in _SESSION_FACTORIES or func.id in self._sessions[-1]
        return isinstance(func, ast.Attribute) and func.attr in _SESSION_FACTORIES

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == "downgrade":
            return
        scope = set(self._sessions[-1])
        # A helper taking a session parameter writes through that name.
        scope.update(
            arg.arg
            for arg in node.args.args + node.args.kwonlyargs
            if arg.annotation is not None and _names_session(arg.annotation)
        )
        self._sessions.append(scope)
        self.generic_visit(node)
        self._sessions.pop()

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            bound = alias.asname or alias.name
            if alias.name == "insert":
                self._inserts.add(bound)
            if alias.name in _SESSION_FACTORIES:
                self._sessions[-1].add(bound)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._is_session_call(node.value):
            self._sessions[-1].update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if self._is_session_call(item.context_expr) and isinstance(
                item.optional_vars, ast.Name
            ):
                self._sessions[-1].add(item.optional_vars.id)
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        # A docstring may describe inserts without performing one.
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and (
            func.id == "insert" or func.id in self._inserts
        ):
            self._flag(node)
        elif isinstance(func, ast.Attribute):
            # Receivers named like a session count even when bound elsewhere.
            receiver_is_session = isinstance(func.value, ast.Name) and (
                func.value.id in self._sessions[-1] or func.value.id.endswith("session")
            )
            if func.attr == "insert" and not _is_list_insert(node):
                self._flag(node)
            elif func.attr == "bulk_insert" or func.attr in _SESSION_WRITES:
                self._flag(node)
            elif func.attr == "add" and receiver_is_session:
                self._flag(node)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str):
            return
        if _INSERT_SQL.search(_executable_sql(node.value)):
            self._flag(node)


_EXECUTE = re.compile(r"\bEXECUTE\b", re.IGNORECASE)


def _executable_sql(sql: str) -> str:
    """Blank out comments and quoted text that Postgres does not run.

    Quoted text is data, except that everything EXECUTE receives up to the
    statement terminator is dynamic SQL and is kept, however it is spliced.
    A `--` inside quotes is never a comment."""
    out: list[str] = []
    executing: bool = False
    i = 0
    while i < len(sql):
        char = sql[i]
        if sql.startswith("--", i):
            newline = sql.find("\n", i)
            i = len(sql) if newline == -1 else newline
            out.append(" ")
        elif sql.startswith("/*", i):
            close = sql.find("*/", i + 2)
            i = len(sql) if close == -1 else close + 2
            out.append(" ")
        elif char in "'\"":
            close = i + 1
            while close < len(sql) and (
                sql[close] != char or sql[close + 1 : close + 2] == char
            ):
                close += 2 if sql[close] == char else 1
            out.append(sql[i : close + 1] if executing and char == "'" else " ")
            i = close + 1
        else:
            if char == ";":
                executing = False
            elif _EXECUTE.match(sql, i):
                executing = True
            out.append(char)
            i += 1
    return "".join(out)


def _names_session(annotation: ast.expr) -> bool:
    name = annotation.attr if isinstance(annotation, ast.Attribute) else None
    if isinstance(annotation, ast.Name):
        name = annotation.id
    return name == "Session"


def _is_list_insert(node: ast.Call) -> bool:
    """`items.insert(0, x)` takes an index first, the Core construct never does."""
    return bool(node.args) and isinstance(node.args[0], ast.Constant)


def find_inserts(source: str) -> list[int]:
    """One-based line numbers of row writes outside downgrade."""
    finder = _InsertFinder(source.splitlines())
    module = ast.parse(source)
    # Module-level names are bound before any function runs, whatever the order.
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in module.body:
        if not isinstance(node, functions):
            finder.visit(node)
    for node in module.body:
        if isinstance(node, functions):
            finder.visit(node)
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
