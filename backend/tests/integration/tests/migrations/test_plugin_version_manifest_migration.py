from collections.abc import Generator

import pytest
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

PREVIOUS_REVISION = "7a3c9e5b1d08"
REVISION = "2d7510746863"


def _engine() -> Engine:
    return create_engine(
        build_connection_string(
            db=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            db_api=SYNC_DB_API,
        )
    )


def _columns(engine: Engine) -> dict[str, tuple[str, str]]:
    with engine.connect() as conn:
        return {
            name: (data_type, nullable)
            for name, data_type, nullable in conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'plugin_version' "
                    "AND column_name IN ('manifest', 'needs')"
                )
            )
        }


@pytest.fixture(scope="module")
def engine() -> Generator[Engine, None, None]:
    engine = _engine()
    try:
        yield engine
    finally:
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
        engine.dispose()


def test_upgrade_downgrade_upgrade(engine: Engine) -> None:
    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
    )
    assert _columns(engine) == {}

    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=REVISION)
    assert _columns(engine) == {
        "manifest": ("jsonb", "YES"),
        "needs": ("jsonb", "YES"),
    }

    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
    )
    assert _columns(engine) == {}

    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=REVISION)
    assert set(_columns(engine)) == {"manifest", "needs"}
