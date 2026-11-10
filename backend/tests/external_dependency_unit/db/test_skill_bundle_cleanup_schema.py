"""Cleanup must use the tenant schema even when public.skill does not exist."""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

from onyx.cache import factory as cache_factory
from onyx.cache.interface import CacheBackendType
from onyx.configs.constants import FileOrigin
from onyx.db.engine import sql_engine
from onyx.db.models import Base, FileRecord
from onyx.db.skill_version import (
    delete_orphan_skill_bundles,
    delete_unreferenced_skill_bundles,
)
from onyx.file_store import file_store
from onyx.file_store.postgres_file_store import PostgresBackedFileStore
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.db.shard_test_utils import temporary_database
from tests.external_dependency_unit.db.test_skill_version_migration import (
    connection as connection,
)


@pytest.fixture
def isolated_engine(monkeypatch: pytest.MonkeyPatch) -> Generator[Engine, None, None]:
    with contextmanager(temporary_database)("skill_cleanup_schema") as database:
        engine = create_engine(
            sql_engine.build_connection_string(db_api="psycopg2", db=database),
            poolclass=NullPool,
        )
        monkeypatch.setattr(sql_engine, "get_engine_for_tenant", lambda _: engine)
        monkeypatch.setattr(cache_factory, "CACHE_BACKEND", CacheBackendType.POSTGRES)
        monkeypatch.setattr(
            file_store, "_DEFAULT_FILE_STORE", PostgresBackedFileStore()
        )
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.mark.parametrize("orphan_sweep", [False, True])
def test_cleanup_preserves_tenant_references(
    connection: Connection, orphan_sweep: bool
) -> None:
    assert connection.scalar(text("SELECT to_regclass('public.skill')")) is None
    schema = connection.scalar(text("SELECT current_schema()"))
    assert isinstance(schema, str)
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
    v1 = scripts.get_revision("6476b236ec97")
    assert v1 is not None
    with Operations.context(MigrationContext.configure(connection)):
        v1.module.upgrade()
    Base.metadata.create_all(
        connection,
        tables=[
            Base.metadata.tables[name]
            for name in (
                "file_record",
                "file_content",
                "cache_store",
                "key_value_store",
            )
        ],
    )
    connection.commit()
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(schema)
    try:
        store = file_store.get_default_file_store()
        retained, orphan = [
            store.save_file(
                BytesIO(b"retained bundle"),
                name,
                FileOrigin.SKILL_BUNDLE,
                "application/zip",
            )
            for name in ("legacy.zip", "orphan.zip")
        ]
        # Simulate an old writer after V1: only the physical legacy column owns this blob.
        connection.execute(
            text("""
                INSERT INTO skill (id, name, description, bundle_file_id, public_permission)
                VALUES (:id, 'legacy', 'Old writer', :file, 'VIEWER')
            """),
            {"id": uuid4(), "file": retained},
        )
        connection.execute(
            update(FileRecord).values(created_at=func.now() - timedelta(hours=2))
        )
        connection.commit()
        assert connection.scalar(text("SELECT count(*) FROM skill_version")) == 0
        with sql_engine.get_session_with_current_tenant() as session:
            # Only schema translation may find the tenant; no search_path fallback.
            assert session.scalar(text("SELECT current_schema()")) == "public"
            if orphan_sweep:
                assert delete_orphan_skill_bundles() == 1
            else:
                delete_unreferenced_skill_bundles([retained, orphan], session)
            assert set(session.scalars(select(FileRecord.file_id))) == {retained}
        with store.read_file(retained) as stream:
            assert stream.read() == b"retained bundle"
        assert not store.has_file(orphan, FileOrigin.SKILL_BUNDLE, "application/zip")
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
