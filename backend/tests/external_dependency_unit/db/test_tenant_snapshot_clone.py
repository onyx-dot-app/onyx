"""A tenant cloned from the template snapshot must equal a migrated schema:
same structure, same baseline rows, stamped at head. The parity comparison
must catch a structural or row difference, since it gates the deploy."""

import os
import uuid
from collections.abc import Generator
from typing import cast

import pytest
from sqlalchemy import Table, text

from ee.onyx.db import tenant_snapshot
from onyx.db.engine.shard_registry import get_default_shard_name, get_engine_for_shard
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import PublicBase, TenantSchemaSnapshot
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
    try:
        tenant_snapshot.store_template_snapshots(head)
        assert tenant_snapshot.get_snapshot(shard, head)
        with pytest.raises(RuntimeError):
            tenant_snapshot.store_template_snapshots("not-the-head")
    finally:
        with tenant_snapshot.get_catalog_session() as db_session:
            db_session.execute(
                text(
                    "DELETE FROM public.tenant_schema_snapshot "
                    "WHERE alembic_revision = :head"
                ),
                {"head": head},
            )
            db_session.commit()


def test_render_refuses_names_that_are_not_tenants(dump: str) -> None:
    with pytest.raises(ValueError):
        tenant_snapshot.render_snapshot(dump, "public")
    with pytest.raises(ValueError):
        tenant_snapshot.render_snapshot(dump, TENANT_TEMPLATE_SCHEMA)


def test_store_keeps_the_newest_two(shard: str) -> None:
    revisions = [f"test-{uuid.uuid4().hex[:8]}" for _ in range(3)]
    try:
        for revision in revisions:
            tenant_snapshot.store_snapshot(shard, revision, f"-- {revision}")
        assert tenant_snapshot.get_snapshot(shard, revisions[0]) is None
        assert tenant_snapshot.get_snapshot(shard, revisions[2]) == f"-- {revisions[2]}"
    finally:
        with tenant_snapshot.get_catalog_session() as db_session:
            db_session.execute(
                text(
                    "DELETE FROM public.tenant_schema_snapshot "
                    "WHERE alembic_revision LIKE 'test-%'"
                )
            )
            db_session.commit()
