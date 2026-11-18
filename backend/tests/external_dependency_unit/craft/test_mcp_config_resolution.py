"""``resolve_craft_mcp_servers`` and the Craft MCP list read the MCP
integrations of the plugins the user runs: only a connected integration (or
one with no sign-in) goes into the opencode config, and a Blocked action is a
disabled tool."""

from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationActionPolicyValue,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    PluginInstallationPolicy,
)
from onyx.db.integration import get_mcp_server_for_integration
from onyx.db.models import Integration, User
from onyx.integrations.connection_models import ConnectionState
from onyx.server.features.build.sandbox.util.mcp_config import (
    resolve_craft_mcp_servers,
)
from onyx.server.features.integrations.api import list_integrations_for_member
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    hold_in_plugin,
    make_mcp_integration,
    set_policy,
)


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
def user(make_test_user: MakeTestUser) -> User:
    return make_test_user("craft_mcp_config")


def _mcp(
    db_session: Session,
    created: list[int],
    name: str,
    auth_mode: IntegrationAuthMode = IntegrationAuthMode.NONE,
    auth_method: IntegrationAuthMethod | None = None,
    header_template: dict[str, str] | None = None,
) -> Integration:
    integration, _ = make_mcp_integration(
        db_session,
        server_url=f"https://api-{uuid4().hex[:8]}.example.com/mcp",
        name=name,
        tools=("search", "delete_records"),
        auth_mode=auth_mode,
        auth_method=auth_method,
        header_template=header_template,
    )
    created.append(integration.id)
    hold_in_plugin(
        db_session,
        [integration],
        published=True,
        installation_policy=PluginInstallationPolicy.DEFAULT,
    )
    return integration


def test_a_blocked_action_is_a_disabled_tool(
    db_session: Session, created: list[int], user: User
) -> None:
    integration = _mcp(db_session, created, "Records CRM")
    set_policy(
        db_session,
        integration.id,
        "delete_records",
        IntegrationActionPolicyValue.BLOCKED,
    )

    config = next(
        c
        for c in resolve_craft_mcp_servers(db_session, user)
        if c.integration_id == integration.id
    )
    assert config.key == f"records-crm-{integration.id}"
    assert config.disabled_tools == ("delete_records",)


def test_the_craft_list_agrees_with_the_session_config(
    db_session: Session, created: list[int], user: User
) -> None:
    open_mcp = _mcp(db_session, created, "Open")
    unconnected = _mcp(
        db_session,
        created,
        "Needs sign-in",
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"Authorization": "Bearer {api_key}"},
    )

    emitted = {c.integration_id for c in resolve_craft_mcp_servers(db_session, user)}
    listed = {
        integration.id: integration
        for integration in list_integrations_for_member(user, db_session)
    }
    assert open_mcp.id in emitted
    assert unconnected.id not in emitted
    open_server = get_mcp_server_for_integration(open_mcp.id, db_session)
    unconnected_server = get_mcp_server_for_integration(unconnected.id, db_session)
    assert open_server is not None and unconnected_server is not None
    assert listed[open_mcp.id].mcp_server_id == open_server.id
    assert listed[open_mcp.id].status.state is ConnectionState.CONNECTED
    assert listed[open_mcp.id].name == "Open"
    assert listed[unconnected.id].mcp_server_id == unconnected_server.id
    assert listed[unconnected.id].status.state is not ConnectionState.CONNECTED
