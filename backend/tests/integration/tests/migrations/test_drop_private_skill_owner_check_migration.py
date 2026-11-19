"""Tests for migration 65f8d8cd1bf3, which drops ck_private_skill_has_owner.

Code no longer writes the old custom skill rows. A user delete sets
author_user_id to NULL on a stale private row, which the check refused."""

from collections.abc import Generator
from uuid import UUID, uuid4

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

PREVIOUS_REVISION = "730bce2814a0"
DROP_REVISION = "65f8d8cd1bf3"
CHECK_NAME = "ck_private_skill_has_owner"


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


def _current_revision(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()


def _check_validated(engine: Engine) -> bool | None:
    """Whether the check is validated; None when it does not exist."""
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT convalidated FROM pg_constraint "
                "WHERE conrelid = 'skill'::regclass AND conname = :name"
            ),
            {"name": CHECK_NAME},
        ).scalar_one_or_none()


def _insert_ownerless_private_skill(engine: Engine) -> UUID:
    """A custom skill row with no author and no organization access."""
    skill_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO skill (id, name, description, bundle_file_id, "
                "bundle_sha256, author_user_id, public_permission) VALUES "
                "(:id, :name, '', :bundle, :sha, NULL, NULL)"
            ),
            {
                "id": skill_id,
                "name": f"ownerless-{skill_id.hex[:8]}",
                "bundle": f"bundle-{skill_id.hex}",
                "sha": "0" * 64,
            },
        )
    return skill_id


def _delete_skill(engine: Engine, skill_id: UUID) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM skill WHERE id = :id"), {"id": skill_id})


@pytest.fixture(scope="module")
def engine() -> Generator[Engine, None, None]:
    engine = _engine()
    try:
        yield engine
    finally:
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
        engine.dispose()


def test_upgrade_stores_a_private_skill_row_with_no_author(engine: Engine) -> None:
    if _current_revision(engine) != PREVIOUS_REVISION:
        downgrade_postgres(
            database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
        )
    assert _check_validated(engine) is not None
    with pytest.raises(IntegrityError, match=CHECK_NAME):
        _insert_ownerless_private_skill(engine)

    upgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=DROP_REVISION
    )

    assert _check_validated(engine) is None
    skill_id = _insert_ownerless_private_skill(engine)
    _delete_skill(engine, skill_id)


def test_downgrade_adds_the_check_back_without_validating(engine: Engine) -> None:
    if _current_revision(engine) != DROP_REVISION:
        upgrade_postgres(
            database=POSTGRES_DB, config_name="alembic", revision=DROP_REVISION
        )
    stale_id = _insert_ownerless_private_skill(engine)
    try:
        downgrade_postgres(
            database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
        )

        assert _check_validated(engine) is False
        with pytest.raises(IntegrityError, match=CHECK_NAME):
            _insert_ownerless_private_skill(engine)
    finally:
        _delete_skill(engine, stale_id)
