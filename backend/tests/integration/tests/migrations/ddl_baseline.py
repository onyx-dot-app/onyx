from collections import Counter
from pathlib import Path

from alembic.autogenerate.api import AutogenContext
from alembic.autogenerate.render import _render_cmd_body
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
    autogen = AutogenContext(context)
    upgrades = directives[0].upgrade_ops_list[0]
    for group in list(upgrades.ops):
        container = group if isinstance(group, ModifyTableOps) else upgrades
        for operation in (
            list(group.ops) if isinstance(group, ModifyTableOps) else [group]
        ):
            rendered = _render_cmd_body(UpgradeOps(ops=[operation]), autogen)
            statement = _normalize("\n".join(rendered.strip().splitlines()[1:-1]))
            if expected[statement]:
                expected[statement] -= 1
                container.ops.remove(operation)
        if isinstance(group, ModifyTableOps) and not group.ops:
            upgrades.ops.remove(group)


def _normalize(statement: str) -> str:
    return "\n".join(line.strip() for line in statement.splitlines())
