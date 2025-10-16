#!/usr/bin/env python3
"""
Script to get the default index name for a tenant.
Designed to be run on a heavy worker pod.

Usage:
    python get_tenant_index_name.py <tenant_id>
"""

import json
import sys

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.search_settings import get_current_search_settings
from onyx.db.search_settings import get_secondary_search_settings
from onyx.document_index.factory import get_default_document_index


def get_tenant_index_name(tenant_id: str) -> dict[str, str]:
    """Get the default index name for the given tenant."""
    print(f"Getting default index name for tenant: {tenant_id}", file=sys.stderr)

    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    try:
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            search_settings = get_current_search_settings(db_session)
            secondary_search_settings = get_secondary_search_settings(db_session)

            document_index = get_default_document_index(
                search_settings=search_settings,
                secondary_search_settings=secondary_search_settings,
            )
            index_name = document_index.index_name

            print(f"Found index name: {index_name}", file=sys.stderr)
            return {"status": "success", "index_name": index_name}

    except Exception as e:
        print(f"Failed to get index name for tenant {tenant_id}: {e}", file=sys.stderr)
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python get_tenant_index_name.py <tenant_id>", file=sys.stderr)
        sys.exit(1)

    tenant_id = sys.argv[1]

    result = get_tenant_index_name(tenant_id)

    # Output result as JSON to stdout for easy parsing
    print(json.dumps(result))

    # Exit with error code if failed
    if result["status"] == "error":
        sys.exit(1)
