#!/usr/bin/env python3

"""
Tenant List Script
Simple script to list the tenant IDs in the database.
Used by the parallel migration script to determine how to split work.

Usage:

```
# List one tenant per line (default)
PYTHONPATH=. python scripts/debugging/onyx_list_tenants.py

# Output as CSV (all on one line)
PYTHONPATH=. python scripts/debugging/onyx_list_tenants.py --csv

# Output as CSV batched into groups of 5
PYTHONPATH=. python scripts/debugging/onyx_list_tenants.py --csv -n 5
```

"""

import argparse
import sys

from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from shared_configs.configs import TENANT_ID_PREFIX


def batch_list(items: list[str], batch_size: int) -> list[list[str]]:
    """Split a list into batches of specified size."""
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List tenant IDs from the database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Output as comma-separated values instead of one per line",
    )
    parser.add_argument(
        "-n",
        "--max-args",
        type=int,
        default=None,
        metavar="N",
        help="Batch CSV output into groups of N items (requires --csv)",
    )
    args = parser.parse_args()

    if args.max_args is not None and not args.csv:
        parser.error("--max-args/-n requires --csv flag")

    try:
        # Initialize the database engine with conservative settings
        SqlEngine.init_engine(pool_size=5, max_overflow=2)

        # Get all tenant IDs
        tenant_ids = get_all_tenant_ids()

        # Filter to only tenant schemas (not public or other system schemas)
        tenant_schemas = [tid for tid in tenant_ids if tid.startswith(TENANT_ID_PREFIX)]

        if args.csv:
            if args.max_args:
                # Output batched CSV lines
                for batch in batch_list(tenant_schemas, args.max_args):
                    print(",".join(batch))
            else:
                # Output all on one line
                print(",".join(tenant_schemas))
        else:
            # Print all tenant IDs, one per line
            for tenant_id in tenant_schemas:
                print(tenant_id)

    except Exception as e:
        print(f"Error getting tenant IDs: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
