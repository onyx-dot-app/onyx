"""A migration connection must stay on its tenant schema after a mid-run commit,
even when the next transaction runs on a server connection whose search_path
points elsewhere (PgBouncer transaction pooling hands out any server connection).

The backend switch is emulated with a `begin` listener registered first: from
the second transaction on, it sets search_path to a decoy schema before any
migration statement runs, as a reused server connection would carry."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.db.engine.migration_search_path import pin_search_path_per_transaction


@pytest.fixture
def schemas(isolated_engine: Engine) -> Generator[tuple[str, str], None, None]:
    tenant = f"pin_tenant_{uuid4().hex[:12]}"
    decoy = f"pin_decoy_{uuid4().hex[:12]}"
    with isolated_engine.begin() as conn:
        conn.execute(CreateSchema(tenant))
        conn.execute(CreateSchema(decoy))
    try:
        yield tenant, decoy
    finally:
        with isolated_engine.begin() as conn:
            conn.execute(DropSchema(tenant, cascade=True, if_exists=True))
            conn.execute(DropSchema(decoy, cascade=True, if_exists=True))


def _emulate_backend_switch(connection: Connection, decoy: str) -> None:
    """From the second transaction on, start it with the decoy search_path."""
    began = 0

    def _on_begin(conn: Connection) -> None:
        nonlocal began
        began += 1
        if began > 1:
            conn.exec_driver_sql(f'SET search_path TO "{decoy}"')

    event.listen(connection, "begin", _on_begin)


def _run_migration_that_commits_mid_run(connection: Connection) -> None:
    connection.execute(text("CREATE TABLE before_commit (id int)"))
    connection.commit()
    connection.execute(text("CREATE TABLE after_commit (id int)"))
    connection.commit()


def _tables_in(connection: Connection, schema: str) -> set[str]:
    return set(
        connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = :schema"),
            {"schema": schema},
        ).scalars()
    )


def test_pinned_connection_keeps_ddl_in_tenant_schema(
    isolated_engine: Engine, schemas: tuple[str, str]
) -> None:
    tenant, decoy = schemas
    with isolated_engine.connect() as connection:
        _emulate_backend_switch(connection, decoy)
        pin_search_path_per_transaction(connection, tenant)
        _run_migration_that_commits_mid_run(connection)

    with isolated_engine.connect() as check:
        assert _tables_in(check, tenant) == {"before_commit", "after_commit"}
        assert _tables_in(check, decoy) == set()


def test_one_time_set_loses_the_tenant_schema_after_a_backend_switch(
    isolated_engine: Engine, schemas: tuple[str, str]
) -> None:
    """Control: a one-time session SET, as env.py used to do, sends the DDL
    after the commit to the decoy schema under the same emulation."""
    tenant, decoy = schemas
    with isolated_engine.connect() as connection:
        _emulate_backend_switch(connection, decoy)
        connection.exec_driver_sql(f'SET search_path TO "{tenant}"')
        _run_migration_that_commits_mid_run(connection)

    with isolated_engine.connect() as check:
        assert _tables_in(check, tenant) == {"before_commit"}
        assert _tables_in(check, decoy) == {"after_commit"}


def test_pin_applies_inside_an_open_transaction(
    isolated_engine: Engine, schemas: tuple[str, str]
) -> None:
    tenant, _ = schemas
    with isolated_engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        pin_search_path_per_transaction(connection, tenant)
        assert connection.execute(text("SELECT current_schema()")).scalar_one() == (
            tenant
        )
        connection.rollback()


def test_pin_does_not_outlive_the_transaction(
    isolated_engine: Engine, schemas: tuple[str, str]
) -> None:
    """The pin must not leave a session search_path for the next client of a
    pooled server connection."""
    tenant, _ = schemas
    with isolated_engine.connect() as connection:
        default_schema = connection.execute(
            text("SELECT current_schema()")
        ).scalar_one()
        connection.rollback()
        pin_search_path_per_transaction(connection, tenant)
        connection.execute(text("SELECT 1"))
        connection.commit()

        # Raw DBAPI read: SQLAlchemy's begin event (and so the pin) does not fire.
        dbapi_connection = connection.connection.dbapi_connection
        assert dbapi_connection is not None
        cursor = dbapi_connection.cursor()
        cursor.execute("SELECT current_schema()")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == default_schema
        dbapi_connection.rollback()


def test_pin_quotes_the_schema_name(isolated_engine: Engine) -> None:
    tenant = f'pin "quoted"; SELECT 1; -- {uuid4().hex[:8]}'
    with isolated_engine.begin() as conn:
        conn.execute(CreateSchema(tenant))
    try:
        with isolated_engine.connect() as connection:
            pin_search_path_per_transaction(connection, tenant)
            current = connection.execute(text("SELECT current_schema()")).scalar_one()
            assert current == tenant
            connection.rollback()
    finally:
        with isolated_engine.begin() as conn:
            conn.execute(DropSchema(tenant, cascade=True, if_exists=True))
