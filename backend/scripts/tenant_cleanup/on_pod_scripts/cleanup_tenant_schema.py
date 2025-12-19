#!/usr/bin/env python3
"""
Script to drop a tenant's PostgreSQL schema.
Designed to be run on a heavy worker pod.

Usage:
    python cleanup_tenant_schema.py <tenant_id>
"""

import json
import sys

from sqlalchemy import text

from onyx.db.engine.sql_engine import get_session_with_shared_schema
from onyx.db.engine.sql_engine import SqlEngine


def drop_data_plane_schema(tenant_id: str) -> dict[str, str]:
    """Drop the PostgreSQL schema for the given tenant."""
    print(f"Dropping data plane schema for tenant: {tenant_id}", file=sys.stderr)

    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    try:
        with get_session_with_shared_schema() as session:
            # First, verify the schema exists
            check_schema_query = text(
                """
                SELECT nspname
                FROM pg_namespace
                WHERE nspname = :schema_name
            """
            )

            result = session.execute(
                check_schema_query, {"schema_name": tenant_id}
            ).fetchone()

            if not result:
                print(f"Schema {tenant_id} does not exist", file=sys.stderr)
                return {
                    "status": "not_found",
                    "message": f"Schema {tenant_id} does not exist",
                }

            # Drop the schema with CASCADE to remove all objects within it
            drop_schema_query = text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE')
            session.execute(drop_schema_query)
            session.commit()

            print(f"Successfully dropped schema: {tenant_id}", file=sys.stderr)

            # Delete the tenant mapping from user_tenant_mapping table
            delete_mapping_query = text(
                """
                DELETE FROM user_tenant_mapping
                WHERE tenant_id = :tenant_id
                """
            )
            session.execute(delete_mapping_query, {"tenant_id": tenant_id})
            session.commit()

            print(
                f"Successfully deleted tenant mapping for: {tenant_id}", file=sys.stderr
            )
            return {
                "status": "success",
                "message": f"Successfully dropped schema: {tenant_id}",
            }

    except Exception as e:
        print(f"Failed to drop schema for tenant {tenant_id}: {e}", file=sys.stderr)
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python cleanup_tenant_schema.py <tenant_id>", file=sys.stderr)
        sys.exit(1)

    tenant_id = sys.argv[1]

    result = drop_data_plane_schema(tenant_id)

    # Output result as JSON to stdout for easy parsing
    print(json.dumps(result))

    # Exit with error code if failed
    if result["status"] == "error":
        sys.exit(1)
