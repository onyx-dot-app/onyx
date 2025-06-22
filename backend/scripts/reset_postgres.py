import os
import sys

import psycopg2
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_sqlalchemy_engine

# makes it so `PYTHONPATH=.` is not required when running this script
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from onyx.configs.app_configs import POSTGRES_DB  # noqa: E402
from onyx.configs.app_configs import POSTGRES_HOST  # noqa: E402
from onyx.configs.app_configs import POSTGRES_PASSWORD  # noqa: E402
from onyx.configs.app_configs import POSTGRES_PORT  # noqa: E402
from onyx.configs.app_configs import POSTGRES_USER  # noqa: E402
from onyx.db.credentials import create_initial_public_credential  # noqa: E402


def wipe_all_rows(database: str) -> None:
    conn = psycopg2.connect(
        dbname=database,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
    )
    cur = conn.cursor()

    # Disable triggers to prevent foreign key constraints from being checked
    cur.execute("SET session_replication_role = 'replica';")

    # Fetch all table names in the current database
    cur.execute(
        """
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
    """
    )

    tables = cur.fetchall()

    for table in tables:
        table_name = table[0]

        # Don't touch migration history
        if table_name == "alembic_version":
            continue

        print(f"Deleting all rows from {table_name}...")
        cur.execute(f'DELETE FROM "{table_name}"')

    # Re-enable triggers
    cur.execute("SET session_replication_role = 'origin';")

    conn.commit()
    cur.close()
    conn.close()
    print("Finished wiping all rows.")


if __name__ == "__main__":
    print("Cleaning up all Onyx tables")
    wipe_all_rows(POSTGRES_DB)
    with Session(get_sqlalchemy_engine(), expire_on_commit=False) as db_session:
        create_initial_public_credential(db_session)
    print("To keep data consistent, it's best to wipe the document index as well.")
    print(
        "To be safe, it's best to restart the Onyx services (API Server and Background Tasks"
    )
