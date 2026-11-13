"""A deploy runs every pending revision in one transaction. The plugin backfills
(cdec9dd9ca3d, 55bf66dd54dd) write rows under deferred FKs, and a later
revision alters the plugin table. 55bf66dd54dd runs the queued checks, or that
ALTER fails on every instance with a custom skill."""

from collections.abc import Generator
from uuid import UUID, uuid4

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

# Before the plugin tables, so both backfills write rows. After them, so only
# the re-sync writes rows.
START_REVISIONS = ("fdaeeca238a1", "cdec9dd9ca3d")


@pytest.fixture(params=START_REVISIONS)
def engine(request: pytest.FixtureRequest) -> Generator[Engine, None, None]:
    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=request.param
    )
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
        yield engine
    finally:
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
        engine.dispose()


@pytest.fixture
def skill_id(engine: Engine) -> Generator[UUID, None, None]:
    skill_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO skill (id, name, description, bundle_file_id, "
                "bundle_sha256, public_permission, is_valid) VALUES "
                "(:id, :name, 'd', :file_id, :sha, 'VIEWER', true)"
            ),
            {
                "id": skill_id,
                "name": f"backfill-{skill_id.hex[:8]}",
                "file_id": f"backfill-{skill_id.hex}",
                "sha": "a" * 64,
            },
        )
    yield skill_id
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM plugin WHERE id = :id"), {"id": skill_id})
        conn.execute(text("DELETE FROM skill WHERE id = :id"), {"id": skill_id})


def test_backfill_and_later_revisions_upgrade_in_one_run(
    engine: Engine, skill_id: UUID
) -> None:
    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")

    with engine.connect() as conn:
        published = conn.execute(
            text("SELECT published_version_id IS NOT NULL FROM plugin WHERE id = :id"),
            {"id": skill_id},
        ).scalar_one()
    assert published
