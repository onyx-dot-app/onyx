#!/usr/bin/env python3

"""
Empty Tenant List Script
Script to list tenant IDs that have no users in the database.
Useful for identifying orphaned/unused tenants.

Usage:

```
# List one tenant per line (default)
PYTHONPATH=. python scripts/debugging/onyx_list_empty_tenants.py

# Output as CSV (all on one line)
PYTHONPATH=. python scripts/debugging/onyx_list_empty_tenants.py --csv

# Output as CSV batched into groups of 5
PYTHONPATH=. python scripts/debugging/onyx_list_empty_tenants.py --csv -n 5

# Also show user count for non-empty tenants (verbose mode)
PYTHONPATH=. python scripts/debugging/onyx_list_empty_tenants.py -v

# Include broken tenants (missing user table) in output
PYTHONPATH=. python scripts/debugging/onyx_list_empty_tenants.py --include-broken
```

"""

import argparse
import sys

from sqlalchemy import text

from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from shared_configs.configs import TENANT_ID_PREFIX


def batch_list(items: list[str], batch_size: int) -> list[list[str]]:
    """Split a list into batches of specified size."""
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def get_schemas_with_user_table(tenant_schemas: list[str]) -> set[str]:
    """Get the set of schemas that have a user table."""
    engine = get_sqlalchemy_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT table_schema
                FROM information_schema.tables
                WHERE table_name = 'user'
                AND table_schema = ANY(:schemas)
                """
            ),
            {"schemas": tenant_schemas},
        )
        return {row[0] for row in result}


def get_user_counts_bulk(tenant_schemas: list[str]) -> dict[str, int]:
    """Get user counts for all tenants in a single query.

    Returns a dict mapping tenant_id -> user_count.
    Only includes tenants that have a user table.
    """
    if not tenant_schemas:
        return {}

    # First, find which schemas actually have a user table
    schemas_with_table = get_schemas_with_user_table(tenant_schemas)

    if not schemas_with_table:
        return {}

    # Build a UNION ALL query to count users in all schemas at once
    # Using quote_ident equivalent for safety (schema names are already validated)
    union_parts = []
    for schema in schemas_with_table:
        # Schema names from get_all_tenant_ids are safe (alphanumeric + underscore + hyphen)
        union_parts.append(
            f"SELECT '{schema}' as tenant_id, COUNT(*) as user_count "
            f'FROM "{schema}"."user"'
        )

    if not union_parts:
        return {}

    query = " UNION ALL ".join(union_parts)

    engine = get_sqlalchemy_engine()
    with engine.connect() as conn:
        result = conn.execute(text(query))
        return {row[0]: row[1] for row in result}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List tenant IDs that have no users.",
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
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show user counts for all tenants, not just empty ones",
    )
    parser.add_argument(
        "--include-broken",
        action="store_true",
        help="Include broken tenants (missing user table) in the output",
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

        # Get all user counts in bulk (single query)
        user_counts = get_user_counts_bulk(tenant_schemas)

        empty_tenants: list[str] = []
        broken_tenants: list[str] = []

        for tenant_id in tenant_schemas:
            if tenant_id not in user_counts:
                # No user table = broken tenant
                broken_tenants.append(tenant_id)
                if args.verbose:
                    print(f"{tenant_id}: BROKEN (no user table)", file=sys.stderr)
            elif user_counts[tenant_id] == 0:
                empty_tenants.append(tenant_id)
                if args.verbose:
                    print(f"{tenant_id}: 0 users (empty)", file=sys.stderr)
            elif args.verbose:
                print(f"{tenant_id}: {user_counts[tenant_id]} users", file=sys.stderr)

        if args.verbose:
            print(
                f"\nFound {len(empty_tenants)} empty tenant(s) and "
                f"{len(broken_tenants)} broken tenant(s) out of {len(tenant_schemas)} total",
                file=sys.stderr,
            )
            print("---", file=sys.stderr)

        # Combine empty and broken tenants if --include-broken is set
        output_tenants = empty_tenants
        if args.include_broken:
            output_tenants = empty_tenants + broken_tenants

        if args.csv:
            if args.max_args:
                # Output batched CSV lines
                for batch in batch_list(output_tenants, args.max_args):
                    print(",".join(batch))
            else:
                # Output all on one line
                print(",".join(output_tenants))
        else:
            # Print all empty tenant IDs, one per line
            for tenant_id in output_tenants:
                print(tenant_id)

    except Exception as e:
        print(f"Error getting tenant IDs: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
