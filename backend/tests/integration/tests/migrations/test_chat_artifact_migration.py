"""Migration 170d8004af5b creates chat_artifact and chat_artifact_version, with
the version's thumbnail link, and its downgrade drops them."""

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

PREVIOUS_REVISION = "3f7b2c9d4e61"
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


def _thumbnail_link(engine: Engine) -> tuple[str, str, bool] | None:
    """The referenced table and delete rule of the thumbnail column's foreign
    key, and whether the column is unique."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT fk.confrelid::regclass::text, fk.confdeltype::text, "
                "EXISTS (SELECT 1 FROM pg_constraint u "
                "WHERE u.conrelid = fk.conrelid AND u.contype = 'u' "
                "AND u.conkey = fk.conkey) "
                "FROM pg_constraint fk "
                "JOIN pg_attribute a ON a.attrelid = fk.conrelid "
                "AND a.attnum = ANY (fk.conkey) "
                "WHERE fk.conrelid = 'chat_artifact_version'::regclass "
                "AND fk.contype = 'f' AND a.attname = 'thumbnail_file_id'"
            )
        ).one_or_none()
    return None if row is None else (row[0], row[1], row[2])


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
        # "n": a deleted thumbnail file clears the link.
        assert _thumbnail_link(engine) == ("file_record", "n", True)

        downgrade_postgres(
            database=POSTGRES_DB,
            config_name="alembic",
            revision=PREVIOUS_REVISION,
        )
        assert _tables(engine) == (None, None)
    finally:
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
        engine.dispose()
