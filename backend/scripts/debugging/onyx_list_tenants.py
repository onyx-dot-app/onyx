#!/usr/bin/env python3

"""
Tenant Count Script
Simple script to count the number of tenants in the database.
Used by the parallel migration script to determine how to split work.

Usage:

```
PYTHONPATH=. python scripts/debugging/onyx_list_tenants.py
```

"""

import sys

from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from shared_configs.configs import TENANT_ID_PREFIX


def main() -> None:
    try:
        # Initialize the database engine with conservative settings
        SqlEngine.init_engine(pool_size=5, max_overflow=2)

        # Get all tenant IDs
        tenant_ids = get_all_tenant_ids()

        # Filter to only tenant schemas (not public or other system schemas)
        tenant_schemas = [tid for tid in tenant_ids if tid.startswith(TENANT_ID_PREFIX)]

        # Print all tenant IDs, one per line
        for tenant_id in tenant_schemas:
            print(tenant_id)

    except Exception as e:
        print(f"Error getting tenant IDs: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
