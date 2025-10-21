#!/usr/bin/env python3
"""
Script to mark connector credential pairs for deletion.
Runs on a Kubernetes pod with access to the data plane database.

Usage:
    # Mark a specific connector for deletion
    python mark_connector_for_deletion.py <tenant_id> <cc_pair_id>

    # Mark all connectors for deletion
    python mark_connector_for_deletion.py <tenant_id> --all

Output:
    JSON to stdout with structure:
    {
        "status": "success" | "error",
        "message": str,
        "deleted_count": int (when using --all),
        "timing": {
            "total_seconds": float,
            "per_connector": [...]
        }
    }
"""

import json
import sys
import time
from typing import Any

from sqlalchemy.orm import Session

from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_credential_pair import get_connector_credential_pairs
from onyx.db.connector_credential_pair import update_connector_credential_pair_from_id
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.index_attempt import cancel_indexing_attempts_for_ccpair


def mark_connector_for_deletion(
    tenant_id: str, cc_pair_id: int, db_session: Session | None = None
) -> dict[str, Any]:
    """Mark a connector credential pair for deletion.

    Args:
        tenant_id: The tenant ID
        cc_pair_id: The connector credential pair ID
        db_session: Optional database session (if None, creates a new one)

    Returns:
        Dict with status, message, and timing
    """
    timing: dict[str, float] = {}
    start_time: float = time.time()

    try:
        print(
            f"Marking connector credential pair {cc_pair_id} for deletion",
            file=sys.stderr,
        )

        def _mark_deletion(db_sess: Session) -> dict[str, Any]:
            # Get the connector credential pair
            fetch_start: float = time.time()
            cc_pair = get_connector_credential_pair_from_id(
                db_session=db_sess,
                cc_pair_id=cc_pair_id,
            )
            timing["fetch_cc_pair_seconds"] = time.time() - fetch_start

            if not cc_pair:
                return {
                    "status": "error",
                    "message": f"Connector credential pair {cc_pair_id} not found",
                    "timing": timing,
                }

            # Cancel any scheduled indexing attempts
            print(
                f"Canceling indexing attempts for CC pair {cc_pair_id}",
                file=sys.stderr,
            )
            cancel_start: float = time.time()
            cancel_indexing_attempts_for_ccpair(
                cc_pair_id=cc_pair.id,
                db_session=db_sess,
                include_secondary_index=True,
            )
            timing["cancel_indexing_seconds"] = time.time() - cancel_start

            # Mark as deleting
            print(
                f"Updating CC pair {cc_pair_id} status to DELETING",
                file=sys.stderr,
            )
            update_start: float = time.time()
            update_connector_credential_pair_from_id(
                db_session=db_sess,
                cc_pair_id=cc_pair.id,
                status=ConnectorCredentialPairStatus.DELETING,
            )
            timing["update_status_seconds"] = time.time() - update_start

            commit_start: float = time.time()
            db_sess.commit()
            timing["commit_seconds"] = time.time() - commit_start

            return {
                "status": "success",
                "message": f"Marked connector credential pair {cc_pair_id} for deletion",
                "timing": timing,
            }

        result: dict[str, Any]
        if db_session:
            result = _mark_deletion(db_session)
        else:
            with get_session_with_tenant(tenant_id=tenant_id) as db_sess:
                result = _mark_deletion(db_sess)

        # Trigger the deletion check task
        print(
            "Triggering connector deletion check task",
            file=sys.stderr,
        )
        task_start: float = time.time()
        client_app.send_task(
            OnyxCeleryTask.CHECK_FOR_CONNECTOR_DELETION,
            priority=OnyxCeleryPriority.HIGH,
            kwargs={"tenant_id": tenant_id},
        )
        timing["send_task_seconds"] = time.time() - task_start
        timing["total_seconds"] = time.time() - start_time

        result["timing"] = timing
        return result

    except Exception as e:
        print(
            f"Error marking connector for deletion: {e}",
            file=sys.stderr,
        )
        timing["total_seconds"] = time.time() - start_time
        return {
            "status": "error",
            "message": str(e),
            "timing": timing,
        }


def mark_all_connectors_for_deletion(tenant_id: str) -> dict[str, Any]:
    """Mark all connector credential pairs for a tenant for deletion.

    Args:
        tenant_id: The tenant ID

    Returns:
        Dict with status, message, deleted_count, and timing
    """
    overall_start: float = time.time()
    per_connector_timing: list[dict[str, Any]] = []

    try:
        print(
            f"Marking all connector credential pairs for tenant {tenant_id} for deletion",
            file=sys.stderr,
        )

        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            # Get all connector credential pairs
            fetch_all_start: float = time.time()
            cc_pairs = get_connector_credential_pairs(db_session=db_session)
            fetch_all_time: float = time.time() - fetch_all_start

            print(
                f"Found {len(cc_pairs)} connector credential pairs to delete",
                file=sys.stderr,
            )

            if not cc_pairs:
                return {
                    "status": "success",
                    "message": "No connector credential pairs found for tenant",
                    "deleted_count": 0,
                    "timing": {
                        "fetch_all_seconds": fetch_all_time,
                        "total_seconds": time.time() - overall_start,
                    },
                }

            deleted_count: int = 0
            errors: list[str] = []

            for cc_pair in cc_pairs:
                connector_start: float = time.time()
                print(
                    f"Processing CC pair {cc_pair.id} ({deleted_count + 1}/{len(cc_pairs)})",
                    file=sys.stderr,
                )

                # Cancel any scheduled indexing attempts
                cancel_start: float = time.time()
                cancel_indexing_attempts_for_ccpair(
                    cc_pair_id=cc_pair.id,
                    db_session=db_session,
                    include_secondary_index=True,
                )
                cancel_time: float = time.time() - cancel_start

                # Mark as deleting
                update_start: float = time.time()
                try:
                    update_connector_credential_pair_from_id(
                        db_session=db_session,
                        cc_pair_id=cc_pair.id,
                        status=ConnectorCredentialPairStatus.DELETING,
                    )
                    deleted_count += 1
                except Exception as e:
                    errors.append(f"CC pair {cc_pair.id}: {str(e)}")
                    print(
                        f"Error updating CC pair {cc_pair.id}: {e}",
                        file=sys.stderr,
                    )

                update_time: float = time.time() - update_start
                connector_total_time: float = time.time() - connector_start

                per_connector_timing.append(
                    {
                        "cc_pair_id": cc_pair.id,
                        "cancel_indexing_seconds": cancel_time,
                        "update_status_seconds": update_time,
                        "total_seconds": connector_total_time,
                    }
                )

            # Commit all changes
            commit_start: float = time.time()
            db_session.commit()
            commit_time: float = time.time() - commit_start

        # Trigger the deletion check task
        print(
            "Triggering connector deletion check task",
            file=sys.stderr,
        )
        task_start: float = time.time()
        client_app.send_task(
            OnyxCeleryTask.CHECK_FOR_CONNECTOR_DELETION,
            priority=OnyxCeleryPriority.HIGH,
            kwargs={"tenant_id": tenant_id},
        )
        task_time: float = time.time() - task_start

        total_time: float = time.time() - overall_start

        result: dict[str, Any] = {
            "status": "success",
            "message": f"Marked {deleted_count} connector credential pairs for deletion",
            "deleted_count": deleted_count,
            "timing": {
                "fetch_all_seconds": fetch_all_time,
                "commit_seconds": commit_time,
                "send_task_seconds": task_time,
                "total_seconds": total_time,
                "per_connector": per_connector_timing,
            },
        }

        if errors:
            result["errors"] = errors

        return result

    except Exception as e:
        print(
            f"Error marking all connectors for deletion: {e}",
            file=sys.stderr,
        )
        return {
            "status": "error",
            "message": str(e),
            "timing": {
                "total_seconds": time.time() - overall_start,
                "per_connector": per_connector_timing,
            },
        }


def main() -> None:
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "Usage: python mark_connector_for_deletion.py <tenant_id> [<cc_pair_id>|--all]",
                }
            )
        )
        sys.exit(1)

    tenant_id: str = sys.argv[1]

    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    result: dict[str, Any]
    # Check if we should mark all connectors or just one
    if len(sys.argv) == 3:
        second_arg: str = sys.argv[2]
        if second_arg == "--all":
            result = mark_all_connectors_for_deletion(tenant_id)
        else:
            try:
                cc_pair_id: int = int(second_arg)
                result = mark_connector_for_deletion(tenant_id, cc_pair_id)
            except ValueError:
                print(
                    json.dumps(
                        {
                            "status": "error",
                            "message": "cc_pair_id must be an integer or use --all",
                        }
                    )
                )
                sys.exit(1)
    else:
        # If only tenant_id is provided, show error
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "Usage: python mark_connector_for_deletion.py <tenant_id> [<cc_pair_id>|--all]",
                }
            )
        )
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
