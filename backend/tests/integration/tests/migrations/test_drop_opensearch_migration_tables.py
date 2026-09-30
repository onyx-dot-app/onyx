"""Tests for migration 3067343245d1, which drops the tables that tracked the
Vespa to OpenSearch migration."""

import threading
import time
from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine, text

from onyx.configs.app_configs import (
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "b7c2e4f1a9d3"
DROP_REVISION = "3067343245d1"
DOCUMENT_RECORD_TABLE = "opensearch_document_migration_record"
TENANT_RECORD_TABLE = "opensearch_tenant_migration_record"


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


def _migration_tables(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name IN (:a, :b)"
            ),
            {"a": DOCUMENT_RECORD_TABLE, "b": TENANT_RECORD_TABLE},
        )
        return {row[0] for row in rows}


def _current_revision(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()


def _insert_document(engine: Engine, doc_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO document (id, semantic_id, boost, hidden, "
                "from_ingestion_api, kg_stage) "
                "VALUES (:id, :id, 0, false, false, 'NOT_STARTED')"
            ),
            {"id": doc_id},
        )


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
        engine.dispose()
        upgrade_postgres(database="postgres", config_name="alembic", revision="head")


@pytest.fixture
def at_previous_revision(engine: Engine) -> Engine:
    """Puts the database at the revision just before the drop, with empty
    migration tables."""
    if _current_revision(engine) == DROP_REVISION:
        downgrade_postgres(
            database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
        )
    assert _current_revision(engine) == PREVIOUS_REVISION
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {DOCUMENT_RECORD_TABLE}"))
        conn.execute(text(f"DELETE FROM {TENANT_RECORD_TABLE}"))
    return engine


def test_upgrade_drops_populated_tables_and_keeps_documents(
    at_previous_revision: Engine,
) -> None:
    engine = at_previous_revision
    _insert_document(engine, "drop-migration-doc")
    with engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {DOCUMENT_RECORD_TABLE} (document_id) "
                "VALUES ('drop-migration-doc')"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {TENANT_RECORD_TABLE} "
                "(id, enable_opensearch_retrieval, migration_completed_at) "
                "VALUES (1, true, now())"
            )
        )

    upgrade_postgres(database="postgres", config_name="alembic", revision=DROP_REVISION)

    assert _migration_tables(engine) == set()
    with engine.connect() as conn:
        remaining = conn.execute(
            text("SELECT count(*) FROM document WHERE id = 'drop-migration-doc'")
        ).scalar_one()
    assert remaining == 1


def test_downgrade_recreates_the_tables(at_previous_revision: Engine) -> None:
    engine = at_previous_revision
    upgrade_postgres(database="postgres", config_name="alembic", revision=DROP_REVISION)

    downgrade_postgres(
        database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
    )

    assert _migration_tables(engine) == {DOCUMENT_RECORD_TABLE, TENANT_RECORD_TABLE}
    _insert_document(engine, "recreated-table-doc")
    with engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {DOCUMENT_RECORD_TABLE} (document_id) "
                "VALUES ('recreated-table-doc')"
            )
        )
        conn.execute(text(f"INSERT INTO {TENANT_RECORD_TABLE} (id) VALUES (1)"))
        status = conn.execute(
            text(f"SELECT status FROM {DOCUMENT_RECORD_TABLE}")
        ).scalar_one()
    assert status == "pending"
    # The singleton index allows only one tenant record.
    with pytest.raises(Exception, match="idx_opensearch_tenant_migration_singleton"):
        with engine.begin() as conn:
            conn.execute(text(f"INSERT INTO {TENANT_RECORD_TABLE} (id) VALUES (2)"))


def test_upgrade_waits_out_a_long_lock_on_document(
    at_previous_revision: Engine,
) -> None:
    """A transaction that holds a lock on `document` (for example an indexing
    batch) must delay the drop, not fail the migration."""
    engine = at_previous_revision
    lock_held = threading.Event()
    hold_lock_s = 7.0

    def _hold_lock() -> None:
        with engine.begin() as conn:
            conn.execute(text("LOCK TABLE document IN ROW SHARE MODE"))
            lock_held.set()
            time.sleep(hold_lock_s)

    holder = threading.Thread(target=_hold_lock)
    holder.start()
    assert lock_held.wait(timeout=10)
    start = time.monotonic()

    upgrade_postgres(database="postgres", config_name="alembic", revision=DROP_REVISION)

    elapsed = time.monotonic() - start
    holder.join()
    assert _current_revision(engine) == DROP_REVISION
    assert _migration_tables(engine) == set()
    # The first attempt timed out behind the lock, so the drop was retried.
    assert elapsed >= 5.0
