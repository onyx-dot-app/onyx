#!/usr/bin/env python3
"""Check new Alembic revisions without loading Alembic or running migration code.

Run from any directory: python3 backend/lint/check_migration_design.py
The hook checks both complete chains, including when a commit deletes a revision.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections.abc import Iterator
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_MARKERS = {
    _BACKEND / "alembic" / "versions": "ff11c4042c42",
    _BACKEND / "alembic_tenants" / "versions": "af8d808d89dd",
}
_FIXES = {
    "not-valid": (
        "Use postgresql_not_valid=True. For a foreign key in add_column, add the "
        "column without the foreign key, then use "
        "op.create_foreign_key(..., postgresql_not_valid=True). "
        "Commit, then validate. See 9d8f310ac672."
    ),
    "deferrable": "Remove deferrable=True and initially=DEFERRED. Check the constraint immediately.",
    "not-null": "Set a server_default or add a nullable column, backfill it, then set NOT NULL.",
    "blocking-index": "Commit and build the index concurrently on an AUTOCOMMIT connection. See 9d8f310ac672.",
}
ALLOW_MARKER = "migration-design: allow"
_ALLOW = re.compile(rf"# {re.escape(ALLOW_MARKER)} ([a-z-]+) - (\S.*)")
_CONSTRAINTS = {
    "create_check_constraint": ("table_name", "schema"),
    "create_foreign_key": ("source_table", "source_schema"),
}
_SA_CONSTRAINTS = {
    "CheckConstraint",
    "ForeignKey",
    "ForeignKeyConstraint",
    "PrimaryKeyConstraint",
    "UniqueConstraint",
    "ExcludeConstraint",
}


def _walk_upgrade(node: ast.AST, *, enter_functions: bool = True) -> Iterator[ast.AST]:
    if isinstance(node, ast.FunctionDef) and (
        node.name == "downgrade" or not enter_functions
    ):
        return
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _walk_upgrade(child, enter_functions=enter_functions)


def _argument(call: ast.Call, name: str, position: int = -1) -> ast.expr | None:
    if 0 <= position < len(call.args):
        return call.args[position]
    return next((kw.value for kw in call.keywords if kw.arg == name), None)


def _literal(node: ast.expr | None) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _op_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.value.id == "op":
            return func.attr
    return ""


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _is_deferrable(call: ast.Call) -> bool:
    return (
        _call_name(call) in _SA_CONSTRAINTS or _op_name(call).startswith("create_")
    ) and (
        _literal(_argument(call, "deferrable")) is True
        or str(_literal(_argument(call, "initially"))).upper() == "DEFERRED"
    )


def _table(
    call: ast.Call, name: str, position: int, schema_name: str = "schema"
) -> tuple[str, str | None] | None:
    table = _literal(_argument(call, name, position))
    schema_node = _argument(call, schema_name)
    schema = _literal(schema_node)
    if not isinstance(table, str):
        return None
    if schema_node is None or (
        isinstance(schema_node, ast.Constant) and schema is None
    ):
        return table, None
    if isinstance(schema, str):
        return table, schema
    return None


def _operation_rules(
    call: ast.Call, created: set[tuple[str, str | None]]
) -> Iterator[str]:
    if _is_deferrable(call):
        yield "deferrable"
    name = _op_name(call)
    if name in _CONSTRAINTS:
        table_name, schema_name = _CONSTRAINTS[name]
        if (
            _table(call, table_name, 1, schema_name) not in created
            and _literal(_argument(call, "postgresql_not_valid")) is not True
        ):
            yield "not-valid"
    if name == "add_column" and _table(call, "table_name", 0) not in created:
        column = _argument(call, "column", 1)
        if isinstance(column, ast.Call):
            if any(
                isinstance(arg, ast.Call) and _call_name(arg) == "ForeignKey"
                for arg in column.args
            ):
                yield "not-valid"
            default = _argument(column, "server_default")
            if _literal(_argument(column, "nullable")) is False and (
                default is None
                or (isinstance(default, ast.Constant) and default.value is None)
            ):
                yield "not-null"
    if name == "create_index" and _table(call, "table_name", 1) not in created:
        yield "blocking-index"


def find_violations(
    tree: ast.Module, source: str, *, accepted: set[tuple[int, str]] | None = None
) -> list[tuple[int, str]]:
    """Check direct op calls and literal constraint options outside downgrade."""
    comments: dict[int, str] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and (match := _ALLOW.fullmatch(token.string)):
            comments[token.start[0]] = match[1]

    violations: set[tuple[int, str]] = set()
    # Only use unconditional table creation in the same function as an exemption.
    for function in _walk_upgrade(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        created: set[tuple[str, str | None]] = set()
        for statement in function.body:
            calls = [
                node
                for node in _walk_upgrade(statement, enter_functions=False)
                if isinstance(node, ast.Call)
            ]
            for call in calls:
                name = _op_name(call)
                if name == "drop_table":
                    table_arguments = ("table_name",)
                elif name == "rename_table":
                    table_arguments = ("old_table_name", "new_table_name")
                else:
                    continue
                for position, argument in enumerate(table_arguments):
                    table = _table(call, argument, position)
                    if table is None:
                        created.clear()
                        break
                    table_name, schema = table
                    created.difference_update(
                        {
                            (created_name, created_schema)
                            for created_name, created_schema in created
                            if created_name == table_name
                            and (
                                schema is None
                                or created_schema is None
                                or schema == created_schema
                            )
                        }
                    )
            for call in calls:
                for rule in _operation_rules(call, created):
                    if not any(
                        comments.get(line) == rule
                        for line in range(
                            call.lineno, (call.end_lineno or call.lineno) + 1
                        )
                    ):
                        violations.add((call.lineno, rule))
                    elif accepted is not None:
                        accepted.add((call.lineno, rule))
            value = (
                statement.value
                if isinstance(statement, (ast.Expr, ast.Assign, ast.AnnAssign))
                else None
            )
            if isinstance(value, ast.Call) and _op_name(value) == "create_table":
                create_if_absent = _argument(value, "if_not_exists")
                if (
                    create_if_absent is not None
                    and _literal(create_if_absent) is not False
                ):
                    continue
                if any(keyword.arg is None for keyword in value.keywords):
                    continue
                table = _table(value, "table_name", 0)
                if table is not None:
                    created.add(table)
    return sorted(violations)


def _metadata(tree: ast.Module) -> dict[str, ast.expr]:
    values: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        else:
            continue
        if isinstance(target, ast.Name) and node.value is not None:
            values[target.id] = node.value
    return values


def _ancestors(parents: dict[str, tuple[str, ...]], start: str) -> set[str]:
    exempt: set[str] = set()
    pending = [start]
    while pending:
        revision = pending.pop()
        if revision not in exempt:
            exempt.add(revision)
            pending.extend(parents[revision])
    return exempt


def check_chain(directory: Path, marker: str) -> Iterator[str]:
    parents: dict[str, tuple[str, ...]] = {}
    files: dict[str, tuple[Path, ast.Module, str]] = {}
    for path in sorted(directory.glob("*.py")):
        if path.name == "__init__.py":
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
            metadata = _metadata(tree)
            revision = ast.literal_eval(metadata["revision"])
            down = ast.literal_eval(metadata["down_revision"])
        except (SyntaxError, ValueError, KeyError) as error:
            line = error.lineno if isinstance(error, SyntaxError) else 1
            yield f"{path}:{line}: revision-metadata: Use valid Python and literal revision and down_revision values."
            continue
        if not isinstance(revision, str) or revision in files:
            yield f"{path}:{metadata['revision'].lineno}: revision-metadata: Give each revision a unique string ID."
            continue
        if isinstance(down, str):
            down = (down,)
        if down is None:
            down = ()
        if not isinstance(down, (tuple, list)) or not all(
            isinstance(item, str) for item in down
        ):
            yield f"{path}:{metadata['down_revision'].lineno}: revision-metadata: Use a revision ID, a tuple of IDs, or None."
            continue
        parents[revision] = tuple(down)
        files[revision] = path, tree, source

    missing = {parent for down in parents.values() for parent in down} - files.keys()
    if missing or marker not in files:
        missing.update({marker} - files.keys())
        yield f"{directory}:1: revision-metadata: Restore missing revisions: {', '.join(sorted(missing))}."
        return

    try:
        TopologicalSorter(parents).prepare()
    except CycleError as error:
        cycle = error.args[1]
        path, tree, _ = files[cycle[0]]
        line = _metadata(tree)["down_revision"].lineno
        yield f"{path}:{line}: revision-metadata: Fix the down_revision links to break this cycle: {' -> '.join(cycle)}."
        return

    heads = files.keys() - {parent for down in parents.values() for parent in down}
    if len(heads) != 1:
        for head in sorted(heads):
            path, tree, _ = files[head]
            line = _metadata(tree)["down_revision"].lineno
            yield f"{path}:{line}: single-head: Rebase the new revision onto the current head or add a merge revision. Heads: {', '.join(sorted(heads))}."

    exempt = _ancestors(parents, marker)
    for revision in files.keys() - exempt:
        path, tree, source = files[revision]
        for line, rule in find_violations(tree, source):
            yield f"{path}:{line}: {rule}: {_FIXES[rule]}"


def main() -> int:
    failures = sorted(
        failure
        for directory, marker in _MARKERS.items()
        for failure in check_chain(directory, marker)
    )
    for failure in failures:
        print(failure)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
