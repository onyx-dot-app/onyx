"""Report a tenant's most recent chat query and Craft session.

The cleanup scripts run against a CSV that an earlier analyze pass produced, and that
snapshot can be days old. This lets the cleanup step re-read activity at deletion time
so a tenant that became active in the meantime is not dropped.
"""

import json
import re
import sys

from sqlalchemy import text

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_shared_schema

TENANT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def main() -> None:
    if len(sys.argv) < 2:
        print("tenant_id required", file=sys.stderr)
        sys.exit(1)

    tenant_id = sys.argv[1]
    if not TENANT_ID_RE.match(tenant_id):
        print(f"unsafe tenant id: {tenant_id!r}", file=sys.stderr)
        sys.exit(1)

    SqlEngine.init_engine(pool_size=2, max_overflow=0)
    with get_session_with_shared_schema() as session:
        exists = session.execute(
            text("SELECT COUNT(*) FROM pg_namespace WHERE nspname = :s"),
            {"s": tenant_id},
        ).scalar()
        if not exists:
            print(json.dumps({"status": "not_found"}))
            return

        # build_session only exists once a tenant has used Craft.
        has_craft = session.execute(
            text(
                "SELECT COUNT(*) FROM pg_tables "
                "WHERE tablename = 'build_session' AND schemaname = :s"
            ),
            {"s": tenant_id},
        ).scalar()
        craft_select = (
            f'(SELECT MAX(last_activity_at) FROM "{tenant_id}".build_session)'
            if has_craft
            else "NULL::timestamptz"
        )

        row = session.execute(
            text(f"""
                SELECT
                    (
                        SELECT MAX(time_sent) FROM "{tenant_id}".chat_message
                        WHERE message_type = 'USER'
                    ) AS last_query_time,
                    {craft_select} AS last_craft_activity_time
            """)
        ).one()

    print(
        json.dumps(
            {
                "status": "success",
                "last_query_time": row[0].isoformat() if row[0] else None,
                "last_craft_activity_time": row[1].isoformat() if row[1] else None,
            }
        )
    )


if __name__ == "__main__":
    main()
