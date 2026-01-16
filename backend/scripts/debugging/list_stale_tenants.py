#!/usr/bin/env python3

"""
Tenant Not-At-Head List Script
Script to list tenant IDs that are not at the head alembic revision.
Useful for identifying tenants that need migrations.

Usage:

```
# List one tenant per line (default)
PYTHONPATH=. python scripts/debugging/onyx_list_tenants_not_at_head.py

# Output as CSV (all on one line)
PYTHONPATH=. python scripts/debugging/onyx_list_tenants_not_at_head.py --csv

# Output as CSV batched into groups of 5
PYTHONPATH=. python scripts/debugging/onyx_list_tenants_not_at_head.py --csv -n 5

# Verbose mode: show revision for each tenant
PYTHONPATH=. python scripts/debugging/onyx_list_tenants_not_at_head.py -v

# Show summary of revisions by count
PYTHONPATH=. python scripts/debugging/onyx_list_tenants_not_at_head.py --summary

# Include tenants with no alembic_version table
PYTHONPATH=. python scripts/debugging/onyx_list_tenants_not_at_head.py --include-missing

# Only show tenants that are not at head AND have no users
PYTHONPATH=. python scripts/debugging/onyx_list_tenants_not_at_head.py --empty-only

# Combine: empty tenants not at head, with summary
PYTHONPATH=. python scripts/debugging/onyx_list_tenants_not_at_head.py --empty-only --summary
```

"""

import argparse
import os
import sys
from collections import Counter

from sqlalchemy import text

from alembic.config import Config
from alembic.script import ScriptDirectory
from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from shared_configs.configs import TENANT_ID_PREFIX


def batch_list(items: list[str], batch_size: int) -> list[list[str]]:
    """Split a list into batches of specified size."""
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def get_alembic_head_revision() -> str:
    """Get the current alembic head revision from the migrations directory."""
    # Find the alembic.ini file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
    alembic_ini_path = os.path.join(root_dir, "alembic.ini")

    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("script_location", os.path.join(root_dir, "alembic"))

    script_dir = ScriptDirectory.from_config(alembic_cfg)
    heads = script_dir.get_heads()

    if not heads:
        raise RuntimeError("No alembic head revision found")
    if len(heads) > 1:
        raise RuntimeError(f"Multiple alembic heads found: {heads}")

    return heads[0]


def get_schemas_with_table(tenant_schemas: list[str], table_name: str) -> set[str]:
    """Get the set of schemas that have a specific table."""
    engine = get_sqlalchemy_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT table_schema
                FROM information_schema.tables
                WHERE table_name = :table_name
                AND table_schema = ANY(:schemas)
                """
            ),
            {"table_name": table_name, "schemas": tenant_schemas},
        )
        return {row[0] for row in result}


def get_user_counts_bulk(tenant_schemas: list[str]) -> dict[str, int | None]:
    """Get user counts for all tenants in a single query.

    Returns a dict mapping tenant_id -> user_count (or None if no user table).
    """
    if not tenant_schemas:
        return {}

    # First, find which schemas actually have a user table
    schemas_with_table = get_schemas_with_table(tenant_schemas, "user")

    # Initialize all schemas as None (no user table)
    result_dict: dict[str, int | None] = {schema: None for schema in tenant_schemas}

    if not schemas_with_table:
        return result_dict

    # Build a UNION ALL query to count users in all schemas at once
    union_parts = []
    for schema in schemas_with_table:
        union_parts.append(
            f"(SELECT '{schema}' as tenant_id, COUNT(*) as user_count "
            f'FROM "{schema}"."user")'
        )

    if not union_parts:
        return result_dict

    query = " UNION ALL ".join(union_parts)

    engine = get_sqlalchemy_engine()
    with engine.connect() as conn:
        result = conn.execute(text(query))
        for row in result:
            result_dict[row[0]] = row[1]

    return result_dict


def get_alembic_versions_bulk(tenant_schemas: list[str]) -> dict[str, str | None]:
    """Get alembic versions for all tenants in a single query.

    Returns a dict mapping tenant_id -> version_num (or None if no alembic_version table).
    """
    if not tenant_schemas:
        return {}

    # First, find which schemas have an alembic_version table
    schemas_with_table = get_schemas_with_table(tenant_schemas, "alembic_version")

    # Initialize all schemas as None (no alembic_version table)
    result_dict: dict[str, str | None] = {schema: None for schema in tenant_schemas}

    if not schemas_with_table:
        return result_dict

    # Build a UNION ALL query to get versions from all schemas at once
    union_parts = []
    for schema in schemas_with_table:
        union_parts.append(
            f"(SELECT '{schema}' as tenant_id, version_num "
            f'FROM "{schema}"."alembic_version" LIMIT 1)'
        )

    if not union_parts:
        return result_dict

    query = " UNION ALL ".join(union_parts)

    engine = get_sqlalchemy_engine()
    with engine.connect() as conn:
        result = conn.execute(text(query))
        for row in result:
            result_dict[row[0]] = row[1]

    return result_dict


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List tenant IDs that are not at the alembic head revision.",
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
        help="Show revision for each tenant",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show summary of revisions grouped by version",
    )
    parser.add_argument(
        "--include-missing",
        action="store_true",
        help="Include tenants that have no alembic_version table",
    )
    parser.add_argument(
        "--empty-only",
        action="store_true",
        help="Only include tenants that have no users (empty tenants)",
    )
    args = parser.parse_args()

    if args.max_args is not None and not args.csv:
        parser.error("--max-args/-n requires --csv flag")

    try:
        # Initialize the database engine with conservative settings
        SqlEngine.init_engine(pool_size=5, max_overflow=2)

        # Get alembic head revision
        head_revision = get_alembic_head_revision()
        if args.verbose or args.summary:
            print(f"Alembic head revision: {head_revision}", file=sys.stderr)

        # Get all tenant IDs
        tenant_ids = get_all_tenant_ids()

        # Filter to only tenant schemas (not public or other system schemas)
        tenant_schemas = [tid for tid in tenant_ids if tid.startswith(TENANT_ID_PREFIX)]

        # Get all alembic versions in bulk (single query)
        alembic_versions = get_alembic_versions_bulk(tenant_schemas)

        # Get user counts if filtering by empty tenants
        user_counts: dict[str, int | None] = {}
        if args.empty_only:
            user_counts = get_user_counts_bulk(tenant_schemas)

        tenants_not_at_head: list[str] = []
        tenants_missing_version: list[str] = []

        # Track revision counts for summary
        revision_counts: Counter[str] = Counter()

        for tenant_id in tenant_schemas:
            tenant_version = alembic_versions.get(tenant_id)

            # Check if tenant is empty (no users or no user table)
            is_empty = False
            if args.empty_only:
                user_count = user_counts.get(tenant_id)
                is_empty = user_count is None or user_count == 0

            if tenant_version is None:
                # Skip if filtering by empty and tenant is not empty
                if args.empty_only and not is_empty:
                    continue
                tenants_missing_version.append(tenant_id)
                revision_counts["<missing>"] += 1
                if args.verbose:
                    msg = f"{tenant_id}: NO alembic_version table"
                    if args.empty_only:
                        user_count = user_counts.get(tenant_id)
                        if user_count is None:
                            msg += ", no user table"
                        else:
                            msg += f", {user_count} users"
                    print(msg, file=sys.stderr)
            elif tenant_version != head_revision:
                # Skip if filtering by empty and tenant is not empty
                if args.empty_only and not is_empty:
                    continue
                tenants_not_at_head.append(tenant_id)
                revision_counts[tenant_version] += 1
                if args.verbose:
                    msg = f"{tenant_id}: {tenant_version[:12]}... (not at head)"
                    if args.empty_only:
                        user_count = user_counts.get(tenant_id)
                        if user_count is None:
                            msg += ", no user table"
                        else:
                            msg += f", {user_count} users"
                    print(msg, file=sys.stderr)
            else:
                revision_counts[head_revision] += 1
                if args.verbose:
                    print(f"{tenant_id}: at head", file=sys.stderr)

        # Show summary if requested
        if args.summary:
            print("\n--- Revision Summary ---", file=sys.stderr)
            # Sort by count descending
            for revision, count in revision_counts.most_common():
                if revision == head_revision:
                    print(
                        f"  {revision[:12]}... (HEAD): {count} tenant(s)",
                        file=sys.stderr,
                    )
                elif revision == "<missing>":
                    print(
                        f"  <missing alembic_version>: {count} tenant(s)",
                        file=sys.stderr,
                    )
                else:
                    print(f"  {revision[:12]}...: {count} tenant(s)", file=sys.stderr)

        # Build output list
        output_tenants = tenants_not_at_head.copy()
        if args.include_missing:
            output_tenants.extend(tenants_missing_version)

        if args.verbose or args.summary:
            msg = f"\nFound {len(tenants_not_at_head)} tenant(s) not at head"
            if tenants_missing_version:
                msg += f", {len(tenants_missing_version)} with no alembic_version table"
            msg += f" out of {len(tenant_schemas)} total"
            if args.empty_only:
                msg += " (filtered to empty tenants only)"
            print(msg, file=sys.stderr)
            print("---", file=sys.stderr)

        if args.csv:
            if args.max_args:
                # Output batched CSV lines
                for batch in batch_list(output_tenants, args.max_args):
                    print(",".join(batch))
            else:
                # Output all on one line
                print(",".join(output_tenants))
        else:
            # Print all tenant IDs, one per line
            for tenant_id in output_tenants:
                print(tenant_id)

    except Exception as e:
        print(f"Error getting tenant IDs: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
