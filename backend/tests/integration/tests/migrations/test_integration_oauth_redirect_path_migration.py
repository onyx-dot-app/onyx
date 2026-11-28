"""Migration b37ec5bd7efa keeps the redirect path of each existing OAuth
client of an API integration, so no admin registers a new one with the
provider. A new client uses /integrations/oauth/callback."""

from collections.abc import Generator

import pytest
from sqlalchemy import Connection, Engine, create_engine, text

from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "00a73eb4dccf"
REVISION = "b37ec5bd7efa"


def _migrate(direction: str, revision: str) -> None:
    if direction == "upgrade":
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=revision)
    else:
        downgrade_postgres(
            database=POSTGRES_DB, config_name="alembic", revision=revision
        )


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    _migrate("upgrade", "head")
    _migrate("downgrade", PREVIOUS_REVISION)
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
        _migrate("upgrade", "head")
        engine.dispose()


def _insert_app_integration(conn: Connection, name: str, provider_mode: str) -> int:
    app_id = conn.execute(
        text(
            "INSERT INTO external_app (name, organization_credentials) "
            "VALUES (:name, '\\x'::bytea) RETURNING id"
        ),
        {"name": name},
    ).scalar_one()
    integration_id = conn.execute(
        text(
            "INSERT INTO integration (kind, name, auth_mode, auth_method, "
            "external_app_id) VALUES ('api', :name, 'individual', 'oauth2', "
            ":app_id) RETURNING id"
        ),
        {"name": name, "app_id": app_id},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO integration_oauth_client (integration_id, provider_mode) "
            "VALUES (:id, :mode)"
        ),
        {"id": integration_id, "mode": provider_mode},
    )
    return integration_id


def _legacy_redirect_paths(conn: Connection, ids: list[int]) -> dict[int, str | None]:
    rows = conn.execute(
        text(
            "SELECT integration_id, legacy_redirect_path "
            "FROM integration_oauth_client WHERE integration_id = ANY(:ids)"
        ),
        {"ids": ids},
    )
    return {row.integration_id: row.legacy_redirect_path for row in rows}


def test_existing_clients_keep_their_redirect_path(engine: Engine) -> None:
    with engine.begin() as conn:
        preset = _insert_app_integration(conn, "redirect-path-preset", "preset")
        manual = _insert_app_integration(conn, "redirect-path-manual", "manual")
        discovery = _insert_app_integration(
            conn, "redirect-path-discovery", "discovery"
        )
    ids = [preset, manual, discovery]
    try:
        _migrate("upgrade", REVISION)
        with engine.connect() as conn:
            assert _legacy_redirect_paths(conn, ids) == {
                preset: "/craft/v1/apps/oauth/callback",
                manual: "/oauth-config/callback",
                discovery: None,
            }
        _migrate("downgrade", PREVIOUS_REVISION)
        with engine.connect() as conn:
            assert conn.execute(
                text(
                    "SELECT count(*) FROM integration_oauth_client "
                    "WHERE integration_id = ANY(:ids)"
                ),
                {"ids": ids},
            ).scalar_one() == len(ids)
    finally:
        with engine.begin() as conn:
            app_ids = list(
                conn.execute(
                    text(
                        "SELECT external_app_id FROM integration WHERE id = ANY(:ids)"
                    ),
                    {"ids": ids},
                ).scalars()
            )
            conn.execute(
                text("DELETE FROM integration WHERE id = ANY(:ids)"), {"ids": ids}
            )
            conn.execute(
                text("DELETE FROM external_app WHERE id = ANY(:ids)"),
                {"ids": app_ids},
            )
