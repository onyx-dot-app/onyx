"""The admin MCP server routes and the agent tool ids of the public API, which
the Terraform provider calls. They keep the request and response shapes of
the release before integrations and read and write the integration tables."""

from collections.abc import Generator
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.configs.constants import MASK_CREDENTIAL_SHORT
from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
    PluginInstallationPolicy,
)
from onyx.db.integration import (
    count_integration_actions,
    get_integration_by_kind_row,
)
from onyx.db.integration_access import load_integration_group_settings
from onyx.db.integration_connection import get_connection
from onyx.db.integration_policy import list_persona_integration_links
from onyx.db.models import (
    Integration,
    Integration__UserGroup,
    MCPServer,
    Tool,
    User,
    UserGroup,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.connection_models import read_connection_secret
from onyx.server.features.integrations import admin_api
from onyx.server.features.integrations.models import (
    IntegrationGroupSettingChange,
    IntegrationGroupSettingsUpdate,
)
from onyx.server.features.mcp import api as mcp_api
from onyx.server.features.mcp.models import (
    MCPAuthTemplate,
    MCPServerSimpleUpdateRequest,
    MCPToolCreateRequest,
)
from onyx.server.features.persona import api as persona_api
from onyx.server.features.persona.models import PersonaUpsertRequest
from onyx.server.features.tool import api as tool_api
from onyx.server.features.tool.models import CustomToolCreate
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.craft.db_helpers import make_group
from tests.external_dependency_unit.integration_helpers import delete_integrations

SERVER_URL = "https://mcp.example.com/mcp"
OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Weather", "description": "Weather", "version": "1.0"},
    "servers": [{"url": "https://weather.example.com"}],
    "paths": {
        "/forecast": {"get": {"operationId": "get_forecast", "summary": "Forecast"}}
    },
}


@pytest.fixture(autouse=True)
def _no_discovery() -> Generator[None, None, None]:
    with patch("onyx.integrations.service.discover_mcp_tools", return_value=[]):
        yield


@pytest.fixture
def admin(make_test_user: MakeTestUser) -> User:
    return make_test_user("mcp-alias-admin", is_admin=True)


@pytest.fixture
def created(
    db_session: Session,
    admin: User,  # noqa: ARG001
) -> Generator[list[int], None, None]:
    """Integrations a test makes; deleted before the users."""
    ids: list[int] = []
    try:
        yield ids
    finally:
        delete_integrations(db_session, ids)


def _request(**fields: Any) -> MCPToolCreateRequest:
    values: dict[str, Any] = {
        "name": f"mcp-alias-{uuid4().hex[:8]}",
        "description": "Weather tools",
        "server_url": SERVER_URL,
        "auth_type": MCPAuthenticationType.NONE,
        "auth_performer": MCPAuthenticationPerformer.ADMIN,
        "transport": MCPTransport.STREAMABLE_HTTP,
        "is_public": True,
        "groups": [],
        "users": [],
    }
    values.update(fields)
    return MCPToolCreateRequest(**values)


def _upsert(db_session: Session, admin: User, created: list[int], **fields: Any) -> int:
    response = mcp_api.upsert_mcp_server_alias(_request(**fields), db_session, admin)
    integration = _integration(db_session, response.server_id)
    if integration.id not in created:
        created.append(integration.id)
    return response.server_id


def _integration(db_session: Session, server_id: int) -> Integration:
    integration = get_integration_by_kind_row(
        Integration.mcp_server_id, server_id, db_session
    )
    assert integration is not None
    return integration


def _installation_policy(
    db_session: Session, integration_id: int
) -> PluginInstallationPolicy:
    return db_session.scalars(
        select(Integration.installation_policy).where(Integration.id == integration_id)
    ).one()


def test_create_saves_a_server_that_onyx_cannot_reach(
    db_session: Session, admin: User, created: list[int]
) -> None:
    """The Terraform provider route saves the server before it is reachable,
    as before integrations. The integration has no actions until a refresh."""
    with patch(
        "onyx.integrations.service.discover_mcp_tools",
        side_effect=ConnectionError("unreachable"),
    ):
        server_id = _upsert(db_session, admin, created)

    integration = _integration(db_session, server_id)
    assert count_integration_actions([integration.id], db_session) == {
        integration.id: 0
    }


def test_create_get_update_and_delete_keep_the_old_shapes(
    db_session: Session, admin: User, created: list[int]
) -> None:
    request = _request()
    response = mcp_api.upsert_mcp_server_alias(request, db_session, admin)
    integration = _integration(db_session, response.server_id)
    created.append(integration.id)
    assert response.model_dump() == {
        "server_id": response.server_id,
        "server_name": request.name,
        "server_url": SERVER_URL,
        "auth_type": "NONE",
        "auth_performer": "ADMIN",
        "no_user_authentication_required": True,
    }
    assert integration.auth_mode is IntegrationAuthMode.NONE
    assert _installation_policy(db_session, integration.id) is (
        PluginInstallationPolicy.AVAILABLE
    )

    server = mcp_api.get_mcp_server_alias(response.server_id, db_session, admin)
    assert server.id == response.server_id
    assert server.model_dump(
        include={
            "name",
            "description",
            "server_url",
            "owner",
            "transport",
            "auth_type",
            "auth_performer",
            "status",
            "is_public",
            "groups",
            "users",
            "available_in_craft",
            "tool_count",
            "auth_template",
        }
    ) == {
        "name": request.name,
        "description": "Weather tools",
        "server_url": SERVER_URL,
        "owner": admin.email,
        "transport": MCPTransport.STREAMABLE_HTTP,
        "auth_type": MCPAuthenticationType.NONE,
        "auth_performer": MCPAuthenticationPerformer.ADMIN,
        "status": "CREATED",
        "is_public": True,
        "groups": [],
        "users": [],
        "available_in_craft": False,
        "tool_count": 0,
        "auth_template": None,
    }

    patched = mcp_api.update_mcp_server_alias(
        response.server_id,
        MCPServerSimpleUpdateRequest(available_in_craft=True),
        db_session,
        admin,
    )
    assert patched.available_in_craft is True

    mcp_api.upsert_mcp_server_alias(
        _request(
            name="renamed",
            description="",
            server_url="https://mcp2.example.com/mcp",
            transport=MCPTransport.SSE,
            is_public=False,
            existing_server_id=response.server_id,
        ),
        db_session,
        admin,
    )
    server = mcp_api.get_mcp_server_alias(response.server_id, db_session, admin)
    assert (server.name, server.description, server.server_url, server.transport) == (
        "renamed",
        "",
        "https://mcp2.example.com/mcp",
        MCPTransport.SSE,
    )
    assert server.is_public is False
    assert server.available_in_craft is True
    server_row = db_session.get(MCPServer, response.server_id)
    assert server_row is not None
    db_session.refresh(server_row)
    assert server_row.name == "renamed"
    assert _installation_policy(db_session, integration.id) is (
        PluginInstallationPolicy.NOT_AVAILABLE
    )

    mcp_api.update_mcp_server_alias(
        response.server_id,
        MCPServerSimpleUpdateRequest(is_public=True),
        db_session,
        admin,
    )
    assert _installation_policy(db_session, integration.id) is (
        PluginInstallationPolicy.AVAILABLE
    )

    assert mcp_api.delete_mcp_server_alias(
        response.server_id, db_session, admin
    ).success
    assert db_session.get(Integration, integration.id) is None
    with pytest.raises(OnyxError) as error:
        mcp_api.get_mcp_server_alias(response.server_id, db_session, admin)
    assert error.value.error_code is OnyxErrorCode.NOT_FOUND


def test_a_shared_token_is_write_only_and_rotates(
    db_session: Session, admin: User, created: list[int]
) -> None:
    server_id = _upsert(
        db_session,
        admin,
        created,
        auth_type=MCPAuthenticationType.API_TOKEN,
        api_token="token-one",
        api_token_changed=True,
    )
    integration = _integration(db_session, server_id)
    assert (integration.auth_mode, integration.auth_method) == (
        IntegrationAuthMode.SHARED,
        IntegrationAuthMethod.API_KEY,
    )

    def stored_token() -> str:
        connection = get_connection(db_session, integration.id, None)
        assert connection is not None
        return read_connection_secret(connection).fields["api_key"]

    assert stored_token() == "token-one"
    server = mcp_api.get_mcp_server_alias(server_id, db_session, admin)
    assert server.auth_type is MCPAuthenticationType.API_TOKEN
    assert server.auth_template == MCPAuthTemplate(
        headers={"Authorization": "Bearer {api_key}"}, required_fields=["api_key"]
    )
    assert "token-one" not in server.model_dump_json()

    _upsert(
        db_session,
        admin,
        created,
        description="second",
        auth_type=MCPAuthenticationType.API_TOKEN,
        existing_server_id=server_id,
    )
    assert stored_token() == "token-one"

    _upsert(
        db_session,
        admin,
        created,
        auth_type=MCPAuthenticationType.API_TOKEN,
        api_token="token-two",
        api_token_changed=True,
        existing_server_id=server_id,
    )
    assert stored_token() == "token-two"

    with pytest.raises(OnyxError) as error:
        _upsert(
            db_session,
            admin,
            created,
            auth_type=MCPAuthenticationType.API_TOKEN,
            api_token=MASK_CREDENTIAL_SHORT,
            api_token_changed=True,
            existing_server_id=server_id,
        )
    assert error.value.error_code is OnyxErrorCode.INVALID_INPUT
    db_session.rollback()
    assert stored_token() == "token-two"


def test_a_per_user_template_keeps_literals_and_survives_a_switch_to_shared(
    db_session: Session, admin: User, created: list[int]
) -> None:
    server_id = _upsert(
        db_session,
        admin,
        created,
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        auth_template=MCPAuthTemplate(
            headers={"X-Api-Key": "{api_key}", "X-Tenant": "a-literal-value"}
        ),
        admin_credentials={"api_key": "the-admins-own-key"},
        admin_credentials_changed={"api_key": True},
    )
    integration = _integration(db_session, server_id)
    assert integration.auth_mode is IntegrationAuthMode.INDIVIDUAL
    assert integration.header_template == {
        "X-Api-Key": "{api_key}",
        "X-Tenant": "a-literal-value",
    }
    own = get_connection(db_session, integration.id, admin.id)
    assert own is not None
    assert read_connection_secret(own).fields == {"api_key": "the-admins-own-key"}

    server = mcp_api.get_mcp_server_alias(server_id, db_session, admin)
    assert server.auth_performer is MCPAuthenticationPerformer.PER_USER
    assert server.auth_template is not None
    assert server.auth_template.headers["X-Api-Key"] == "{api_key}"
    assert server.auth_template.headers["X-Tenant"] != "a-literal-value"
    assert server.auth_template.required_fields == ["api_key"]

    # An omitted template keeps the stored one.
    _upsert(
        db_session,
        admin,
        created,
        auth_type=MCPAuthenticationType.API_TOKEN,
        api_token="a-shared-token",
        api_token_changed=True,
        existing_server_id=server_id,
    )
    db_session.refresh(integration)
    assert integration.auth_mode is IntegrationAuthMode.SHARED
    assert integration.header_template == {
        "X-Api-Key": "{api_key}",
        "X-Tenant": "a-literal-value",
    }
    shared = get_connection(db_session, integration.id, None)
    assert shared is not None
    assert read_connection_secret(shared).fields == {"api_key": "a-shared-token"}


def test_a_private_user_list_round_trips_and_clears(
    db_session: Session,
    admin: User,
    make_test_user: MakeTestUser,
    created: list[int],
) -> None:
    other = make_test_user("mcp-alias-other")
    server_id = _upsert(
        db_session, admin, created, is_public=False, users=[admin.id, other.id]
    )
    server = mcp_api.get_mcp_server_alias(server_id, db_session, admin)
    assert server.is_public is False
    assert sorted(server.users) == sorted([admin.id, other.id])

    _upsert(
        db_session,
        admin,
        created,
        is_public=False,
        users=[],
        existing_server_id=server_id,
    )
    assert mcp_api.get_mcp_server_alias(server_id, db_session, admin).users == []


def test_agent_tool_ids_round_trip_through_the_integration_links(
    db_session: Session, admin: User, created: list[int]
) -> None:
    tool = tool_api.create_custom_tool(
        CustomToolCreate(
            name=f"agent-tool-{uuid4().hex[:8]}",
            description="",
            definition=OPENAPI_SPEC,
            passthrough_auth=False,
        ),
        db_session,
        admin,
    )
    integration = get_integration_by_kind_row(Integration.tool_id, tool.id, db_session)
    assert integration is not None
    created.append(integration.id)

    def request(tool_ids: list[int], name: str) -> PersonaUpsertRequest:
        return PersonaUpsertRequest(
            name=name,
            description="",
            system_prompt="",
            task_prompt="",
            datetime_aware=False,
            document_set_ids=[],
            tool_ids=tool_ids,
            is_public=True,
        )

    name = f"agent-{uuid4().hex[:8]}"
    agent = persona_api.create_persona(request([tool.id], name), admin, db_session)
    assert [t.id for t in agent.tools] == [tool.id]
    assert [
        t.id for t in persona_api.get_persona(agent.id, admin, db_session).tools
    ] == [tool.id]
    assert len(list_persona_integration_links(db_session, agent.id)) == 1

    updated = persona_api.update_persona(agent.id, request([], name), admin, db_session)
    assert updated.tools == []
    assert list_persona_integration_links(db_session, agent.id) == []
    # The integration stays; only the link of the agent goes.
    assert db_session.get(Integration, integration.id) is not None


def test_agent_mcp_tool_ids_round_trip_and_change_the_selection(
    db_session: Session, admin: User, created: list[int]
) -> None:
    server_id = _upsert(db_session, admin, created)
    alpha, beta = (
        Tool(name=name, description="", mcp_server_id=server_id, user_id=admin.id)
        for name in ("alpha", "beta")
    )
    db_session.add_all([alpha, beta])
    db_session.commit()

    def request(tool_ids: list[int], name: str) -> PersonaUpsertRequest:
        return PersonaUpsertRequest(
            name=name,
            description="",
            system_prompt="",
            task_prompt="",
            datetime_aware=False,
            document_set_ids=[],
            tool_ids=tool_ids,
            is_public=True,
        )

    def links() -> list[dict[str, Any] | None]:
        return [
            row.action_settings
            for row in list_persona_integration_links(db_session, agent.id)
        ]

    name = f"agent-{uuid4().hex[:8]}"
    agent = persona_api.create_persona(request([alpha.id], name), admin, db_session)
    assert [t.id for t in agent.tools] == [alpha.id]

    both = persona_api.update_persona(
        agent.id, request([alpha.id, beta.id], name), admin, db_session
    )
    assert sorted(t.id for t in both.tools) == sorted([alpha.id, beta.id])
    assert links() == [
        {"default": "blocked", "actions": {"alpha": "inherit", "beta": "inherit"}}
    ]

    beta_only = persona_api.update_persona(
        agent.id, request([beta.id], name), admin, db_session
    )
    assert [t.id for t in beta_only.tools] == [beta.id]

    cleared = persona_api.update_persona(agent.id, request([], name), admin, db_session)
    assert cleared.tools == []
    assert links() == []


def test_a_private_server_lists_each_group_with_access(
    db_session: Session, admin: User, created: list[int]
) -> None:
    """The legacy view has no group settings, so it lists a group whose own
    setting gives access. A legacy edit keeps the setting."""
    group = make_group(db_session)
    db_session.commit()
    try:
        server_id = _upsert(db_session, admin, created)
        integration = _integration(db_session, server_id)
        admin_api.set_integration_group_settings(
            integration.id,
            IntegrationGroupSettingsUpdate(
                group_settings=[
                    IntegrationGroupSettingChange(
                        group_id=group.id,
                        installation_policy=PluginInstallationPolicy.AVAILABLE,
                    )
                ]
            ),
            admin,
            db_session,
        )

        # A public server lists no groups, so a Terraform plan with
        # groups=[] converges.
        server = mcp_api.get_mcp_server_alias(server_id, db_session, admin)
        assert (server.is_public, server.groups) == (True, [])

        mcp_api.update_mcp_server_alias(
            server_id,
            MCPServerSimpleUpdateRequest(is_public=False),
            db_session,
            admin,
        )
        server = mcp_api.get_mcp_server_alias(server_id, db_session, admin)
        assert (server.is_public, server.groups) == (False, [group.id])

        # A share-only edit keeps the group setting.
        mcp_api.update_mcp_server_alias(
            server_id,
            MCPServerSimpleUpdateRequest(users=[admin.id]),
            db_session,
            admin,
        )
        assert [
            setting.group_id
            for setting in load_integration_group_settings(integration.id, db_session)
        ] == [group.id]

        # The legacy groups are each group with access, so groups=[] takes
        # the access away, setting and all.
        mcp_api.update_mcp_server_alias(
            server_id,
            MCPServerSimpleUpdateRequest(groups=[]),
            db_session,
            admin,
        )
        assert load_integration_group_settings(integration.id, db_session) == []
        server = mcp_api.get_mcp_server_alias(server_id, db_session, admin)
        assert server.groups == []
    finally:
        db_session.rollback()
        db_session.execute(
            delete(Integration__UserGroup).where(
                Integration__UserGroup.user_group_id == group.id
            )
        )
        db_session.execute(delete(UserGroup).where(UserGroup.id == group.id))
        db_session.commit()
