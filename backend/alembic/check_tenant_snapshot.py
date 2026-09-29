#!/usr/bin/env python3
"""Deploy gate for tenant schema snapshots, meant to run after the migration job:
clone each shard's snapshot for the code's head, compare it with a freshly migrated
schema, and fail on any difference so no snapshot ships that the chain would not build."""

import sys

from ee.onyx.db.tenant_snapshot import check_snapshot_parity
from ee.onyx.db.tenant_snapshot import get_head_revision
from ee.onyx.db.tenant_snapshot import get_snapshot
from onyx.db.engine.shard_registry import get_shard_specs
from onyx.db.engine.sql_engine import SqlEngine


def main() -> int:
    head_rev = get_head_revision()
    if head_rev is None:
        print("Could not determine head revision.", file=sys.stderr)
        return 1

    failed = False
    with SqlEngine.scoped_engine(pool_size=5, max_overflow=2):
        for shard_name in sorted(get_shard_specs()):
            dump = get_snapshot(shard_name, head_rev)
            if dump is None:
                print(f"{shard_name}: no snapshot for head {head_rev}", file=sys.stderr)
                failed = True
                continue
            differences = check_snapshot_parity(shard_name, dump)
            if differences:
                print(f"{shard_name}: snapshot differs from a migrated schema:")
                print("\n".join(differences))
                print(
                    "Drop the template schema on that shard and rerun the migration "
                    "job with --snapshot-template to rebuild it from the chain."
                )
                failed = True
            else:
                print(
                    f"{shard_name}: snapshot for {head_rev} matches a migrated schema"
                )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
