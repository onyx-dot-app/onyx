#!/usr/bin/env python3
"""
Script to fetch user emails from a tenant's data plane schema.
Must be run on a pod with access to the data plane PostgreSQL database.

Usage:
    python get_tenant_users.py <tenant_id>

Output:
    JSON object with status and users list
"""

import json
import sys

from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import User


def get_tenant_users(tenant_id: str) -> dict:
    """
    Fetch user emails from the tenant's data plane schema.

    Args:
        tenant_id: The tenant ID to query

    Returns:
        Dictionary with status and users list
    """
    try:
        print(f"Querying users for tenant: {tenant_id}", file=sys.stderr)

        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            # Query users from the tenant schema
            stmt = select(User).order_by(User.email)
            result = db_session.execute(stmt)
            users = [user.email for user in result.scalars()]

        return {"status": "success", "users": users}

    except Exception as e:
        error_msg = str(e)
        print(f"Error fetching users: {error_msg}", file=sys.stderr)
        # Check if it's a schema not found error
        if "does not exist" in error_msg:
            return {
                "status": "not_found",
                "message": f"Schema '{tenant_id}' does not exist",
                "users": [],
            }
        return {"status": "error", "message": error_msg, "users": []}


def main() -> None:
    if len(sys.argv) != 2:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "Usage: python get_tenant_users.py <tenant_id>",
                }
            )
        )
        sys.exit(1)

    tenant_id = sys.argv[1]

    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    result = get_tenant_users(tenant_id)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
