import logging
import time

import psycopg2
import requests

from alembic import command
from alembic.config import Config
from danswer.configs.app_configs import POSTGRES_HOST
from danswer.configs.app_configs import POSTGRES_PASSWORD
from danswer.configs.app_configs import POSTGRES_PORT
from danswer.configs.app_configs import POSTGRES_USER
from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.engine import build_connection_string
from danswer.db.engine import get_session_context_manager
from danswer.db.engine import SYNC_DB_API
from danswer.db.swap_index import check_index_swap
from danswer.document_index.vespa.index import DOCUMENT_ID_ENDPOINT
from danswer.document_index.vespa.index import VespaIndex
from danswer.main import setup_postgres
from danswer.main import setup_vespa
from tests.integration.common_utils.llm import seed_default_openai_provider


def _run_migrations(
    database_url: str, direction: str = "upgrade", revision: str = "head"
) -> None:
    # hide info logs emitted during migration
    logging.getLogger("alembic").setLevel(logging.CRITICAL)

    # Create an Alembic configuration object
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_section_option("logger_alembic", "level", "WARN")

    # Set the SQLAlchemy URL in the Alembic configuration
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)

    # Run the migration
    if direction == "upgrade":
        command.upgrade(alembic_cfg, revision)
    elif direction == "downgrade":
        command.downgrade(alembic_cfg, revision)
    else:
        raise ValueError(
            f"Invalid direction: {direction}. Must be 'upgrade' or 'downgrade'."
        )

    logging.getLogger("alembic").setLevel(logging.INFO)


def reset_postgres(database: str = "postgres") -> None:
    """Reset the Postgres database."""

    # NOTE: need to delete all rows to allow migrations to be rolled back
    # as there are a few downgrades that don't properly handle data in tables
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

        # Don't touch Kombu
        if table_name == "kombu_message" or table_name == "kombu_queue":
            continue

        cur.execute(f'DELETE FROM "{table_name}"')

    # Re-enable triggers
    cur.execute("SET session_replication_role = 'origin';")

    conn.commit()
    cur.close()
    conn.close()

    # downgrade to base + upgrade back to head
    conn_str = build_connection_string(
        db=database,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        db_api=SYNC_DB_API,
    )
    _run_migrations(
        conn_str,
        direction="downgrade",
        revision="base",
    )
    _run_migrations(
        conn_str,
        direction="upgrade",
        revision="head",
    )

    # do the same thing as we do on API server startup
    with get_session_context_manager() as db_session:
        setup_postgres(db_session)


def reset_vespa() -> None:
    """Wipe all data from the Vespa index."""
    with get_session_context_manager() as db_session:
        # swap to the correct default model
        check_index_swap(db_session)

        current_model = get_current_db_embedding_model(db_session)
        index_name = current_model.index_name

    setup_vespa(
        document_index=VespaIndex(index_name=index_name, secondary_index_name=None),
        db_embedding_model=current_model,
        secondary_db_embedding_model=None,
    )

    for _ in range(5):
        try:
            continuation = None
            should_continue = True
            while should_continue:
                params = {"selection": "true", "cluster": "danswer_index"}
                if continuation:
                    params = {**params, "continuation": continuation}
                response = requests.delete(
                    DOCUMENT_ID_ENDPOINT.format(index_name=index_name), params=params
                )
                response.raise_for_status()

                response_json = response.json()

                continuation = response_json.get("continuation")
                should_continue = bool(continuation)

            break
        except Exception as e:
            print(f"Error deleting documents: {e}")
            time.sleep(5)


def reset_all() -> None:
    """Reset both Postgres and Vespa."""
    print("Resetting Postgres...")
    reset_postgres()
    print("Resetting Vespa...")
    reset_vespa()
    print("Seeding LLM Providers...")
    seed_default_openai_provider()
    print("Finished resetting all.")
