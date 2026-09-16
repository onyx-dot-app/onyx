"""Find unused Python code in the backend.

Runs vulture with the `[tool.vulture]` config in pyproject.toml, then drops two
kinds of findings that vulture cannot judge:

- Class-body fields (Pydantic fields, enum members, SQLAlchemy columns). Other
  code reads them through serialization or the ORM, not by name.
- Function arguments. Signatures are fixed by callers, and pytest fixtures are
  often requested only for their side effects.

Alembic migrations are scanned so that their imports count as usage, but
findings inside them are not reported: migrations are frozen history.

Names that are only referenced dynamically go in
backend/scripts/vulture_whitelist.py.

Run from the repository root:

    uv run python backend/scripts/check_dead_code.py
"""

import ast
import sys
from functools import cache
from pathlib import Path

from vulture.config import make_config
from vulture.core import Item, Vulture

DEAD_CODE_EXIT_CODE = 3
MIGRATION_DIRS = ("/alembic/versions/", "/alembic_tenants/versions/")


@cache
def _ignored_variable_sites(filename: str) -> frozenset[tuple[int, str]]:
    """(line, name) pairs for class-body fields and function arguments."""
    with open(filename, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filename)

    sites: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            sites.add((node.lineno, node.arg))
        elif isinstance(node, ast.ClassDef):
            for stmt in node.body:
                targets: list[ast.expr] = []
                if isinstance(stmt, ast.Assign):
                    targets = stmt.targets
                elif isinstance(stmt, ast.AnnAssign):
                    targets = [stmt.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        sites.add((stmt.lineno, target.id))
    return frozenset(sites)


def _is_reportable(item: Item) -> bool:
    filename = Path(item.filename).as_posix()
    if any(migration_dir in filename for migration_dir in MIGRATION_DIRS):
        return False
    if item.typ != "variable":
        return True
    sites = _ignored_variable_sites(filename)
    return (item.first_lineno, item.name) not in sites


def main() -> int:
    config = make_config(sys.argv[1:])
    vulture = Vulture(
        verbose=config["verbose"],
        ignore_names=config["ignore_names"],
        ignore_decorators=config["ignore_decorators"],
    )
    vulture.scavenge(config["paths"], exclude=config["exclude"])

    items = [
        item
        for item in vulture.get_unused_code(
            min_confidence=config["min_confidence"],
            sort_by_size=config["sort_by_size"],
        )
        if _is_reportable(item)
    ]
    for item in items:
        print(item.get_report(add_size=config["sort_by_size"]))

    if items:
        print(
            f"\n{len(items)} unused definitions. Delete them, or add a name that is "
            "only used dynamically to backend/scripts/vulture_whitelist.py.",
            file=sys.stderr,
        )
        return DEAD_CODE_EXIT_CODE
    return 0


if __name__ == "__main__":
    sys.exit(main())
