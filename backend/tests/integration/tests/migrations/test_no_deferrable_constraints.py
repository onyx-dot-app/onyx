"""No constraint at head is deferrable. backend/AGENTS.md gives the reason."""

from sqlalchemy import create_engine, text

from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import upgrade_postgres


def test_no_deferrable_constraints_at_head() -> None:
    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
    engine = create_engine(
        build_connection_string(
            db=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            db_api=SYNC_DB_API,
        )
    )
    try:
        with engine.connect() as conn:
            deferrable = (
                conn.execute(
                    text(
                        "SELECT conrelid::regclass::text || '.' || conname "
                        "FROM pg_constraint "
                        "WHERE condeferrable AND connamespace = current_schema()::regnamespace"
                    )
                )
                .scalars()
                .all()
            )
    finally:
        engine.dispose()
    assert deferrable == []
