from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from mcp.shared.auth import OAuthClientInformationFull
from sqlalchemy import Connection, Engine, Table, inspect, text
from sqlalchemy.orm import Session

from onyx.db import oauth_provider
from onyx.db.models import OAuthProviderClient
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA

_BACKEND = Path(__file__).resolve().parents[3]


def _run_revision(
    connection: Connection,
    *,
    catalog: bool,
    upgrade: bool,
    multi_tenant: bool,
    monkeypatch: pytest.MonkeyPatch,
    revision_id: str | None = None,
    schema: str = "public",
) -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(_BACKEND / ("alembic_tenants" if catalog else "alembic"))
    )
    revision = ScriptDirectory.from_config(config).get_revision(
        revision_id or ("af8d808d89dd" if catalog else "84c15650b1ad")
    )
    assert revision is not None
    module = revision.module
    if not catalog:
        monkeypatch.setattr(module, "MULTI_TENANT", multi_tenant)
        monkeypatch.setattr(module, "POSTGRES_DEFAULT_SCHEMA", schema)
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
            "oauth_provider_client",
            "oauth_provider_grant",
            "oauth_provider_token",
        }
        connection.execute(
            text(
                "INSERT INTO public.oauth_provider_client (client_id, client_metadata) VALUES ('migration-test', '{}')"
            )
        )
        assert (
            connection.scalar(
                text("SELECT client_id FROM public.oauth_provider_client")
            )
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
            "oauth_provider_client"
        ]
        assert set(inspect(connection).get_table_names(schema="tenant_oauth_test")) == {
            "user",
            "oauth_provider_grant",
            "oauth_provider_token",
        }
        connection.execute(
            text(
                "INSERT INTO public.oauth_provider_client (client_id, client_metadata) VALUES ('migration-test', '{}')"
            )
        )
        assert (
            connection.scalar(
                text("SELECT client_id FROM public.oauth_provider_client")
            )
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
            "oauth_provider_client"
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


@pytest.mark.parametrize("schema", ["onyx_app", 'onyx-"app'])
def test_custom_schema_upgrade_preserves_client_registration(
    migration_database: Engine, monkeypatch: pytest.MonkeyPatch, schema: str
) -> None:
    with migration_database.begin() as connection:
        quoted_schema = connection.dialect.identifier_preparer.quote_schema(schema)
        connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
        connection.execute(text('CREATE TABLE "user" (id UUID PRIMARY KEY)'))
        _run_revision(
            connection,
            catalog=False,
            upgrade=True,
            multi_tenant=False,
            monkeypatch=monkeypatch,
        )
        connection.execute(
            text(
                "INSERT INTO public.oauth_provider_client (client_id, client_metadata) "
                "VALUES ('existing-client', '{\"client_name\": \"Existing client\"}')"
            )
        )
        original = connection.execute(
            text("SELECT * FROM public.oauth_provider_client")
        ).one()
        for upgrade in (True, False, True):
            _run_revision(
                connection,
                catalog=False,
                upgrade=upgrade,
                multi_tenant=False,
                monkeypatch=monkeypatch,
                revision_id="e38f8193dd32",
                schema=schema,
            )
            destination = quoted_schema if upgrade else "public"
            assert (
                connection.execute(
                    text(f"SELECT * FROM {destination}.oauth_provider_client")
                ).one()
                == original
            )
            assert (
                inspect(connection).get_indexes(
                    "oauth_provider_client", schema=schema if upgrade else "public"
                )[0]["name"]
                == "ix_oauth_provider_client_last_used_at"
            )
        assert not inspect(connection).has_table(
            "oauth_provider_client", schema="public"
        )


def test_fresh_custom_schema_does_not_create_public_registry(
    migration_database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with migration_database.connect() as connection:
        connection.execute(text("CREATE SCHEMA onyx_app"))
        connection.execute(text("CREATE ROLE oauth_schema_migration"))
        connection.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
        connection.execute(
            text("GRANT USAGE, CREATE ON SCHEMA onyx_app TO oauth_schema_migration")
        )
        connection.execute(text("SET LOCAL ROLE oauth_schema_migration"))
        connection.execute(text("SET LOCAL search_path TO onyx_app"))
        assert (
            connection.scalar(
                text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
            )
            is False
        )
        connection.execute(text('CREATE TABLE "user" (id UUID PRIMARY KEY)'))
        for revision_id in ("84c15650b1ad", "e38f8193dd32"):
            _run_revision(
                connection,
                catalog=False,
                upgrade=True,
                multi_tenant=False,
                monkeypatch=monkeypatch,
                revision_id=revision_id,
                schema="onyx_app",
            )
        assert inspect(connection).get_table_names(schema="public") == []
        assert inspect(connection).has_table("oauth_provider_client", schema="onyx_app")
        connection.execute(text("RESET ROLE"))
        for revision_id in ("e38f8193dd32", "84c15650b1ad"):
            _run_revision(
                connection,
                catalog=False,
                upgrade=False,
                multi_tenant=False,
                monkeypatch=monkeypatch,
                revision_id=revision_id,
                schema="onyx_app",
            )
        assert inspect(connection).get_table_names(schema="onyx_app") == ["user"]
        assert inspect(connection).get_table_names(schema="public") == []


@pytest.mark.parametrize(
    "multi_tenant,schema", [(True, "tenant_oauth_test"), (False, "public")]
)
def test_registry_move_leaves_cloud_and_default_schema_unchanged(
    migration_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
    multi_tenant: bool,
    schema: str,
) -> None:
    with migration_database.begin() as connection:
        _run_revision(
            connection,
            catalog=True,
            upgrade=True,
            multi_tenant=True,
            monkeypatch=monkeypatch,
        )
        for upgrade in (True, False):
            _run_revision(
                connection,
                catalog=False,
                upgrade=upgrade,
                multi_tenant=multi_tenant,
                monkeypatch=monkeypatch,
                revision_id="e38f8193dd32",
                schema=schema,
            )
            assert inspect(connection).has_table(
                "oauth_provider_client", schema="public"
            )


def test_client_storage_uses_configured_schema(
    migration_database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = "public" if MULTI_TENANT else POSTGRES_DEFAULT_SCHEMA
    assert OAuthProviderClient.__table__.schema == schema
    with migration_database.begin() as connection:
        quoted_schema = connection.dialect.identifier_preparer.quote_schema(schema)
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quoted_schema}"))
        table = OAuthProviderClient.__table__
        assert isinstance(table, Table)
        table.create(connection)

    @contextmanager
    def catalog_session() -> Generator[Session, None, None]:
        with Session(migration_database) as session:
            session.execute(text("SET LOCAL search_path TO pg_catalog"))
            yield session

    monkeypatch.setattr(oauth_provider, "get_catalog_session", catalog_session)
    client = OAuthClientInformationFull(
        client_id="configured-schema-client",
        client_name="Schema test client",
        redirect_uris=["http://localhost:3000/callback"],
        token_endpoint_auth_method="none",
    )
    oauth_provider.register_oauth_provider_client(client)
    assert client.client_id is not None
    assert oauth_provider.get_oauth_provider_client(client.client_id) == client
    with migration_database.connect() as connection:
        assert (
            connection.scalar(
                text(f"SELECT client_id FROM {quoted_schema}.oauth_provider_client")
            )
            == client.client_id
        )
        if schema != "public":
            assert not inspect(connection).has_table(
                "oauth_provider_client", schema="public"
            )
