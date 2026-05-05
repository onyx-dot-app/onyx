"""Script to update connector prune_freq from one value to another (in days).

Must be run from inside a Kubernetes pod. DB connection is picked up automatically
from the pod's environment variables.

Usage:
    python -m scripts.update_connector_prune_freq --from-days <n> --to-days <n> [--dry-run]

Example:
    python -m scripts.update_connector_prune_freq --from-days 30 --to-days 25 --dry-run
"""

import argparse
import os
import sys
from typing import Any
from typing import cast

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from sqlalchemy import update  # noqa: E402
from sqlalchemy.engine import CursorResult  # noqa: E402
from sqlalchemy.exc import ProgrammingError  # noqa: E402

from onyx.db.engine.sql_engine import get_session_with_tenant  # noqa: E402
from onyx.db.engine.sql_engine import SqlEngine  # noqa: E402
from onyx.db.engine.tenant_utils import get_all_tenant_ids  # noqa: E402
from onyx.db.models import Connector  # noqa: E402
from onyx.utils.variable_functionality import global_version  # noqa: E402

_SECONDS_PER_DAY = 86400


def run(from_days: int, to_days: int, dry_run: bool) -> None:
    old_freq = from_days * _SECONDS_PER_DAY
    new_freq = to_days * _SECONDS_PER_DAY

    print(
        f"Updating prune_freq: {from_days} days ({old_freq}s) -> {to_days} days ({new_freq}s)"
    )

    tenant_ids = get_all_tenant_ids()
    print(f"Found {len(tenant_ids)} tenant(s)")

    total_updated = 0
    for tenant_id in tenant_ids:
        try:
            with get_session_with_tenant(tenant_id=tenant_id) as db_session:
                result = cast(
                    CursorResult[Any],
                    db_session.execute(
                        update(Connector)
                        .where(Connector.prune_freq == old_freq)
                        .values(prune_freq=new_freq)
                    ),
                )
                rowcount = result.rowcount
                if rowcount > 0:
                    print(f"  {tenant_id}: {rowcount} row(s) updated")
                    total_updated += rowcount

                if dry_run:
                    db_session.rollback()
                else:
                    db_session.commit()
        except ProgrammingError as e:
            if "UndefinedTable" not in type(e.orig).__name__:
                raise
            continue

    print(f"\nTotal rows {'to update' if dry_run else 'updated'}: {total_updated}")
    if dry_run:
        print("Dry run — no changes committed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Update connector prune_freq")
    parser.add_argument(
        "--from-days", type=int, required=True, help="Current prune_freq in days"
    )
    parser.add_argument(
        "--to-days", type=int, required=True, help="New prune_freq in days"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without committing"
    )
    args = parser.parse_args()

    global_version.set_ee()
    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    run(from_days=args.from_days, to_days=args.to_days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
