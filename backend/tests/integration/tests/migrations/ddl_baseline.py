import ast
from collections import Counter
from pathlib import Path
from textwrap import dedent

from alembic.autogenerate import render_python_code
from alembic.operations.ops import MigrationScript, ModifyTableOps, UpgradeOps
from alembic.runtime.migration import MigrationContext


def exclude_known_drift(
    context: MigrationContext,
    _revision: tuple[str, ...],
    directives: list[MigrationScript],
    *,
    chain: str,
) -> None:
    """Remove exact, existing differences before pytest-alembic checks the DDL."""
    baseline = Path(__file__).with_name(f"{chain}_ddl_baseline.txt")
    expected = Counter(
        _normalize(statement)
        for statement in baseline.read_text().strip().split("\n\n")
    )
    render_context = MigrationContext.configure(dialect=context.dialect)
    upgrades = directives[0].upgrade_ops_list[0]
    for group in list(upgrades.ops):
        container = group if isinstance(group, ModifyTableOps) else upgrades
        for operation in (
            list(group.ops) if isinstance(group, ModifyTableOps) else [group]
        ):
            rendered = render_python_code(
                UpgradeOps(ops=[operation]), migration_context=render_context
            )
            statement = _normalize(rendered)
            if expected[statement]:
                expected[statement] -= 1
                container.ops.remove(operation)
        if isinstance(group, ModifyTableOps) and not group.ops:
            upgrades.ops.remove(group)

    obsolete = "\n".join(+expected)
    if obsolete:
        raise AssertionError(
            f"Remove obsolete entries from {baseline.name}:\n{obsolete}"
        )


def _normalize(statement: str) -> str:
    lines = (
        line for line in statement.splitlines() if not line.lstrip().startswith("#")
    )
    return ast.unparse(ast.parse(dedent("\n".join(lines)).strip()))
