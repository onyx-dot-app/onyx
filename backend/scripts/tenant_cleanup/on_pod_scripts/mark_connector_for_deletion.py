#!/usr/bin/env python3
"""
Script to mark a connector credential pair for deletion.
Runs on a Kubernetes pod with access to the data plane database.

Usage:
    python mark_connector_for_deletion.py <tenant_id> <cc_pair_id>

Output:
    JSON to stdout with structure:
    {
        "status": "success" | "error",
        "message": str
    }
"""

import json
import sys

from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_credential_pair import update_connector_credential_pair_from_id
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.index_attempt import cancel_indexing_attempts_for_ccpair


def mark_connector_for_deletion(tenant_id: str, cc_pair_id: int) -> dict:
    """Mark a connector credential pair for deletion.

    Args:
        tenant_id: The tenant ID
        cc_pair_id: The connector credential pair ID

    Returns:
        Dict with status and message
    """
    try:
        print(
            f"Marking connector credential pair {cc_pair_id} for deletion",
            file=sys.stderr,
        )

        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            # Get the connector credential pair
            cc_pair = get_connector_credential_pair_from_id(
                db_session=db_session,
                cc_pair_id=cc_pair_id,
            )

            if not cc_pair:
                return {
                    "status": "error",
                    "message": f"Connector credential pair {cc_pair_id} not found",
                }

            # Cancel any scheduled indexing attempts
            print(
                f"Canceling indexing attempts for CC pair {cc_pair_id}",
                file=sys.stderr,
            )
            cancel_indexing_attempts_for_ccpair(
                cc_pair_id=cc_pair.id,
                db_session=db_session,
                include_secondary_index=True,
            )

            # Mark as deleting
            print(
                f"Updating CC pair {cc_pair_id} status to DELETING",
                file=sys.stderr,
            )
            update_connector_credential_pair_from_id(
                db_session=db_session,
                cc_pair_id=cc_pair.id,
                status=ConnectorCredentialPairStatus.DELETING,
            )

            db_session.commit()

            # Trigger the deletion check task
            print(
                "Triggering connector deletion check task",
                file=sys.stderr,
            )
            client_app.send_task(
                OnyxCeleryTask.CHECK_FOR_CONNECTOR_DELETION,
                priority=OnyxCeleryPriority.HIGH,
                kwargs={"tenant_id": tenant_id},
            )

            return {
                "status": "success",
                "message": f"Marked connector credential pair {cc_pair_id} for deletion",
            }

    except Exception as e:
        print(
            f"Error marking connector for deletion: {e}",
            file=sys.stderr,
        )
        return {
            "status": "error",
            "message": str(e),
        }


def main() -> None:
    if len(sys.argv) != 3:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "Usage: python mark_connector_for_deletion.py <tenant_id> <cc_pair_id>",
                }
            )
        )
        sys.exit(1)

    tenant_id = sys.argv[1]
    try:
        cc_pair_id = int(sys.argv[2])
    except ValueError:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "cc_pair_id must be an integer",
                }
            )
        )
        sys.exit(1)

    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    result = mark_connector_for_deletion(tenant_id, cc_pair_id)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
