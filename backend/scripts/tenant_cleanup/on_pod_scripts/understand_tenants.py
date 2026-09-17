import json
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_shared_schema


def get_tenant_activity_summary(session: Session) -> list[dict[str, Any]]:
    """Return chat/Craft activity, document count, and user count per tenant."""

    # Step 1: fetch all tenant schemas
    tenant_schemas = [
        row[0]
        for row in session.execute(
            text("""
            SELECT nspname
            FROM pg_namespace
            WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'public')
                AND nspname NOT LIKE 'pg_toast%%'
                AND nspname NOT LIKE 'pg_temp%%'
            ORDER BY nspname
        """)
        )
    ]

    print(f"Found {len(tenant_schemas)} tenant schemas", file=sys.stderr)

    schemas_with_build_sessions = {
        row[0]
        for row in session.execute(
            text("""
            SELECT schemaname
            FROM pg_tables
            WHERE tablename = 'build_session'
                AND schemaname = ANY(:tenant_schemas)
            """),
            {"tenant_schemas": tenant_schemas},
        )
    }

    summaries = []

    # Step 2: loop through each tenant schema
    for idx, schema in enumerate(tenant_schemas):
        if idx % 100 == 0:
            print(f"Processing tenant {idx}/{len(tenant_schemas)}", file=sys.stderr)

        try:
            craft_activity_select = (
                f'(SELECT MAX(last_activity_at) FROM "{schema}".build_session)'
                if schema in schemas_with_build_sessions
                else "NULL::timestamptz"
            )

            # Use a single query to get all data at once
            query = text(f"""
                SELECT
                    :tenant_id AS tenant_id,
                    (
                        SELECT time_sent
                        FROM "{schema}".chat_message
                        WHERE message_type = 'USER'
                        ORDER BY time_sent DESC
                        LIMIT 1
                    ) AS last_query_time,
                    (
                        SELECT message
                        FROM "{schema}".chat_message
                        WHERE message_type = 'USER'
                        ORDER BY time_sent DESC
                        LIMIT 1
                    ) AS last_query_text,
                    {craft_activity_select} AS last_craft_activity_time,
                    (SELECT COUNT(*) FROM "{schema}".document) AS num_documents,
                    (SELECT COUNT(*) FROM "{schema}".user) AS num_users
            """)

            result = session.execute(query, {"tenant_id": schema}).mappings().first()

            if result:
                summaries.append(dict(result))

        except ProgrammingError as e:
            # schema may be missing a table
            print(f"Error processing schema {schema}: {e}", file=sys.stderr)
            session.rollback()
            continue
        except Exception as e:
            print(f"Unexpected error processing schema {schema}: {e}", file=sys.stderr)
            session.rollback()
            continue

    return summaries


def main() -> None:
    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    with get_session_with_shared_schema() as session:
        summaries = get_tenant_activity_summary(session)

    print(json.dumps(summaries, indent=2, default=str))


if __name__ == "__main__":
    main()
