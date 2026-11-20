"""Migration 170d8004af5b creates chat_artifact and chat_artifact_version, and
its downgrade drops them."""

from sqlalchemy import Engine, create_engine, text

from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "e08a3dc8052a"
REVISION = "170d8004af5b"


def _tables(engine: Engine) -> tuple[str | None, str | None]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT to_regclass('chat_artifact')::text, "
                "to_regclass('chat_artifact_version')::text"
            )
        ).one()
    return row[0], row[1]


def test_upgrade_creates_and_downgrade_drops_the_artifact_tables() -> None:
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
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
        downgrade_postgres(
            database=POSTGRES_DB,
            config_name="alembic",
            revision=PREVIOUS_REVISION,
        )
        assert _tables(engine) == (None, None)

        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=REVISION)
        assert _tables(engine) == ("chat_artifact", "chat_artifact_version")

        downgrade_postgres(
            database=POSTGRES_DB,
            config_name="alembic",
            revision=PREVIOUS_REVISION,
        )
        assert _tables(engine) == (None, None)
    finally:
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
        engine.dispose()
