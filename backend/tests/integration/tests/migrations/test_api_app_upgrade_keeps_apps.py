"""An upgrade to head from a release before the api_app table (4d900adc4242),
or from the release that added it (main at ce6d912380d7), keeps each app
working: chat reads REST apps only from api_app, so each one needs its row.
Credentials, policies, links and approvals are not touched, and each stored
secret still reads as the same value."""

import json
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, select, text
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
from onyx.db.models import (
    IntegrationConnection,
    IntegrationOAuthClient,
    User,
)
from onyx.integrations.call_credentials import resolve_call_credentials
from onyx.integrations.chat_tools import build_integration_chat_tools
from onyx.integrations.connection_models import (
    ConnectionSecret,
    read_connection_secret,
    read_oauth_client,
)
from onyx.integrations.models import ActionSettings, ApprovalMode, CallCredentials
from onyx.tools.models import (
    IntegrationChatRequest,
    IntegrationEntry,
    IntegrationLinkConfiguration,
    ToolOptions,
)
from onyx.utils.encryption import encrypt_string_to_bytes
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PRE_API_APP_REVISION = "4d900adc4242"
MAIN_REVISION = "ce6d912380d7"

SERVER = "https://orders.example.com/v1"


def _spec(title: str) -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {"title": title, "description": title, "version": "1"},
        "servers": [{"url": SERVER}],
        "paths": {
            "/orders/{order_id}": {
                "get": {
                    "operationId": "getOrder",
                    "summary": "Get an order",
                    "parameters": [
                        {
                            "name": "order_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                }
            },
            "/orders": {
                "post": {
                    "operationId": "createOrder",
                    "summary": "Create an order",
                    "requestBody": {
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    },
                }
            },
        },
    }


# The tables an upgrade must leave as they were, with the columns that later
# revisions add left out.
SNAPSHOT_TABLES: dict[str, tuple[str, list[str]]] = {
    "integration": ("id", ["api_app_id"]),
    "integration_connection": ("id", []),
    "integration_oauth_client": ("integration_id", ["legacy_redirect_path"]),
    "integration_action": ("id", []),
    "integration_action_policy": ("id", []),
    "persona__integration": ("integration_id", []),
    "tool": ("id", []),
    "mcp_server": ("id", []),
    "external_app": ("id", []),
    "approval_request": ("id", []),
    "action_approval": ("approval_id", ["chat_session_id", "command_id"]),
    "chat_session": ("id", []),
    "oauth_account": ("id", []),
}


@dataclass
class Seeded:
    user_id: UUID
    persona_id: int
    chat_session_id: UUID
    # Integration ids by role.
    rest_key: int
    rest_legacy_headers: int
    rest_login: int
    rest_oauth: int
    mcp: int
    preset: int
    custom: int
    tool_options: dict[str, Any]

    @property
    def rest(self) -> list[int]:
        return [
            self.rest_key,
            self.rest_legacy_headers,
            self.rest_login,
            self.rest_oauth,
        ]

    @property
    def all(self) -> list[int]:
        return [*self.rest, self.mcp, self.preset, self.custom]


def _engine() -> Engine:
    return create_engine(
        build_connection_string(
            db=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            db_api=SYNC_DB_API,
        )
    )


def _encrypted_json(value: Any) -> bytes:
    return encrypt_string_to_bytes(json.dumps(value))


def _insert_integration(
    conn: Connection,
    name: str,
    *,
    kind: str = "api",
    auth_mode: str,
    auth_method: str | None,
    header_template: dict[str, str] | None = None,
    credential_fields: list[dict[str, Any]] | None = None,
    tool_id: int | None = None,
    mcp_server_id: int | None = None,
    external_app_id: int | None = None,
) -> int:
    return conn.execute(
        text(
            "INSERT INTO integration (kind, name, installation_policy, auth_mode, "
            "auth_method, header_template, credential_fields, tool_id, "
            "mcp_server_id, external_app_id) VALUES (:kind, :name, 'AVAILABLE', "
            ":auth_mode, :auth_method, CAST(:header_template AS jsonb), "
            "CAST(:credential_fields AS jsonb), :tool_id, :mcp_server_id, "
            ":external_app_id) RETURNING id"
        ),
        {
            "kind": kind,
            "name": name,
            "auth_mode": auth_mode,
            "auth_method": auth_method,
            "header_template": (
                json.dumps(header_template) if header_template is not None else None
            ),
            "credential_fields": (
                json.dumps(credential_fields) if credential_fields is not None else None
            ),
            "tool_id": tool_id,
            "mcp_server_id": mcp_server_id,
            "external_app_id": external_app_id,
        },
    ).scalar_one()


def _insert_rest_tool(conn: Connection, name: str, passthrough: bool = False) -> int:
    return conn.execute(
        text(
            "INSERT INTO tool (name, description, display_name, openapi_schema, "
            "passthrough_auth, enabled) VALUES (:name, 'd', :name, "
            "CAST(:schema AS jsonb), :passthrough, true) RETURNING id"
        ),
        {"name": name, "schema": json.dumps(_spec(name)), "passthrough": passthrough},
    ).scalar_one()


def _insert_rest_actions(conn: Connection, integration_id: int) -> None:
    conn.execute(
        text(
            "INSERT INTO integration_action (integration_id, key, source, "
            "display_name, read_only, default_policy, http_method, path_template) "
            "VALUES (:id, 'getOrder', 'openapi', 'Get an order', true, 'allow', "
            "'GET', '/orders/{order_id}'), (:id, 'createOrder', 'openapi', "
            "'Create an order', false, 'ask', 'POST', '/orders')"
        ),
        {"id": integration_id},
    )


def _insert_connection(
    conn: Connection,
    integration_id: int,
    user_id: UUID | None,
    secret: Any,
    legacy_format: str | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO integration_connection (integration_id, user_id, secret, "
            "status, legacy_format) VALUES (:integration_id, :user_id, :secret, "
            "'connected', :legacy_format)"
        ),
        {
            "integration_id": integration_id,
            "user_id": user_id,
            "secret": _encrypted_json(secret),
            "legacy_format": legacy_format,
        },
    )


def _seed(conn: Connection) -> Seeded:
    tag = uuid4().hex[:8]
    user_id = uuid4()
    conn.execute(
        text(
            'INSERT INTO "user" (id, email, hashed_password, is_active, '
            "is_superuser, is_verified) VALUES (:id, :email, '', true, false, true)"
        ),
        {"id": user_id, "email": f"api-app-upgrade-{tag}@example.com"},
    )
    conn.execute(
        text(
            "INSERT INTO oauth_account (id, user_id, oauth_name, access_token, "
            "account_id, account_email) VALUES (:id, :user_id, 'oidc', "
            "'login-token', 'acct', 'acct@example.com')"
        ),
        {"id": uuid4(), "user_id": user_id},
    )
    persona_id = conn.execute(
        text(
            "INSERT INTO persona (name, deleted, description, is_listed, "
            "is_public, builtin_persona) VALUES (:name, false, 'd', true, true, "
            "false) RETURNING id"
        ),
        {"name": f"api-app-upgrade-{tag}"},
    ).scalar_one()

    # A shared API key in the new format, filled into the header template.
    rest_key = _insert_integration(
        conn,
        f"rest-key-{tag}",
        auth_mode="shared",
        auth_method="api_key",
        header_template={"X-Api-Key": "{api_key}"},
        credential_fields=[{"key": "api_key", "label": "API key", "secret": True}],
        tool_id=_insert_rest_tool(conn, f"rest_key_{tag}"),
    )
    _insert_connection(conn, rest_key, None, {"fields": {"api_key": "org-key"}})
    # The static headers of a custom tool, as the integration tables
    # migration copied them.
    rest_legacy_headers = _insert_integration(
        conn,
        f"rest-headers-{tag}",
        auth_mode="shared",
        auth_method="api_key",
        tool_id=_insert_rest_tool(conn, f"rest_headers_{tag}"),
    )
    _insert_connection(
        conn,
        rest_legacy_headers,
        None,
        [{"key": "X-Static", "value": "static-{1}"}],
        legacy_format="tool_headers",
    )
    # A passthrough auth tool sends the Onyx login token.
    rest_login = _insert_integration(
        conn,
        f"rest-login-{tag}",
        auth_mode="individual",
        auth_method="onyx_login",
        tool_id=_insert_rest_tool(conn, f"rest_login_{tag}", passthrough=True),
    )
    # A per-user OAuth sign-in with an admin-entered client.
    rest_oauth = _insert_integration(
        conn,
        f"rest-oauth-{tag}",
        auth_mode="individual",
        auth_method="oauth2",
        tool_id=_insert_rest_tool(conn, f"rest_oauth_{tag}"),
    )
    conn.execute(
        text(
            "INSERT INTO integration_oauth_client (integration_id, provider_mode, "
            "authorization_url, token_url, scopes, client_id, client_secret) "
            "VALUES (:id, 'manual', 'https://auth.example.com/authorize', "
            "'https://auth.example.com/token', ARRAY['orders'], :client_id, "
            ":client_secret)"
        ),
        {
            "id": rest_oauth,
            "client_id": encrypt_string_to_bytes("client-1"),
            "client_secret": encrypt_string_to_bytes("client-secret-1"),
        },
    )
    _insert_connection(
        conn,
        rest_oauth,
        user_id,
        {"access_token": "user-token", "refresh_token": "user-refresh"},
    )
    for integration_id in (rest_key, rest_legacy_headers, rest_login, rest_oauth):
        _insert_rest_actions(conn, integration_id)

    # An MCP server with an old admin config.
    server_id = conn.execute(
        text(
            "INSERT INTO mcp_server (owner, name, server_url, transport) VALUES "
            "('admin@example.com', 'crm', 'https://mcp.example.com/mcp', "
            "'STREAMABLE_HTTP') RETURNING id"
        )
    ).scalar_one()
    mcp = _insert_integration(
        conn,
        f"mcp-{tag}",
        kind="mcp",
        auth_mode="shared",
        auth_method="api_key",
        header_template={"Authorization": "Bearer {api_key}"},
        mcp_server_id=server_id,
    )
    _insert_connection(
        conn,
        mcp,
        None,
        {
            "headers": {"Authorization": "Bearer mcp-key"},
            "header_template": {"Authorization": "Bearer {api_key}"},
            "api_token": "mcp-key",
            "header_substitutions": {},
        },
        legacy_format="mcp_config",
    )
    conn.execute(
        text(
            "INSERT INTO integration_action (integration_id, key, source, "
            "display_name, read_only, input_schema) VALUES (:id, 'search', 'mcp', "
            "'search', true, CAST(:schema AS jsonb))"
        ),
        {"id": mcp, "schema": json.dumps({"type": "object", "properties": {}})},
    )

    # A preset app with an organization token, and a URL-pattern custom app.
    preset_app_id = conn.execute(
        text(
            "INSERT INTO external_app (app_type, name, upstream_url_patterns, "
            "auth_template, organization_credentials, enabled) VALUES ('LINEAR', "
            ":name, ARRAY['https://api\\.linear\\.app/.*'], '{}', :credentials, "
            "true) RETURNING id"
        ),
        {"name": f"linear-{tag}", "credentials": _encrypted_json({})},
    ).scalar_one()
    preset = _insert_integration(
        conn,
        f"linear-{tag}",
        auth_mode="shared",
        auth_method="oauth2",
        external_app_id=preset_app_id,
    )
    _insert_connection(conn, preset, None, {"access_token": "linear-token"})
    custom_app_id = conn.execute(
        text(
            "INSERT INTO external_app (app_type, name, upstream_url_patterns, "
            "auth_template, organization_credentials, enabled) VALUES ('CUSTOM', "
            ":name, ARRAY['https://internal\\.example\\.com/.*'], "
            "CAST(:template AS jsonb), :credentials, true) RETURNING id"
        ),
        {
            "name": f"internal-{tag}",
            "template": json.dumps({"X-Token": "{token}"}),
            "credentials": _encrypted_json({"token": "internal-token"}),
        },
    ).scalar_one()
    custom = _insert_integration(
        conn,
        f"internal-{tag}",
        auth_mode="shared",
        auth_method="api_key",
        header_template={"X-Token": "{token}"},
        external_app_id=custom_app_id,
    )
    _insert_connection(
        conn,
        custom,
        None,
        {"token": "internal-token"},
        legacy_format="external_app_org",
    )

    # Policies: an admin block, a user Always allow and an admin default.
    conn.execute(
        text(
            "INSERT INTO integration_action_policy (integration_id, action, user_id, "
            "policy) VALUES (:key, 'createOrder', NULL, 'blocked'), "
            "(:oauth, 'createOrder', :user_id, 'allow'), (:mcp, '', NULL, 'allow')"
        ),
        {"key": rest_key, "oauth": rest_oauth, "mcp": mcp, "user_id": user_id},
    )
    for integration_id in (
        rest_key,
        rest_legacy_headers,
        rest_login,
        rest_oauth,
        mcp,
        preset,
        custom,
    ):
        conn.execute(
            text(
                "INSERT INTO persona__integration (persona_id, integration_id, "
                "action_settings) VALUES (:persona_id, :integration_id, "
                "CAST(:settings AS jsonb))"
            ),
            {
                "persona_id": persona_id,
                "integration_id": integration_id,
                "settings": json.dumps(
                    {"actions": {"getOrder": "allow"}}
                    if integration_id == rest_legacy_headers
                    else {}
                ),
            },
        )

    # A chat with tool options, a pending approval and a chat grant.
    chat_session_id = uuid4()
    tool_options = {
        "allowed": [
            {"type": "integration", "integration_id": integration_id}
            for integration_id in (
                rest_key,
                rest_legacy_headers,
                rest_login,
                rest_oauth,
                mcp,
                preset,
            )
        ]
    }
    conn.execute(
        text(
            "INSERT INTO chat_session (id, user_id, persona_id, deleted, "
            "shared_status, onyxbot_flow, tool_options) VALUES (:id, :user_id, "
            ":persona_id, false, 'private', false, CAST(:tool_options AS jsonb))"
        ),
        {
            "id": chat_session_id,
            "user_id": user_id,
            "persona_id": persona_id,
            "tool_options": json.dumps(tool_options),
        },
    )
    message_id = conn.execute(
        text(
            "INSERT INTO chat_message (chat_session_id, message, message_type, "
            "token_count) VALUES (:id, 'hi', 'ASSISTANT', 1) RETURNING id"
        ),
        {"id": chat_session_id},
    ).scalar_one()
    for action, decided_via in (
        ("createOrder", None),
        ("createOrder", "SESSION_GRANT"),
    ):
        conn.execute(
            text(
                "INSERT INTO approval_request (id, chat_session_id, chat_message_id, "
                "integration_id, action_id, tool_call_id, tool_name, display_name, "
                "arguments, decision, decided_via) VALUES (:id, :chat_session_id, "
                ":message_id, :integration_id, :action, 'call-1', 'custom', "
                "'Create an order', '{}', :decision, :decided_via)"
            ),
            {
                "id": uuid4(),
                "chat_session_id": chat_session_id,
                "message_id": message_id,
                "integration_id": (rest_login if decided_via else rest_key),
                "action": action,
                "decision": "APPROVED" if decided_via else None,
                "decided_via": decided_via,
            },
        )
    # A Craft approval that waits for an answer.
    build_session_id = uuid4()
    conn.execute(
        text("INSERT INTO build_session (id, user_id) VALUES (:id, :user_id)"),
        {"id": build_session_id, "user_id": user_id},
    )
    conn.execute(
        text(
            "INSERT INTO action_approval (approval_id, session_id, payload, "
            "actions, app_name, integration_id) VALUES (:id, :session_id, "
            "'{\"method\": \"POST\"}', '[\"createOrder\"]', 'orders', :integration_id)"
        ),
        {"id": uuid4(), "session_id": build_session_id, "integration_id": rest_key},
    )
    return Seeded(
        user_id=user_id,
        persona_id=persona_id,
        chat_session_id=chat_session_id,
        rest_key=rest_key,
        rest_legacy_headers=rest_legacy_headers,
        rest_login=rest_login,
        rest_oauth=rest_oauth,
        mcp=mcp,
        preset=preset,
        custom=custom,
        tool_options=tool_options,
    )


def _snapshot(conn: Connection) -> dict[str, list[Any]]:
    snapshot: dict[str, list[Any]] = {}
    for table, (order_by, new_columns) in SNAPSHOT_TABLES.items():
        snapshot[table] = list(
            conn.execute(
                text(
                    f"SELECT to_jsonb(t) - CAST(:new_columns AS text[]) "
                    f"FROM {table} t ORDER BY {order_by}"
                ),
                {"new_columns": new_columns},
            ).scalars()
        )
    return snapshot


@pytest.fixture(params=[["head"], [MAIN_REVISION, "head"]], ids=["pre_api_app", "main"])
def upgraded(
    request: pytest.FixtureRequest,
) -> Generator[tuple[Engine, Seeded, dict[str, list[Any]]], None, None]:
    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision="base", clear_data=True
    )
    upgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PRE_API_APP_REVISION
    )
    engine = _engine()
    try:
        with engine.begin() as conn:
            seeded = _seed(conn)
            before = _snapshot(conn)
        for revision in request.param:
            upgrade_postgres(
                database=POSTGRES_DB, config_name="alembic", revision=revision
            )
        yield engine, seeded, before
    finally:
        engine.dispose()
        downgrade_postgres(
            database=POSTGRES_DB,
            config_name="alembic",
            revision="base",
            clear_data=True,
        )
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")


def test_upgrade_keeps_every_row(
    upgraded: tuple[Engine, Seeded, dict[str, list[Any]]],
) -> None:
    engine, _, before = upgraded
    with engine.connect() as conn:
        assert _snapshot(conn) == before


def test_each_rest_app_gets_its_api_app_row(
    upgraded: tuple[Engine, Seeded, dict[str, list[Any]]],
) -> None:
    engine, seeded, _ = upgraded
    with engine.connect() as conn:
        rows = {
            row.id: row
            for row in conn.execute(
                text(
                    "SELECT i.id, i.api_app_id, a.api_type, a.base_url, "
                    "a.openapi_document, t.openapi_schema FROM integration i "
                    "LEFT JOIN api_app a ON a.id = i.api_app_id "
                    "LEFT JOIN tool t ON t.id = i.tool_id WHERE i.id = ANY(:ids)"
                ),
                {"ids": seeded.all},
            )
        }
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM integration WHERE api_app_id IS NOT NULL "
                    "GROUP BY api_app_id HAVING count(*) > 1"
                )
            ).all()
            == []
        )
    for integration_id in seeded.rest:
        row = rows[integration_id]
        assert row.api_type == "rest"
        assert row.base_url == SERVER
        assert json.loads(row.openapi_document) == row.openapi_schema
    for integration_id in (seeded.mcp, seeded.preset, seeded.custom):
        assert rows[integration_id].api_app_id is None


def test_each_secret_reads_as_before(
    upgraded: tuple[Engine, Seeded, dict[str, list[Any]]],
) -> None:
    engine, seeded, _ = upgraded
    with Session(engine) as db_session:
        secrets = {
            (connection.integration_id, connection.user_id): read_connection_secret(
                connection
            )
            for connection in db_session.scalars(
                select(IntegrationConnection).where(
                    IntegrationConnection.integration_id.in_(seeded.all)
                )
            )
        }
        oauth_client = db_session.get(IntegrationOAuthClient, seeded.rest_oauth)
        assert oauth_client is not None
        client = read_oauth_client(oauth_client)
    assert secrets == {
        (seeded.rest_key, None): ConnectionSecret(fields={"api_key": "org-key"}),
        (seeded.rest_legacy_headers, None): ConnectionSecret(
            headers={"X-Static": "static-{{1}}"}
        ),
        (seeded.rest_oauth, seeded.user_id): ConnectionSecret(
            access_token="user-token", refresh_token="user-refresh"
        ),
        (seeded.mcp, None): ConnectionSecret(
            fields={"api_key": "mcp-key"},
            headers={"Authorization": "Bearer {api_key}"},
        ),
        (seeded.preset, None): ConnectionSecret(access_token="linear-token"),
        (seeded.custom, None): ConnectionSecret(fields={"token": "internal-token"}),
    }
    assert (client.client_id, client.client_secret) == ("client-1", "client-secret-1")


def test_chat_builds_the_tools_of_each_app_with_its_credential(
    upgraded: tuple[Engine, Seeded, dict[str, list[Any]]],
) -> None:
    engine, seeded, _ = upgraded
    with Session(engine) as db_session:
        user = db_session.get(User, seeded.user_id)
        assert user is not None
        tool_options = ToolOptions.model_validate(seeded.tool_options)
        assert tool_options.allowed is not None
        request = IntegrationChatRequest(
            persona_id=seeded.persona_id,
            integration_links=[
                IntegrationLinkConfiguration(
                    integration_id=integration_id,
                    action_settings=ActionSettings.model_validate(
                        {"actions": {"getOrder": "allow"}}
                        if integration_id == seeded.rest_legacy_headers
                        else {}
                    ),
                )
                for integration_id in seeded.all
            ],
            approval_mode=ApprovalMode.INTERACTIVE,
            chat_session_id=seeded.chat_session_id,
            allowed_integrations={
                entry.integration_id: None
                for entry in tool_options.allowed
                if isinstance(entry, IntegrationEntry)
            },
        )
        tools = {
            tool.name: tool
            for tool in build_integration_chat_tools(db_session, user, request)
        }
        headers: dict[int, dict[str, str]] = {}
        for integration_id in [*seeded.rest, seeded.mcp, seeded.preset]:
            integration = get_integration_by_id(integration_id, db_session)
            assert integration is not None
            credentials = resolve_call_credentials(integration, user, db_session)
            assert isinstance(credentials, CallCredentials), credentials
            headers[integration_id] = dict(credentials.headers)

    actions: dict[int, set[str]] = {}
    for name in tools:
        _, integration_id, action = name.split("__", 2)
        actions.setdefault(int(integration_id), set()).add(action.rsplit("__", 1)[-1])
    preset_actions = actions.pop(seeded.preset)
    assert actions == {
        # The admin blocked createOrder.
        seeded.rest_key: {"getOrder"},
        seeded.rest_legacy_headers: {"getOrder", "createOrder"},
        seeded.rest_login: {"getOrder", "createOrder"},
        seeded.rest_oauth: {"getOrder", "createOrder"},
        seeded.mcp: {"search"},
    }
    assert {"linear_issues_read", "linear_issues_create", "request"} <= preset_actions
    # The chat grant of the passthrough app and the user's Always allow of the
    # OAuth app still apply; the pending request still asks.
    assert tools[f"custom__{seeded.rest_login}__createOrder"].approval is None
    assert tools[f"custom__{seeded.rest_oauth}__createOrder"].approval is None
    assert tools[f"custom__{seeded.rest_legacy_headers}__createOrder"].approval
    assert headers == {
        seeded.rest_key: {"X-Api-Key": "org-key"},
        seeded.rest_legacy_headers: {"X-Static": "static-{1}"},
        seeded.rest_login: {"Authorization": "Bearer login-token"},
        seeded.rest_oauth: {"Authorization": "Bearer user-token"},
        seeded.mcp: {"Authorization": "Bearer mcp-key"},
        seeded.preset: {"Authorization": "Bearer linear-token"},
    }
