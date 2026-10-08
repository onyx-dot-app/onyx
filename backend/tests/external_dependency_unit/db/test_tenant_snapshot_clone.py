"""A tenant cloned from the template snapshot must equal a migrated schema:
same structure, same baseline rows, stamped at head. The parity comparison
must catch a structural or row difference, since it gates the deploy."""

import os
import uuid
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import cast
from unittest.mock import patch

import pytest
from sqlalchemy import Table, delete, func, select, text

from ee.onyx.db import tenant_snapshot
from ee.onyx.server.tenants import schema_management
from onyx.db.engine import tenant_utils
from onyx.db.engine.shard_registry import (
    get_default_shard_name,
    get_engine_for_shard,
    get_shard_specs,
)
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.tenant_utils import get_template_shards
from onyx.db.models import PublicBase, TenantSchemaSnapshot, Tool
from shared_configs.configs import TENANT_TEMPLATE_SCHEMA


@pytest.fixture(scope="module")
def shard() -> Generator[str, None, None]:
    SqlEngine.init_engine(pool_size=5, max_overflow=2)
    shard_name = get_default_shard_name()
    # The snapshot table comes from the catalog chain, which the single-tenant
    # test database never runs.
    PublicBase.metadata.create_all(
        SqlEngine.get_engine(), tables=[cast(Table, TenantSchemaSnapshot.__table__)]
    )
    # The chain seeds cloud-only rows under this flag, which is what the
    # rollout job's template gets.
    os.environ["MULTI_TENANT"] = "true"
    tenant_snapshot.ensure_template_schema(shard_name)
    try:
        tenant_snapshot._migrate_empty_schema(shard_name, TENANT_TEMPLATE_SCHEMA)
        yield shard_name
    finally:
        os.environ.pop("MULTI_TENANT", None)
        with tenant_snapshot._dropped_afterwards(
            get_engine_for_shard(shard_name), TENANT_TEMPLATE_SCHEMA
        ):
            pass
        SqlEngine.reset_engine()


@pytest.fixture(scope="module")
def dump(shard: str) -> str:
    return tenant_snapshot.dump_schema(shard, TENANT_TEMPLATE_SCHEMA)


@pytest.fixture
def clone(shard: str, dump: str) -> Generator[str, None, None]:
    tenant_id = tenant_snapshot.scratch_schema_name()
    tenant_snapshot.apply_snapshot(get_engine_for_shard(shard), dump, tenant_id)
    yield tenant_id
    with tenant_snapshot._dropped_afterwards(get_engine_for_shard(shard), tenant_id):
        pass


def test_clone_matches_the_template(shard: str, clone: str) -> None:
    assert tenant_snapshot.compare_schemas(shard, clone, TENANT_TEMPLATE_SCHEMA) == []

    with get_engine_for_shard(shard).connect() as connection:
        stamped = connection.scalar(
            text(f'SELECT version_num FROM "{clone}".alembic_version')
        )
        tool_count = connection.scalar(text(f'SELECT count(*) FROM "{clone}".tool'))
    assert stamped == tenant_snapshot.get_head_revision()
    assert tool_count and tool_count > 0


def test_parity_catches_a_missing_column(shard: str, clone: str) -> None:
    with get_engine_for_shard(shard).begin() as connection:
        connection.execute(
            text(f'ALTER TABLE "{clone}".persona DROP COLUMN description')
        )

    differences = tenant_snapshot.compare_schemas(shard, clone, TENANT_TEMPLATE_SCHEMA)
    assert differences and differences[0] == "structure differs:"


def test_parity_catches_an_extra_index(shard: str, clone: str) -> None:
    with get_engine_for_shard(shard).begin() as connection:
        connection.execute(
            text(f'CREATE INDEX parity_extra ON "{clone}".persona (name)')
        )

    differences = tenant_snapshot.compare_schemas(shard, clone, TENANT_TEMPLATE_SCHEMA)
    assert differences and differences[0] == "structure differs:"
    assert any("parity_extra" in difference for difference in differences)


def test_parity_catches_a_dropped_constraint(shard: str, clone: str) -> None:
    with get_engine_for_shard(shard).begin() as connection:
        constraint = connection.execute(
            text(
                "SELECT con.conname, c.relname FROM pg_constraint con "
                "JOIN pg_class c ON c.oid = con.conrelid "
                "WHERE con.connamespace = CAST(:schema AS regnamespace) "
                "AND con.contype = 'f' "
                "ORDER BY con.conname LIMIT 1"
            ),
            {"schema": f'"{clone}"'},
        ).one()
        connection.execute(
            text(
                f'ALTER TABLE "{clone}"."{constraint.relname}" '
                f'DROP CONSTRAINT "{constraint.conname}"'
            )
        )

    differences = tenant_snapshot.compare_schemas(shard, clone, TENANT_TEMPLATE_SCHEMA)
    assert differences and differences[0] == "structure differs:"
    assert any(constraint.conname in difference for difference in differences)


def test_parity_catches_a_dropped_trigger(shard: str, clone: str) -> None:
    with get_engine_for_shard(shard).begin() as connection:
        trigger = connection.execute(
            text(
                "SELECT t.tgname, c.relname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE c.relnamespace = CAST(:schema AS regnamespace) "
                "AND NOT t.tgisinternal "
                "ORDER BY t.tgname LIMIT 1"
            ),
            {"schema": f'"{clone}"'},
        ).one()
        connection.execute(
            text(
                f'ALTER TABLE "{clone}"."{trigger.relname}" '
                f'DISABLE TRIGGER "{trigger.tgname}"'
            )
        )

    differences = tenant_snapshot.compare_schemas(shard, clone, TENANT_TEMPLATE_SCHEMA)
    assert differences and differences[0] == "structure differs:"
    assert any(trigger.tgname in difference for difference in differences)

    with get_engine_for_shard(shard).begin() as connection:
        connection.execute(
            text(f'DROP TRIGGER "{trigger.tgname}" ON "{clone}"."{trigger.relname}"')
        )

    differences = tenant_snapshot.compare_schemas(shard, clone, TENANT_TEMPLATE_SCHEMA)
    assert differences and differences[0] == "structure differs:"
    assert any(trigger.tgname in difference for difference in differences)


def test_parity_ignores_the_migration_date_seed(shard: str, clone: str) -> None:
    # The knowledge graph config is seeded with the migration's run date.
    with get_engine_for_shard(shard).begin() as connection:
        connection.execute(
            text(
                f'UPDATE "{clone}".key_value_store '
                "SET value = jsonb_set(value, '{KG_COVERAGE_START}', '\"2000-01-01\"') "
                "WHERE key = 'kg_config'"
            )
        )

    assert tenant_snapshot.compare_schemas(shard, clone, TENANT_TEMPLATE_SCHEMA) == []

    # Only the dated field is dropped: any other setting still has to match.
    with get_engine_for_shard(shard).begin() as connection:
        connection.execute(
            text(
                f'UPDATE "{clone}".key_value_store '
                "SET value = jsonb_set(value, '{KG_ENABLED}', 'true') "
                "WHERE key = 'kg_config'"
            )
        )
    differences = tenant_snapshot.compare_schemas(shard, clone, TENANT_TEMPLATE_SCHEMA)
    assert any(difference.startswith("key_value_store: ") for difference in differences)


def test_parity_catches_a_missing_row(shard: str, clone: str) -> None:
    with get_engine_for_shard(shard).begin() as connection:
        connection.execute(
            text(
                f'DELETE FROM "{clone}".tool WHERE id = '
                f'(SELECT min(id) FROM "{clone}".tool)'
            )
        )

    differences = tenant_snapshot.compare_schemas(shard, clone, TENANT_TEMPLATE_SCHEMA)
    assert any(difference.startswith("tool: ") for difference in differences)


def test_deploy_gate_passes_for_the_template_snapshot(shard: str, dump: str) -> None:
    # Migrates a scratch schema through the full chain, so this is the slow one.
    assert tenant_snapshot.check_snapshot_parity(shard, dump) == []


def test_rollout_stores_the_template_only_at_head(shard: str) -> None:
    head = tenant_snapshot.get_head_revision()
    assert head is not None
    with _snapshot_rows_restored(head):
        tenant_snapshot.store_template_snapshots(head)
        assert tenant_snapshot.get_snapshot(shard, head)
        with pytest.raises(RuntimeError):
            tenant_snapshot.store_template_snapshots("not-the-head")


def test_template_is_rotated_by_shard(shard: str) -> None:
    # Enumeration only looks past the default schema in multi-tenant mode.
    with patch.object(tenant_utils, "MULTI_TENANT", True):
        assert get_template_shards() == [shard]
    # The session binds model tables to the template, which is what rotation reads.
    with tenant_snapshot.template_session(shard) as db_session:
        seeded_tools = db_session.scalar(select(func.count()).select_from(Tool))
    assert seeded_tools and seeded_tools > 0


@contextmanager
def _snapshot_rows_restored(head: str) -> Iterator[None]:
    """Whatever the catalog held for this head, on every shard, is put back."""
    before = {
        shard_name: tenant_snapshot.get_snapshot(shard_name, head)
        for shard_name in get_shard_specs()
    }
    try:
        yield
    finally:
        for shard_name, dump in before.items():
            if dump is not None:
                tenant_snapshot.store_snapshot(shard_name, head, dump)
            else:
                _delete_snapshot_rows(shard_name, head)


@pytest.fixture
def stored_snapshot(shard: str, dump: str) -> Generator[str, None, None]:
    head = tenant_snapshot.get_head_revision()
    assert head is not None
    with _snapshot_rows_restored(head):
        tenant_snapshot.store_snapshot(shard, head, dump)
        yield head


@pytest.fixture
def new_tenant(shard: str) -> Generator[str, None, None]:
    name = tenant_snapshot.scratch_schema_name()
    yield name
    with tenant_snapshot._dropped_afterwards(get_engine_for_shard(shard), name):
        pass


def test_snapshot_builds_the_tenant_without_alembic(
    shard: str, stored_snapshot: str, new_tenant: str
) -> None:
    with patch.object(schema_management, "run_alembic_migrations") as alembic:
        schema_management.build_tenant_schema(new_tenant)

    alembic.assert_not_called()
    with get_engine_for_shard(shard).connect() as connection:
        stamped = connection.scalar(
            text(f'SELECT version_num FROM "{new_tenant}".alembic_version')
        )
        tools = connection.scalar(text(f'SELECT count(*) FROM "{new_tenant}".tool'))
    assert stamped == stored_snapshot
    assert tools and tools > 0


@pytest.mark.usefixtures("stored_snapshot")
def test_a_retried_build_resumes_through_the_chain(clone: str) -> None:
    # The clone fixture already built the schema, as a failed first attempt would.
    with patch.object(schema_management, "run_alembic_migrations") as alembic:
        schema_management.build_tenant_schema(clone)

    alembic.assert_called_once_with(clone)


def test_no_snapshot_falls_back_to_the_chain(shard: str, new_tenant: str) -> None:
    with (
        patch.object(
            schema_management, "get_shard_for_tenant", return_value="other-shard"
        ),
        patch.object(
            schema_management,
            "get_engine_for_shard",
            return_value=get_engine_for_shard(shard),
        ),
        patch.object(schema_management, "get_snapshot", return_value=None) as lookup,
        patch.object(schema_management, "run_alembic_migrations") as alembic,
    ):
        schema_management.build_tenant_schema(new_tenant)

    lookup.assert_called_once_with("other-shard", tenant_snapshot.get_head_revision())
    alembic.assert_called_once_with(new_tenant)


def test_render_refuses_names_that_are_not_tenants(dump: str) -> None:
    with pytest.raises(ValueError):
        tenant_snapshot.render_snapshot(dump, "public")
    with pytest.raises(ValueError):
        tenant_snapshot.render_snapshot(dump, TENANT_TEMPLATE_SCHEMA)


@pytest.mark.usefixtures("shard")
def test_store_keeps_the_newest_two() -> None:
    # Retention is per shard, so a made-up shard cannot evict real rows.
    fake_shard = f"test-shard-{uuid.uuid4().hex[:8]}"
    revisions = [f"test-{uuid.uuid4().hex[:8]}" for _ in range(3)]
    try:
        for revision in revisions:
            tenant_snapshot.store_snapshot(fake_shard, revision, f"-- {revision}")
        assert tenant_snapshot.get_snapshot(fake_shard, revisions[0]) is None
        assert (
            tenant_snapshot.get_snapshot(fake_shard, revisions[2])
            == f"-- {revisions[2]}"
        )
    finally:
        _delete_snapshot_rows(fake_shard)


def _delete_snapshot_rows(shard: str, head: str | None = None) -> None:
    statement = delete(TenantSchemaSnapshot).where(
        TenantSchemaSnapshot.shard_name == shard
    )
    if head is not None:
        statement = statement.where(TenantSchemaSnapshot.alembic_revision == head)
    with tenant_snapshot.get_catalog_session() as db_session:
        db_session.execute(statement)
        db_session.commit()
