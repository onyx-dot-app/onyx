#!/usr/bin/env python3
"""
Script to report a tenant's most recent chat query and Craft session.

The cleanup scripts run against a CSV that an earlier analyze pass produced, and that
snapshot can be days old. This lets the cleanup step re-read activity at deletion time,
so a tenant that became active in the meantime is not dropped.

Must be run on a pod with access to the data plane PostgreSQL database.

Usage:
    python check_tenant_activity.py <tenant_id>

Output:
    JSON object with status and the two activity timestamps
"""

import json
import sys

from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError

from onyx.configs.constants import MessageType
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_tenant
from onyx.db.models import BuildSession, ChatMessage


def check_tenant_activity(tenant_id: str) -> dict:
    """Return the latest chat and Craft activity for a tenant.

    Uses a tenant-scoped session so the query reaches the shard holding this
    tenant rather than only the catalog shard.
    """
    print(f"Checking activity for tenant: {tenant_id}", file=sys.stderr)

    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        last_query_time = db_session.scalar(
            select(func.max(ChatMessage.time_sent)).where(
                ChatMessage.message_type == MessageType.USER
            )
        )

        # build_session only exists once a tenant has used Craft.
        try:
            last_craft_activity_time = db_session.scalar(
                select(func.max(BuildSession.last_activity_at))
            )
        except ProgrammingError:
            db_session.rollback()
            last_craft_activity_time = None

    return {
        "status": "success",
        "last_query_time": last_query_time.isoformat() if last_query_time else None,
        "last_craft_activity_time": (
            last_craft_activity_time.isoformat() if last_craft_activity_time else None
        ),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("tenant_id required", file=sys.stderr)
        sys.exit(1)

    tenant_id = sys.argv[1]
    SqlEngine.init_engine(pool_size=2, max_overflow=0)

    try:
        print(json.dumps(check_tenant_activity(tenant_id)))
    except ProgrammingError:
        # No schema for this tenant on its shard.
        print(json.dumps({"status": "not_found"}))
    except Exception as e:
        print(f"Failed to check activity for {tenant_id}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
