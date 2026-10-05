from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, inspect, text

_BACKEND = Path(__file__).resolve().parents[3]


def _run_revision(
    connection: Connection,
    *,
    catalog: bool,
    upgrade: bool,
    multi_tenant: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(_BACKEND / ("alembic_tenants" if catalog else "alembic"))
    )
    revision = ScriptDirectory.from_config(config).get_revision(
        "af8d808d89dd" if catalog else "84c15650b1ad"
    )
    assert revision is not None
    module = revision.module
    if not catalog:
        monkeypatch.setattr(module, "MULTI_TENANT", multi_tenant)
    with Operations.context(MigrationContext.configure(connection)):
        if upgrade:
            module.upgrade()
        else:
            module.downgrade()


def test_self_hosted_migration_creates_catalog_and_tenant_tables(
    migration_database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with migration_database.begin() as connection:
        connection.execute(text('CREATE TABLE "user" (id UUID PRIMARY KEY)'))
        _run_revision(
            connection,
            catalog=False,
            upgrade=True,
            multi_tenant=False,
            monkeypatch=monkeypatch,
        )
        assert set(inspect(connection).get_table_names(schema="public")) == {
            "user",
            "mcp_oauth_client",
            "mcp_oauth_grant",
            "mcp_oauth_token",
        }
        connection.execute(
            text(
                "INSERT INTO public.mcp_oauth_client (client_id, client_metadata) VALUES ('migration-test', '{}')"
            )
        )
        assert (
            connection.scalar(text("SELECT client_id FROM public.mcp_oauth_client"))
            == "migration-test"
        )
        _run_revision(
            connection,
            catalog=False,
            upgrade=False,
            multi_tenant=False,
            monkeypatch=monkeypatch,
        )
        assert inspect(connection).get_table_names(schema="public") == ["user"]


def test_cloud_migrations_keep_one_registry_outside_tenant_schema(
    migration_database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with migration_database.begin() as connection:
        _run_revision(
            connection,
            catalog=True,
            upgrade=True,
            multi_tenant=True,
            monkeypatch=monkeypatch,
        )
        connection.execute(text("CREATE SCHEMA tenant_oauth_test"))
        connection.execute(
            text('CREATE TABLE tenant_oauth_test."user" (id UUID PRIMARY KEY)')
        )
        connection.execute(text("SET LOCAL search_path TO tenant_oauth_test, public"))
        _run_revision(
            connection,
            catalog=False,
            upgrade=True,
            multi_tenant=True,
            monkeypatch=monkeypatch,
        )
        assert inspect(connection).get_table_names(schema="public") == [
            "mcp_oauth_client"
        ]
        assert set(inspect(connection).get_table_names(schema="tenant_oauth_test")) == {
            "user",
            "mcp_oauth_grant",
            "mcp_oauth_token",
        }
        connection.execute(
            text(
                "INSERT INTO public.mcp_oauth_client (client_id, client_metadata) VALUES ('migration-test', '{}')"
            )
        )
        assert (
            connection.scalar(text("SELECT client_id FROM public.mcp_oauth_client"))
            == "migration-test"
        )
        _run_revision(
            connection,
            catalog=False,
            upgrade=False,
            multi_tenant=True,
            monkeypatch=monkeypatch,
        )
        assert inspect(connection).get_table_names(schema="public") == [
            "mcp_oauth_client"
        ]
        assert inspect(connection).get_table_names(schema="tenant_oauth_test") == [
            "user"
        ]
        _run_revision(
            connection,
            catalog=True,
            upgrade=False,
            multi_tenant=True,
            monkeypatch=monkeypatch,
        )
        assert inspect(connection).get_table_names(schema="public") == []
