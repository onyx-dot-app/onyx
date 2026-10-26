"""Tests for migration ca7cc9a98a6b, which widens search_settings.reclaim_status
and rewrites "RECLAIMD" rows to "RECLAIMED".

Migration b3f1c9a27d84 sized the column to the longest IndexReclaimStatus member
when it ran. A fresh install now gets VARCHAR(9), so these tests set VARCHAR(8)
by hand to get the column that databases migrated before RECLAIMED have."""

from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DataError

from onyx.configs.app_configs import (
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.db.enums import IndexReclaimStatus
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "d7f46adc4d49"
WIDEN_REVISION = "ca7cc9a98a6b"
# The length of the column on databases migrated before RECLAIMED was added.
PRE_RECLAIMED_LENGTH = 8
WIDENED_LENGTH = 64
# The fresh-install length before this migration, which its downgrade restores.
DOWNGRADED_LENGTH = 9


def _engine() -> Engine:
    return create_engine(
        build_connection_string(
            db="postgres",
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            db_api=SYNC_DB_API,
        )
    )


def _current_revision(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()


def _reclaim_status_length(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'search_settings' "
                "AND column_name = 'reclaim_status'"
            )
        ).scalar_one()


def _set_reclaim_status(engine: Engine, search_settings_id: int, value: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE search_settings SET reclaim_status = :value WHERE id = :id"),
            {"value": value, "id": search_settings_id},
        )


def _get_reclaim_status(engine: Engine, search_settings_id: int) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT reclaim_status FROM search_settings WHERE id = :id"),
            {"id": search_settings_id},
        ).scalar_one()


@pytest.fixture(scope="module")
def engine() -> Generator[Engine, None, None]:
    downgrade_postgres(
        database="postgres", config_name="alembic", revision="base", clear_data=True
    )
    upgrade_postgres(
        database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
    )
    engine = _engine()
    try:
        yield engine
    finally:
        upgrade_postgres(database="postgres", config_name="alembic", revision="head")
        # The tests write reclaim_status; leave no value for a later test to see.
        with engine.begin() as conn:
            conn.execute(text("UPDATE search_settings SET reclaim_status = NULL"))
        engine.dispose()


@pytest.fixture
def search_settings_id_at_pre_reclaimed_length(engine: Engine) -> int:
    """Puts the database at the revision before the widen, with the column at
    its pre-RECLAIMED length. Returns the id of a search_settings row."""
    if _current_revision(engine) == WIDEN_REVISION:
        downgrade_postgres(
            database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
        )
    assert _current_revision(engine) == PREVIOUS_REVISION
    with engine.begin() as conn:
        conn.execute(text("UPDATE search_settings SET reclaim_status = NULL"))
        conn.execute(
            text(
                "ALTER TABLE search_settings ALTER COLUMN reclaim_status "
                f"TYPE VARCHAR({PRE_RECLAIMED_LENGTH})"
            )
        )
        search_settings_id = conn.execute(
            text("SELECT min(id) FROM search_settings")
        ).scalar_one()
    # The migrations seed search_settings rows.
    assert search_settings_id is not None
    return search_settings_id


def test_upgrade_lets_every_reclaim_status_be_written(
    engine: Engine, search_settings_id_at_pre_reclaimed_length: int
) -> None:
    search_settings_id = search_settings_id_at_pre_reclaimed_length
    with pytest.raises(DataError, match="value too long"):
        _set_reclaim_status(
            engine, search_settings_id, IndexReclaimStatus.RECLAIMED.value
        )

    upgrade_postgres(
        database="postgres", config_name="alembic", revision=WIDEN_REVISION
    )

    assert _reclaim_status_length(engine) == WIDENED_LENGTH
    for reclaim_status in IndexReclaimStatus:
        _set_reclaim_status(engine, search_settings_id, reclaim_status.value)
        assert _get_reclaim_status(engine, search_settings_id) == reclaim_status.value


def test_upgrade_rewrites_the_short_reclaimed_value(
    engine: Engine, search_settings_id_at_pre_reclaimed_length: int
) -> None:
    """Releases without this migration write RECLAIMED as "RECLAIMD"."""
    search_settings_id = search_settings_id_at_pre_reclaimed_length
    _set_reclaim_status(engine, search_settings_id, "RECLAIMD")

    upgrade_postgres(
        database="postgres", config_name="alembic", revision=WIDEN_REVISION
    )

    assert (
        _get_reclaim_status(engine, search_settings_id)
        == IndexReclaimStatus.RECLAIMED.value
    )


def test_downgrade_keeps_reclaimed_rows(
    engine: Engine, search_settings_id_at_pre_reclaimed_length: int
) -> None:
    search_settings_id = search_settings_id_at_pre_reclaimed_length
    upgrade_postgres(
        database="postgres", config_name="alembic", revision=WIDEN_REVISION
    )
    _set_reclaim_status(engine, search_settings_id, IndexReclaimStatus.RECLAIMED.value)

    downgrade_postgres(
        database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
    )

    assert _reclaim_status_length(engine) == DOWNGRADED_LENGTH
    assert (
        _get_reclaim_status(engine, search_settings_id)
        == IndexReclaimStatus.RECLAIMED.value
    )
