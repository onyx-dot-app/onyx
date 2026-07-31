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

from onyx.db.engine.shard_routing import get_engine_for_tenant
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_shared_schema
from onyx.db.tenant_shard import clear_tenant_placement


def drop_data_plane_schema(tenant_id: str) -> dict[str, str]:
    """Drop the PostgreSQL schema for the given tenant."""
    print(f"Dropping data plane schema for tenant: {tenant_id}", file=sys.stderr)

    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    try:
        # The schema lives on the tenant's shard, which is not necessarily the database
        # holding the catalog tables cleaned up below.
        with get_engine_for_tenant(tenant_id).connect() as connection:
            with connection.begin():
                check_schema_query = text("""
                    SELECT nspname
                    FROM pg_namespace
                    WHERE nspname = :schema_name
                """)

                result = connection.execute(
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
                connection.execute(drop_schema_query)

        print(f"Successfully dropped schema: {tenant_id}", file=sys.stderr)

        with get_session_with_shared_schema() as session:
            # Schema-qualified on purpose: schema_translate_map only rewrites SQLAlchemy
            # Table constructs, not raw text(), so an unqualified name resolves against
            # whatever search_path the pooled backend happens to carry.
            delete_mapping_query = text("""
                DELETE FROM public.user_tenant_mapping
                WHERE tenant_id = :tenant_id
                """)
            session.execute(delete_mapping_query, {"tenant_id": tenant_id})
            session.commit()

        print(f"Successfully deleted tenant mapping for: {tenant_id}", file=sys.stderr)

        # Last: the shard lookup above depends on this row.
        clear_tenant_placement(tenant_id)

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
