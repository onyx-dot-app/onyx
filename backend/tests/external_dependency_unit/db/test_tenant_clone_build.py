"""A new tenant is built from the shard's stored snapshot when one exists for
the code's head, stamped at head without alembic running. Without one the
migration chain runs instead."""

import os
from collections.abc import Generator
from typing import cast
from unittest.mock import patch

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
    PublicBase.metadata.create_all(
        SqlEngine.get_engine(), tables=[cast(Table, TenantSchemaSnapshot.__table__)]
    )
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


@pytest.fixture
def stored_snapshot(shard: str) -> Generator[str, None, None]:
    head = tenant_snapshot.get_head_revision()
    assert head is not None
    tenant_snapshot.store_template_snapshots(head)
    yield head
    with tenant_snapshot.get_catalog_session() as db_session:
        db_session.execute(
            text(
                "DELETE FROM public.tenant_schema_snapshot "
                "WHERE shard_name = :shard AND alembic_revision = :head"
            ),
            {"shard": shard, "head": head},
        )
        db_session.commit()


@pytest.fixture
def tenant_id(shard: str) -> Generator[str, None, None]:
    name = tenant_snapshot.scratch_schema_name()
    yield name
    with tenant_snapshot._dropped_afterwards(get_engine_for_shard(shard), name):
        pass


def test_snapshot_builds_the_tenant_without_alembic(
    shard: str, stored_snapshot: str, tenant_id: str
) -> None:
    with patch.object(tenant_snapshot, "run_alembic_migrations") as alembic:
        tenant_snapshot.build_tenant_schema(tenant_id)

    alembic.assert_not_called()
    with get_engine_for_shard(shard).connect() as connection:
        stamped = connection.scalar(
            text(f'SELECT version_num FROM "{tenant_id}".alembic_version')
        )
        tools = connection.scalar(text(f'SELECT count(*) FROM "{tenant_id}".tool'))
    assert stamped == stored_snapshot
    assert tools and tools > 0


@pytest.mark.usefixtures("shard")
def test_no_snapshot_falls_back_to_the_chain(tenant_id: str) -> None:
    with (
        patch.object(tenant_snapshot, "get_snapshot", return_value=None),
        patch.object(tenant_snapshot, "run_alembic_migrations") as alembic,
    ):
        tenant_snapshot.build_tenant_schema(tenant_id)

    alembic.assert_called_once_with(tenant_id)
