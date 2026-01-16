#!/usr/bin/env python3

"""
Tenant Downgrade Script
Script to forcibly downgrade a single tenant schema to the base revision.

This drops the schema entirely and recreates it empty.

WARNING: This is a destructive operation that will delete tenant data!

Usage:
    PYTHONPATH=. python scripts/debugging/onyx_downgrade_tenant_to_base.py <tenant_id>

To re-initialize the tenant with migrations afterwards:
    alembic -x schemas=<tenant_id> upgrade head
"""

import argparse
import sys

from sqlalchemy import text

from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.db.engine.sql_engine import SqlEngine
from shared_configs.configs import TENANT_ID_PREFIX


def schema_exists(tenant_id: str) -> bool:
    """Check if a schema exists."""
    engine = get_sqlalchemy_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema_name"
            ),
            {"schema_name": tenant_id},
        )
        return result.fetchone() is not None


def drop_and_recreate_schema(tenant_id: str) -> bool:
    """Drop a tenant schema entirely and recreate it empty."""
    engine = get_sqlalchemy_engine()

    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE'))
            conn.commit()
            conn.execute(text(f'CREATE SCHEMA "{tenant_id}"'))
            conn.commit()
        return True
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Forcibly downgrade a single tenant schema to the base revision.",
    )
    parser.add_argument("tenant_id", help="The tenant ID (schema name) to downgrade")
    parser.add_argument("-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    if not args.tenant_id.startswith(TENANT_ID_PREFIX):
        print(f"Error: tenant_id must start with '{TENANT_ID_PREFIX}'", file=sys.stderr)
        sys.exit(1)

    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    if not schema_exists(args.tenant_id):
        print(f"Error: Schema '{args.tenant_id}' does not exist.", file=sys.stderr)
        sys.exit(1)

    if not args.y:
        response = input(f"Delete all data in {args.tenant_id}? [y/N]: ")
        if response.lower() != "y":
            sys.exit(1)

    if drop_and_recreate_schema(args.tenant_id):
        print(f"Done. Run: alembic -x schemas={args.tenant_id} upgrade head")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
