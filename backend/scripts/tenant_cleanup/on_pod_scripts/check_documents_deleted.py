#!/usr/bin/env python3
"""
Script to check for remaining ConnectorCredentialPairs and Documents in a tenant's schema.
Must be run on a pod with access to the data plane PostgreSQL database.

Usage:
    python check_documents_deleted.py <tenant_id>

Output:
    JSON object with status, message, and counts of remaining records
"""

import json
import sys

from sqlalchemy import func
from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document


def check_documents_deleted(tenant_id: str) -> dict:
    """
    Check for remaining ConnectorCredentialPairs and Documents in tenant schema.

    Args:
        tenant_id: The tenant ID to query

    Returns:
        Dictionary with status and counts of remaining records
    """
    try:
        print(
            f"Checking for remaining documents in tenant: {tenant_id}",
            file=sys.stderr,
        )

        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            # Count ConnectorCredentialPairs
            cc_count = db_session.scalar(
                select(func.count()).select_from(ConnectorCredentialPair)
            )

            # Count Documents
            doc_count = db_session.scalar(select(func.count()).select_from(Document))

        # Handle None values from scalar (should not happen but mypy needs it)
        cc_count = cc_count or 0
        doc_count = doc_count or 0

        # If any records remain beyond acceptable thresholds, return error status
        is_deletable = cc_count == 0 or doc_count <= 5
        if not is_deletable:
            return {
                "status": "error",
                "message": (
                    f"Found {cc_count} ConnectorCredentialPair(s) and {doc_count} Document(s) "
                    "still remaining. Must have 0 ConnectorCredentialPairs and no more than "
                    "5 Documents before cleanup."
                ),
                "connector_credential_pair_count": cc_count,
                "document_count": doc_count,
            }

        # All clear
        return {
            "status": "success",
            "message": "No ConnectorCredentialPairs or Documents found - safe to proceed",
            "connector_credential_pair_count": 0,
            "document_count": 0,
        }

    except Exception as e:
        error_msg = str(e)
        print(f"Error checking documents: {error_msg}", file=sys.stderr)
        # Check if it's a schema not found error
        if "does not exist" in error_msg:
            return {
                "status": "not_found",
                "message": f"Schema '{tenant_id}' does not exist",
            }
        return {"status": "error", "message": f"Error checking documents: {error_msg}"}


def main() -> None:
    if len(sys.argv) != 2:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "Usage: python check_documents_deleted.py <tenant_id>",
                }
            )
        )
        sys.exit(1)

    tenant_id = sys.argv[1]

    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    result = check_documents_deleted(tenant_id)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
