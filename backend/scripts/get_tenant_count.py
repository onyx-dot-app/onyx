#!/usr/bin/env python3

"""
Tenant Count Script
Simple script to count the number of tenants in the database.
Used by the parallel migration script to determine how to split work.
"""

import sys

# Add the backend directory to the Python path
sys.path.append("/opt/onyx/backend")

from onyx.db.engine import get_all_tenant_ids, SqlEngine
from shared_configs.configs import TENANT_ID_PREFIX


def main():
    try:
        # Initialize the database engine with conservative settings
        SqlEngine.init_engine(pool_size=5, max_overflow=2)

        # Get all tenant IDs
        tenant_ids = get_all_tenant_ids()

        # Filter to only tenant schemas (not public or other system schemas)
        tenant_schemas = [tid for tid in tenant_ids if tid.startswith(TENANT_ID_PREFIX)]

        # Print the count
        print(len(tenant_schemas))

    except Exception as e:
        print(f"Error counting tenants: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
