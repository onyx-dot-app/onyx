#!/usr/bin/env python3
"""
Script to fetch connector credential pairs for a tenant.
Runs on a Kubernetes pod with access to the data plane database.

Usage:
    python get_tenant_connectors.py <tenant_id>

Output:
    JSON to stdout with structure:
    {
        "status": "success" | "error",
        "connectors": [
            {
                "id": int,
                "connector_id": int,
                "credential_id": int,
                "name": str,
                "status": str
            },
            ...
        ] (if success),
        "message": str (if error)
    }
"""

import json
import sys

from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import ConnectorCredentialPair


def get_tenant_connectors(tenant_id: str) -> dict:
    """Get all connector credential pairs for a tenant.

    Args:
        tenant_id: The tenant ID to query

    Returns:
        Dict with status and list of connectors or error message
    """
    try:
        print(
            f"Fetching connector credential pairs for tenant: {tenant_id}",
            file=sys.stderr,
        )

        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            # Get all connector credential pairs, excluding user files
            stmt = select(ConnectorCredentialPair).where(
                ConnectorCredentialPair.is_user_file.is_(False)
            )
            cc_pairs = db_session.execute(stmt).scalars().all()

            connectors = [
                {
                    "id": cc.id,
                    "connector_id": cc.connector_id,
                    "credential_id": cc.credential_id,
                    "name": cc.name,
                    "status": cc.status.value,
                }
                for cc in cc_pairs
            ]

            print(
                f"Found {len(connectors)} connector credential pair(s)",
                file=sys.stderr,
            )

            return {
                "status": "success",
                "connectors": connectors,
            }

    except Exception as e:
        print(f"Error fetching connectors: {e}", file=sys.stderr)
        return {
            "status": "error",
            "message": str(e),
        }


def main() -> None:
    if len(sys.argv) != 2:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "Usage: python get_tenant_connectors.py <tenant_id>",
                }
            )
        )
        sys.exit(1)

    tenant_id = sys.argv[1]

    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    result = get_tenant_connectors(tenant_id)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
