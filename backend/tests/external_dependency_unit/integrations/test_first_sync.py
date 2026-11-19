"""An integration as migration 730bce2814a0 leaves it: an API integration with
no actions, and a per-user API key MCP server with no header template, each
with synced_at NULL. The first database session of the schema fills them, so
the first read a user makes already sees the data."""

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    IntegrationActionSource,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    PluginInstallationPolicy,
)
from onyx.db.models import (
    Integration,
    IntegrationAction,
    MCPConnectionConfig,
    MCPServer,
    Tool,
    User,
)
from onyx.integrations import sync
from onyx.integrations.chat_tools import build_integration_chat_tools
from onyx.integrations.connection_models import ConnectionState
from onyx.integrations.kinds import api as api_kind
from onyx.integrations.models import ActionSettings, ApprovalMode
from onyx.server.features.integrations import admin_api, api
from onyx.server.features.integrations.models import ConnectionFieldsRequest
from onyx.tools.models import IntegrationChatRequest, IntegrationLinkConfiguration
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    openapi_to_method_specs,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_mcp_integration,
    make_openapi_integration,
)

ORDERS_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Orders", "description": "Orders", "version": "1"},
    "servers": [{"url": "https://orders.example.com"}],
    "paths": {
        "/orders": {
            "get": {"operationId": "listOrders", "summary": "List orders"},
            "post": {"operationId": "createOrder", "summary": "Create an order"},
        }
    },
}
NO_ACTIONS_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Empty", "version": "1"},
    "servers": [{"url": "https://empty.example.com"}],
    "paths": {},
}


@pytest.fixture
def created(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[int], None, None]:
    integration_ids: list[int] = []
    try:
        yield integration_ids
    finally:
        delete_integrations(db_session, integration_ids)


@pytest.fixture
def new_process() -> Generator[None, None, None]:
    """This process has not yet opened a session for the schema."""
    with patch.object(sync, "_synced_schemas", set()):
        yield


@pytest.fixture
def admin(make_test_user: MakeTestUser) -> User:
    return make_test_user("first-sync-admin", is_admin=True)


@pytest.fixture
def member(make_test_user: MakeTestUser) -> User:
    return make_test_user("first-sync-member")


def _as_migrated(db_session: Session, integration_id: int) -> None:
    db_session.execute(
        delete(IntegrationAction).where(
            IntegrationAction.integration_id == integration_id,
            IntegrationAction.source != IntegrationActionSource.MCP,
        )
    )
    db_session.execute(
        update(Integration)
        .where(Integration.id == integration_id)
        .values(synced_at=None, header_template=None, credential_fields=None)
    )
    db_session.commit()


def _migrated_openapi(
    db_session: Session, created: list[int], spec: dict[str, Any]
) -> int:
    """The app refuses a spec with no actions, so the row gets ``spec``
    after the create, as an old tool row can hold it."""
    integration, tool = make_openapi_integration(db_session, openapi_schema=ORDERS_SPEC)
    created.append(integration.id)
    db_session.execute(
        update(Tool).where(Tool.id == tool.id).values(openapi_schema=spec)
    )
    give_access(db_session, [integration])
    _as_migrated(db_session, integration.id)
    return integration.id


def _migrated_per_user_key_server(
    db_session: Session, created: list[int]
) -> tuple[int, int]:
    """Returns the integration id and the id of its admin config."""
    integration, server = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    created.append(integration.id)
    config = MCPConnectionConfig(
        mcp_server_id=server.id,
        user_email="",
        config={
            "header_template": {"X-Api-Key": "{api_key}", "Host": "evil.example.com"}
        },
    )
    db_session.add(config)
    db_session.flush()
    db_session.execute(
        update(MCPServer)
        .where(MCPServer.id == server.id)
        .values(admin_connection_config_id=config.id)
    )
    give_access(
        db_session, [integration], installation_policy=PluginInstallationPolicy.DEFAULT
    )
    _as_migrated(db_session, integration.id)
    return integration.id, config.id


@pytest.mark.usefixtures("new_process")
def test_the_admin_actions_tab_lists_the_actions_of_a_migrated_api_integration(
    db_session: Session, admin: User, created: list[int]
) -> None:
    integration_id = _migrated_openapi(db_session, created, ORDERS_SPEC)

    with get_session_with_current_tenant() as request_session:
        actions = admin_api.get_integration_actions(
            integration_id, admin, request_session
        ).actions

    assert [(a.key, a.default_policy.value) for a in actions] == [
        ("listOrders", "allow"),
        ("createOrder", "ask"),
    ]


@pytest.mark.usefixtures("new_process")
def test_chat_offers_the_actions_of_a_migrated_api_integration(
    db_session: Session, member: User, created: list[int]
) -> None:
    integration_id = _migrated_openapi(db_session, created, ORDERS_SPEC)

    with get_session_with_current_tenant() as request_session:
        tools = build_integration_chat_tools(
            request_session,
            member,
            IntegrationChatRequest(
                persona_id=7,
                integration_links=[
                    IntegrationLinkConfiguration(
                        integration_id=integration_id,
                        action_settings=ActionSettings(),
                    )
                ],
                approval_mode=ApprovalMode.INTERACTIVE,
            ),
        )

    assert sorted(tool.name for tool in tools) == [
        f"custom__{integration_id}__createOrder",
        f"custom__{integration_id}__listOrders",
    ]


@pytest.mark.usefixtures("new_process")
def test_a_spec_with_no_actions_is_read_only_once(
    db_session: Session, admin: User, created: list[int]
) -> None:
    integration_id = _migrated_openapi(db_session, created, NO_ACTIONS_SPEC)

    with patch.object(
        api_kind, "openapi_to_method_specs", wraps=openapi_to_method_specs
    ) as parse:
        with get_session_with_current_tenant() as request_session:
            first = admin_api.get_integration_actions(
                integration_id, admin, request_session
            ).actions
        assert parse.call_count == 1
        # Another process starts and opens its first session.
        sync._synced_schemas.clear()
        with get_session_with_current_tenant() as request_session:
            second = admin_api.get_integration_actions(
                integration_id, admin, request_session
            ).actions
        assert parse.call_count == 1

    assert first == second == []
    db_session.expire_all()
    integration = db_session.get(Integration, integration_id)
    assert integration is not None
    assert integration.synced_at is not None


@pytest.mark.usefixtures("new_process")
def test_a_member_fills_the_fields_of_a_migrated_per_user_key_server(
    db_session: Session, member: User, created: list[int]
) -> None:
    integration_id, _ = _migrated_per_user_key_server(db_session, created)

    with get_session_with_current_tenant() as request_session:
        detail = api.get_integration_for_member(integration_id, member, request_session)
        status = api.save_member_connection(
            integration_id,
            ConnectionFieldsRequest(fields={"api_key": "member-key"}),
            member,
            request_session,
        )

    assert [(f.key, f.label, f.secret) for f in detail.credential_fields] == [
        ("api_key", "api key", True)
    ]
    assert status.state is ConnectionState.CONNECTED
    db_session.expire_all()
    integration = db_session.get(Integration, integration_id)
    assert integration is not None
    # The denylisted Host header does not come over.
    assert integration.header_template == {"X-Api-Key": "{api_key}"}


@pytest.mark.usefixtures("new_process")
def test_an_admin_config_that_does_not_read_is_not_read_again(
    db_session: Session, created: list[int]
) -> None:
    integration_id, config_id = _migrated_per_user_key_server(db_session, created)
    db_session.execute(
        text("UPDATE mcp_connection_config SET config = :config WHERE id = :id"),
        {"config": b"\xff not a config", "id": config_id},
    )
    db_session.commit()

    with get_session_with_current_tenant():
        pass

    db_session.expire_all()
    integration = db_session.get(Integration, integration_id)
    assert integration is not None
    assert integration.synced_at is not None
    assert integration.header_template is None
    assert integration.credential_fields is None
