"""Migration a4253e609025 gives chat_artifact_version and user_file a unique
preview_file_id that links a file record, and indexes user_file.file_id, not
unique. A retry after an interrupted concurrent index build replaces the
invalid index it left; the downgrade drops the columns and the index."""

from collections.abc import Generator
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import OperationalError

from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "ce6d912380d7"
REVISION = "a4253e609025"


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
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


def _index(conn: Connection, name: str) -> tuple[bool, bool] | None:
    """(valid, unique) of the index `name`, or None when it does not exist."""
    row = conn.execute(
        text(
            "SELECT indisvalid, indisunique FROM pg_index "
            "WHERE indexrelid = to_regclass(:index)"
        ),
        {"index": name},
    ).one_or_none()
    return None if row is None else (row[0], row[1])


def _constraints(conn: Connection, table: str) -> dict[str, bool]:
    """The preview_file_id constraints of `table`, by name, and whether each
    is validated."""
    return dict(
        conn.execute(
            text(
                "SELECT conname, convalidated FROM pg_constraint "
                "WHERE conrelid = to_regclass(:table) AND conname LIKE :name"
            ),
            {"table": table, "name": f"{table}_preview_file_id_%"},
        )
        .tuples()
        .all()
    )


def test_the_upgrade_adds_the_columns_and_index_and_the_downgrade_drops_them(
    engine: Engine,
) -> None:
    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=REVISION)
    with engine.connect() as conn:
        assert _index(conn, "ix_user_file_file_id") == (True, False)
        for table in ("chat_artifact_version", "user_file"):
            assert _index(conn, f"{table}_preview_file_id_key") == (True, True)
            assert _constraints(conn, table) == {
                f"{table}_preview_file_id_fkey": True,
                f"{table}_preview_file_id_key": True,
            }

    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
    )
    with engine.connect() as conn:
        assert _index(conn, "ix_user_file_file_id") is None
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE column_name = 'preview_file_id' AND table_name IN "
                    "('chat_artifact_version', 'user_file')"
                )
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize(
    ("table", "interrupted", "drop"),
    [
        (
            "chat_artifact_version",
            "chat_artifact_version_preview_file_id_key",
            "ALTER TABLE chat_artifact_version "
            "DROP CONSTRAINT chat_artifact_version_preview_file_id_key",
        ),
        (
            "user_file",
            "user_file_preview_file_id_key",
            "ALTER TABLE user_file DROP CONSTRAINT user_file_preview_file_id_key",
        ),
        ("user_file", "ix_user_file_file_id", "DROP INDEX ix_user_file_file_id"),
    ],
)
def test_a_retry_replaces_the_index_that_an_interrupted_build_left(
    monkeypatch: pytest.MonkeyPatch,
    engine: Engine,
    table: str,
    interrupted: str,
    drop: str,
) -> None:
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[4] / "alembic"))
    revision = scripts.get_revision(REVISION)
    assert revision is not None
    with engine.connect() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            revision.module.upgrade()
            # The build of the index stops partway: a writer holds the
            # table, and the lock timeout ends the build.
            conn.execute(text(drop))
            conn.commit()
            monkeypatch.setattr(revision.module, "LOCK_TIMEOUT", "100ms")
            with engine.connect() as writer:
                writer.execute(text(f"LOCK TABLE {table} IN ROW EXCLUSIVE MODE"))
                with pytest.raises(OperationalError, match="lock timeout"):
                    revision.module.upgrade()
                writer.rollback()
            index = _index(conn, interrupted)
            assert index is not None and not index[0]

            revision.module.upgrade()

        assert _index(conn, "ix_user_file_file_id") == (True, False)
        for table in ("chat_artifact_version", "user_file"):
            assert _index(conn, f"{table}_preview_file_id_key") == (True, True)
            assert _constraints(conn, table) == {
                f"{table}_preview_file_id_fkey": True,
                f"{table}_preview_file_id_key": True,
            }
