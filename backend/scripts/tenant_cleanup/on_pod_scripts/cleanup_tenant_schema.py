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

from onyx.db.engine.shard_registry import get_engine_for_shard, get_shard_specs
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_shared_schema
from onyx.db.engine.tenant_utils import validate_tenant_id
from onyx.db.tenant_shard import clear_tenant_placement


def drop_data_plane_schema(tenant_id: str) -> dict[str, str]:
    """Drop the PostgreSQL schema for the given tenant."""
    print(f"Dropping data plane schema for tenant: {tenant_id}", file=sys.stderr)

    # A schema name cannot be bound as a parameter, so it is interpolated into DDL
    # below. Validate before touching any database: this argument arrives from a
    # human on the command line, and the drop now runs against every shard.
    if not validate_tenant_id(tenant_id):
        message = f"Invalid tenant_id format: {tenant_id}"
        print(message, file=sys.stderr)
        return {"status": "error", "message": message}

    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    try:
        # Swept rather than resolved through the catalog: the mapping is deleted below,
        # so trusting a stale row would strand the schema on a shard nothing can reach
        # afterwards. A tenant mid-migration also exists on two shards at once.
        # Equivalent to a single lookup when one shard is configured.
        dropped_from: list[str] = []
        for shard_name in sorted(get_shard_specs()):
            with get_engine_for_shard(shard_name).connect() as connection:
                with connection.begin():
                    check_schema_query = text("""
                        SELECT nspname
                        FROM pg_namespace
                        WHERE nspname = :schema_name
                    """)

                    if (
                        connection.execute(
                            check_schema_query, {"schema_name": tenant_id}
                        ).fetchone()
                        is None
                    ):
                        continue

                    # CASCADE to remove all objects within it
                    connection.execute(
                        text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE')
                    )
                    dropped_from.append(shard_name)
                    print(
                        f"Dropped schema {tenant_id} from shard {shard_name}",
                        file=sys.stderr,
                    )

        # Runs even when no schema was found, so a retry after a partially completed
        # cleanup converges instead of repeating `not_found` forever.
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

        clear_tenant_placement(tenant_id)
        print(f"Successfully deleted tenant mapping for: {tenant_id}", file=sys.stderr)

        if not dropped_from:
            return {
                "status": "not_found",
                "message": f"Schema {tenant_id} exists on no shard; cleared catalog rows",
            }
        return {
            "status": "success",
            "message": f"Dropped schema {tenant_id} from: {', '.join(dropped_from)}",
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
