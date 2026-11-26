"""Migration 933a21d46472 turns a URL-pattern app with one `https://host/path/*`
pattern into a REST app in place. The integration keeps its id, so its agent
links, policies and saved sign-in stay, and the credential still goes on its
requests. An app whose patterns no base URL covers stays as it was."""

import json
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session

from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.db.integration import get_integration_by_id
from onyx.db.models import User
from onyx.integrations.call_credentials import resolve_call_credentials
from onyx.integrations.kinds.api import ApiKindHandler
from onyx.integrations.models import ApiShape, CallCredentials
from onyx.utils.encryption import encrypt_string_to_bytes
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "d04326aae2f9"
REVISION = "933a21d46472"


@pytest.fixture
def user_ids() -> list[UUID]:
    return []


@pytest.fixture
def engine(user_ids: list[UUID]) -> Generator[Engine, None, None]:
    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
    )
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
        try:
            upgrade_postgres(
                database=POSTGRES_DB, config_name="alembic", revision="head"
            )
            with engine.begin() as conn:
                kind_rows = conn.execute(
                    text(
                        "DELETE FROM integration WHERE owner_user_id = ANY(:ids) "
                        "RETURNING api_app_id, external_app_id"
                    ),
                    {"ids": user_ids},
                ).all()
                conn.execute(
                    text("DELETE FROM api_app WHERE id = ANY(:ids)"),
                    {"ids": [row.api_app_id for row in kind_rows]},
                )
                conn.execute(
                    text("DELETE FROM external_app WHERE id = ANY(:ids)"),
                    {"ids": [row.external_app_id for row in kind_rows]},
                )
                # The tool rows go with their user.
                for statement in (
                    "DELETE FROM persona WHERE user_id = ANY(:ids)",
                    'DELETE FROM "user" WHERE id = ANY(:ids)',
                ):
                    conn.execute(text(statement), {"ids": user_ids})
        finally:
            engine.dispose()


def _insert_url_pattern_app(
    conn: Connection, user_id: UUID, name: str, patterns: list[str]
) -> int:
    app_id = conn.execute(
        text(
            "INSERT INTO external_app (app_type, name, upstream_url_patterns, "
            "auth_template, organization_credentials, enabled) VALUES ('CUSTOM', "
            ":name, :patterns, '{}', :credentials, true) RETURNING id"
        ),
        {
            "name": name,
            "patterns": patterns,
            "credentials": encrypt_string_to_bytes("{}"),
        },
    ).scalar_one()
    integration_id = conn.execute(
        text(
            "INSERT INTO integration (kind, name, description, owner_user_id, "
            "installation_policy, auth_mode, auth_method, header_template, "
            "credential_fields, external_app_id) VALUES ('api', :name, 'Tickets', "
            ":user_id, 'AVAILABLE', 'shared', 'api_key', "
            '\'{"X-Token": "{token}"}\', '
            '\'[{"key": "token", "label": "Token", "secret": true}]\', '
            ":app_id) RETURNING id"
        ),
        {"name": name, "user_id": user_id, "app_id": app_id},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO integration_connection (integration_id, user_id, secret, "
            "status) VALUES (:id, NULL, :secret, 'connected')"
        ),
        {
            "id": integration_id,
            "secret": encrypt_string_to_bytes(
                json.dumps({"fields": {"token": f"{name}-token"}})
            ),
        },
    )
    conn.execute(
        text(
            "INSERT INTO integration_action (integration_id, key, source, "
            "display_name, default_policy) VALUES (:id, 'unspecified', "
            "'external_app', :name, 'ask')"
        ),
        {"id": integration_id, "name": name},
    )
    conn.execute(
        text(
            "INSERT INTO integration_action_policy (integration_id, action, user_id, "
            "policy) VALUES (:id, 'unspecified', NULL, 'allow')"
        ),
        {"id": integration_id},
    )
    return integration_id


def _seed(conn: Connection, user_ids: list[UUID]) -> tuple[UUID, int, dict[str, int]]:
    tag = uuid4().hex[:8]
    user_id = uuid4()
    user_ids.append(user_id)
    conn.execute(
        text(
            'INSERT INTO "user" (id, email, hashed_password, is_active, '
            "is_superuser, is_verified) VALUES (:id, :email, '', true, false, true)"
        ),
        {"id": user_id, "email": f"url-pattern-apps-{tag}@example.com"},
    )
    persona_id = conn.execute(
        text(
            "INSERT INTO persona (name, user_id, deleted, description, is_listed, "
            "is_public, builtin_persona) VALUES (:name, :user_id, false, 'd', true, "
            "true, false) RETURNING id"
        ),
        {"name": f"url-pattern-apps-{tag}", "user_id": user_id},
    ).scalar_one()
    apps = {
        "prefix": ["https://tickets.example.com/api/*"],
        "host": ["https://wiki.example.com/*"],
        "two_hosts": ["https://a.example.com/*", "https://b.example.com/*"],
        "inner_wildcard": ["https://c.example.com/v1/*/items"],
        "no_slash": ["https://d.example.com/v1*"],
    }
    ids = {
        role: _insert_url_pattern_app(conn, user_id, f"{role}-{tag}", patterns)
        for role, patterns in apps.items()
    }
    for integration_id in ids.values():
        conn.execute(
            text(
                "INSERT INTO persona__integration (persona_id, integration_id, "
                "action_settings) VALUES (:persona_id, :id, "
                '\'{"actions": {"unspecified": "allow"}}\')'
            ),
            {"persona_id": persona_id, "id": integration_id},
        )
    return user_id, persona_id, ids


def _rows(conn: Connection, ids: list[int]) -> dict[int, Any]:
    return {
        row.id: row
        for row in conn.execute(
            text(
                "SELECT i.id, i.external_app_id, i.tool_id, a.base_url, "
                "a.openapi_document, t.openapi_schema, t.user_id AS tool_user_id, "
                "(SELECT count(*) FROM persona__integration p "
                " WHERE p.integration_id = i.id) AS links, "
                "(SELECT count(*) FROM integration_action_policy p "
                " WHERE p.integration_id = i.id AND p.action = 'unspecified') "
                " AS policies, "
                "(SELECT count(*) FROM integration_action ia "
                " WHERE ia.integration_id = i.id) AS actions "
                "FROM integration i LEFT JOIN api_app a ON a.id = i.api_app_id "
                "LEFT JOIN tool t ON t.id = i.tool_id WHERE i.id = ANY(:ids)"
            ),
            {"ids": ids},
        )
    }


def test_a_prefix_pattern_app_becomes_a_rest_app_in_place(
    engine: Engine, user_ids: list[UUID]
) -> None:
    with engine.begin() as conn:
        user_id, _, ids = _seed(conn, user_ids)

    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=REVISION)

    with engine.connect() as conn:
        rows = _rows(conn, list(ids.values()))
    converted = {
        "prefix": "https://tickets.example.com/api",
        "host": "https://wiki.example.com",
    }
    for role, base_url in converted.items():
        row = rows[ids[role]]
        assert row.external_app_id is None
        assert row.base_url == base_url
        # The previous release reads the same spec from the tool row.
        assert json.loads(row.openapi_document) == row.openapi_schema
        assert row.openapi_schema["servers"] == [{"url": base_url}]
        assert row.openapi_schema["paths"] == {}
        assert row.tool_user_id == user_id
        assert (row.links, row.policies, row.actions) == (1, 1, 0)
    for role in ("two_hosts", "inner_wildcard", "no_slash"):
        row = rows[ids[role]]
        assert row.external_app_id is not None
        assert row.tool_id is None
        assert (row.links, row.policies, row.actions) == (1, 1, 1)

    with Session(engine) as db_session:
        user = db_session.get(User, user_id)
        assert user is not None
        for role, base_url in converted.items():
            integration = get_integration_by_id(ids[role], db_session)
            assert integration is not None
            config = ApiKindHandler().load_config(integration, db_session)
            assert (config.shape, config.base_url) == (ApiShape.OPENAPI, base_url)
            # The saved sign-in still goes on each request.
            credentials = resolve_call_credentials(integration, user, db_session)
            assert isinstance(credentials, CallCredentials), credentials
            assert dict(credentials.headers) == {"X-Token": f"{integration.name}-token"}
