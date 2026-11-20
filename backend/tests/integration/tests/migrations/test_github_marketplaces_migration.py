from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "2d7510746863"
REVISION = "e08a3dc8052a"


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


def _marketplace_columns(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return set(
            conn.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'plugin_marketplace'"
                )
            )
        )


def _seed_github_marketplace(engine: Engine) -> None:
    marketplace_id = uuid4()
    plugin_id = uuid4()
    version_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO plugin_marketplace (id, kind, name, provider_config) "
                "VALUES (:id, 'github', 'acme/tools', "
                '\'{"owner": "acme", "repo": "tools"}\')'
            ),
            {"id": marketplace_id},
        )
        conn.execute(
            text(
                "INSERT INTO plugin (id, name, description, marketplace_id, "
                "current_version_id, published_version_id, marketplace_entry_key) "
                "VALUES (:id, 'formatter', '', :marketplace_id, :version_id, "
                ":version_id, 'formatter')"
            ),
            {
                "id": plugin_id,
                "marketplace_id": marketplace_id,
                "version_id": version_id,
            },
        )
        conn.execute(
            text(
                "INSERT INTO plugin_version (id, plugin_id, version_number, "
                "source_tree_sha) VALUES (:id, :plugin_id, 1, :tree_sha)"
            ),
            {"id": version_id, "plugin_id": plugin_id, "tree_sha": "a" * 40},
        )


def _github_rows(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM plugin_marketplace WHERE kind = 'github'")
        ).scalar_one()


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
    assert "provider_config" not in _marketplace_columns(engine)

    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=REVISION)
    assert {
        "provider_config",
        "login_user_id",
        "last_synced_revision",
        "last_synced_tree_sha",
        "last_synced_at",
        "last_error",
        "sync_requested_at",
        "pending_delete_revision",
        "last_sync_result",
    } <= _marketplace_columns(engine)
    _seed_github_marketplace(engine)
    assert _github_rows(engine) == 1

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO plugin_marketplace (id, kind, name) "
                "VALUES (:id, 'user_uploads', 'My uploads')"
            ),
            {"id": uuid4()},
        )

    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
    )
    assert "provider_config" not in _marketplace_columns(engine)
    assert _github_rows(engine) == 0
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM plugin WHERE marketplace_id NOT IN "
                    "(SELECT id FROM plugin_marketplace)"
                )
            ).scalar_one()
            == 0
        )

    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=REVISION)
    assert "provider_config" in _marketplace_columns(engine)
    with engine.connect() as conn:
        assert conn.execute(
            text(
                "SELECT indisvalid FROM pg_index "
                "WHERE indexrelid = to_regclass('uq_plugin_marketplace_entry_key')"
            )
        ).scalar_one()
