"""Tests for migration e4283ce70fbd, which moves the Atlassian ``scoped_token``
flag from Confluence and Jira connector configs onto their credentials."""

import json
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
from onyx.utils.encryption import decrypt_bytes_to_string, encrypt_string_to_bytes
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "b3e7c1d9a4f2"
MOVE_REVISION = "e4283ce70fbd"


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


def _insert_pair(
    engine: Engine, source: str, config: dict, credential_json: dict
) -> tuple[int, int]:
    """A connector, a credential and the pair linking them. Returns their ids."""
    with engine.begin() as conn:
        connector_id = conn.execute(
            text(
                "INSERT INTO connector (name, source, connector_specific_config) "
                "VALUES (:name, :source, CAST(:config AS jsonb)) RETURNING id"
            ),
            {"name": f"{source} test", "source": source, "config": json.dumps(config)},
        ).scalar_one()
        credential_id = conn.execute(
            text(
                "INSERT INTO credential (credential_json, source, admin_public) "
                "VALUES (:json, :source, true) RETURNING id"
            ),
            {
                "json": encrypt_string_to_bytes(json.dumps(credential_json)),
                "source": source,
            },
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO connector_credential_pair (connector_id, credential_id, "
                "total_docs_indexed, name, status, access_type) "
                "VALUES (:connector, :credential, 0, :name, 'ACTIVE', 'PUBLIC')"
            ),
            {
                "connector": connector_id,
                "credential": credential_id,
                "name": f"{source} pair {connector_id}",
            },
        )
    return connector_id, credential_id


def _config(engine: Engine, connector_id: int) -> dict:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT connector_specific_config FROM connector WHERE id = :id"),
            {"id": connector_id},
        ).scalar_one()


def _credential(engine: Engine, credential_id: int) -> dict:
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT credential_json FROM credential WHERE id = :id"),
            {"id": credential_id},
        ).scalar_one()
    return json.loads(decrypt_bytes_to_string(bytes(value)))


@pytest.fixture
def at_previous_revision() -> Generator[Engine, None, None]:
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


def test_upgrade_moves_the_flag_onto_credentials(at_previous_revision: Engine) -> None:
    engine = at_previous_revision
    family_json = {
        "email": "user@example.com",
        "token": "token",
        "oauth": None,
        "credential_family": "atlassian",
    }
    scoped_connector, scoped_credential = _insert_pair(
        engine,
        "CONFLUENCE",
        {
            "wiki_base": "https://acme.atlassian.net",
            "is_cloud": True,
            "scoped_token": True,
        },
        family_json,
    )
    unscoped_connector, unscoped_credential = _insert_pair(
        engine,
        "JIRA",
        {"jira_base_url": "https://acme.atlassian.net", "scoped_token": False},
        {"jira_user_email": "user@example.com", "jira_api_token": "token"},
    )

    upgrade_postgres(database="postgres", config_name="alembic", revision=MOVE_REVISION)

    assert _credential(engine, scoped_credential)["scoped_token"] is True
    assert "scoped_token" not in _credential(engine, unscoped_credential)
    assert "scoped_token" not in _config(engine, scoped_connector)
    assert "scoped_token" not in _config(engine, unscoped_connector)


def test_downgrade_puts_the_flag_back_on_scoped_connectors(
    at_previous_revision: Engine,
) -> None:
    engine = at_previous_revision
    scoped_connector, _ = _insert_pair(
        engine,
        "JIRA",
        {"jira_base_url": "https://acme.atlassian.net", "scoped_token": True},
        {"jira_user_email": "user@example.com", "jira_api_token": "token"},
    )
    unscoped_connector, _ = _insert_pair(
        engine,
        "JIRA",
        {"jira_base_url": "https://acme.atlassian.net"},
        {"jira_user_email": "user@example.com", "jira_api_token": "token"},
    )
    upgrade_postgres(database="postgres", config_name="alembic", revision=MOVE_REVISION)

    downgrade_postgres(
        database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
    )

    assert _config(engine, scoped_connector)["scoped_token"] is True
    assert "scoped_token" not in _config(engine, unscoped_connector)
