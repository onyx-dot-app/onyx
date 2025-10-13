import json
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_shared_schema
from onyx.db.engine.sql_engine import SqlEngine


def get_tenant_activity_summary(session: Session) -> list[dict[str, Any]]:
    """Return a list of dicts, one per tenant, with last query info, doc count, and user count."""

    # Step 1: fetch all tenant schemas
    tenant_schemas = [
        row[0]
        for row in session.execute(
            text(
                """
            SELECT nspname
            FROM pg_namespace
            WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'public')
                AND nspname NOT LIKE 'pg_toast%%'
                AND nspname NOT LIKE 'pg_temp%%'
            ORDER BY nspname
        """
            )
        )
    ]

    print(f"Found {len(tenant_schemas)} tenant schemas", file=sys.stderr)

    summaries = []

    # Step 2: loop through each tenant schema
    for idx, schema in enumerate(tenant_schemas):
        if idx % 100 == 0:
            print(f"Processing tenant {idx}/{len(tenant_schemas)}", file=sys.stderr)

        try:
            # Use a single query to get all data at once
            query = text(
                f"""
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
                    (SELECT COUNT(*) FROM "{schema}".document) AS num_documents,
                    (SELECT COUNT(*) FROM "{schema}".user) AS num_users
            """
            )

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
