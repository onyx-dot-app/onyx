"""Chat tool construction on the integration tables: which integrations an
agent can use, what a policy does to each action, the approval scope of an
Ask action, the credential of each call, and bot and eval runs."""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.auth.users import get_anonymous_user
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.context.search.models import PersonaSearchInfo
from onyx.db.enums import (
    IntegrationActionPolicyValue,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    PluginInstallationPolicy,
)
from onyx.db.models import (
    Integration,
    Integration__User,
    User,
    UserIntegrationPreference,
)
from onyx.integrations.chat_tools import (
    _integration_tools,
    build_integration_chat_tools,
)
from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.models import ActionSettings, ApprovalMode, IntegrationConfig
from onyx.integrations.registry import get_kind_handler
from onyx.llm.interfaces import LLM
from onyx.tools.interface import Tool
from onyx.tools.models import (
    IntegrationChatRequest,
    IntegrationEntry,
    IntegrationLinkConfiguration,
    PersonaToolConfiguration,
    ToolApprovalScope,
    ToolOptions,
)
from onyx.tools.tool_constructor import CustomToolConfig, construct_tools
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_mcp_integration,
    make_openapi_integration,
    set_policy,
)
from tests.external_dependency_unit.integrations.conftest import add_connection
from tests.external_dependency_unit.integrations.test_list_query_counts import (
    _query_count,
)

AGENT_ID = 7
ALLOW = IntegrationActionPolicyValue.ALLOW
BLOCKED = IntegrationActionPolicyValue.BLOCKED


@pytest.mark.parametrize("kind", ["api", "mcp"])
def test_chat_tool_query_count_is_constant(
    db_session: Session, user: User, integration_ids: list[int], kind: str
) -> None:
    links: list[IntegrationLinkConfiguration] = []
    counts: list[int] = []
    expected_configs: dict[int, IntegrationConfig] = {}
    actual_configs: dict[int, IntegrationConfig | None] = {}
    for size in (3, 10):
        for _ in range(len(links), size):
            factory = _openapi if kind == "api" else _mcp
            integration = factory(
                db_session,
                integration_ids,
                auth_mode=IntegrationAuthMode.SHARED,
                auth_method=IntegrationAuthMethod.API_KEY,
                header_template={"Authorization": "Bearer {api_key}"},
            )
            add_connection(
                db_session,
                integration,
                None,
                ConnectionSecret(fields={"api_key": "shared-key"}),
            )
            _access(db_session, [integration])
            expected_configs[integration.id] = get_kind_handler(
                integration.kind
            ).load_config(integration, db_session)
            links.append(
                IntegrationLinkConfiguration(
                    integration_id=integration.id, action_settings=ActionSettings()
                )
            )
        request = IntegrationChatRequest(
            persona_id=AGENT_ID,
            integration_links=links,
            approval_mode=ApprovalMode.INTERACTIVE,
            chat_session_id=uuid4(),
        )

        def read(
            expected: int = size, request: IntegrationChatRequest = request
        ) -> None:
            with patch(
                "onyx.integrations.chat_tools._integration_tools",
                wraps=_integration_tools,
            ) as build:
                tools = build_integration_chat_tools(db_session, user, request)
            assert len(tools) == expected * 2
            assert len(build.call_args_list) == expected
            for call in build.call_args_list:
                actual_configs[call.args[1].id] = call.kwargs.get("config")

        counts.append(_query_count(db_session, [user], read))
    assert counts[0] == counts[1], counts
    assert actual_configs == expected_configs


def test_chat_tools_without_linked_integrations(
    db_session: Session, user: User
) -> None:
    assert (
        build_integration_chat_tools(
            db_session,
            user,
            IntegrationChatRequest(
                persona_id=AGENT_ID,
                integration_links=[],
                approval_mode=ApprovalMode.INTERACTIVE,
            ),
        )
        == []
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


@pytest.fixture(autouse=True)
def _no_document_index() -> Generator[None, None, None]:
    with (
        patch("onyx.tools.tool_constructor.get_current_search_settings"),
        patch("onyx.tools.tool_constructor.get_default_document_index"),
    ):
        yield


@pytest.fixture
def integration_ids(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[int], None, None]:
    created: list[int] = []
    try:
        yield created
    finally:
        delete_integrations(db_session, created)


@pytest.fixture
def user(make_test_user: MakeTestUser) -> User:
    member = make_test_user("chat_integration_tools")
    member.enable_memory_tool = False
    return member


def _mcp(db_session: Session, created: list[int], **kwargs: Any) -> Integration:
    integration, _ = make_mcp_integration(
        db_session,
        server_url="https://mcp.example.com/mcp",
        name="crm",
        tools=kwargs.pop("tools", ("search", "update")),
        read_only=kwargs.pop("read_only", {"search": True}),
        **kwargs,
    )
    created.append(integration.id)
    return integration


def _openapi(db_session: Session, created: list[int], **kwargs: Any) -> Integration:
    integration, _ = make_openapi_integration(
        db_session, openapi_schema=ORDERS_SPEC, **kwargs
    )
    created.append(integration.id)
    return integration


def _access(
    db_session: Session,
    integrations: list[Integration],
    policy: PluginInstallationPolicy = PluginInstallationPolicy.DEFAULT,
) -> None:
    give_access(db_session, integrations, published=True, installation_policy=policy)


def _configuration(
    links: dict[int, dict[str, Any]], persona_id: int = AGENT_ID
) -> PersonaToolConfiguration:
    return PersonaToolConfiguration(
        persona_id=persona_id,
        persona_name="Agent",
        tools=[],
        search=PersonaSearchInfo(
            document_set_names=[],
            search_start_date=None,
            attached_document_ids=[],
            hierarchy_node_ids=[],
        ),
        integration_links=[
            IntegrationLinkConfiguration(
                integration_id=integration_id,
                action_settings=ActionSettings.model_validate(settings),
            )
            for integration_id, settings in links.items()
        ],
    )


def _build(
    db_session: Session,
    user: User,
    configuration: PersonaToolConfiguration,
    mode: ApprovalMode = ApprovalMode.INTERACTIVE,
    chat_session_id: UUID | None = None,
    tool_options: ToolOptions | None = None,
) -> dict[str, Tool]:
    tools = construct_tools(
        configuration=configuration,
        user=user,
        llm=MagicMock(spec=LLM),
        db_session=db_session,
        custom_tool_config=CustomToolConfig(chat_session_id=chat_session_id),
        approval_mode=mode,
        tool_options=tool_options,
    )
    return {tool.name: tool for tool in tools}


def test_an_agent_offers_the_mcp_and_openapi_actions_of_its_integrations(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    mcp = _mcp(db_session, integration_ids)
    api = _openapi(db_session, integration_ids)
    _access(db_session, [mcp, api])

    tools = _build(db_session, user, _configuration({mcp.id: {}, api.id: {}}))

    assert set(tools) == {
        f"mcp__{mcp.id}__crm__search",
        f"mcp__{mcp.id}__crm__update",
        f"custom__{api.id}__listOrders",
        f"custom__{api.id}__createOrder",
    }
    assert all(tool.id is None for tool in tools.values())
    assert isinstance(tools[f"mcp__{mcp.id}__crm__search"], MCPTool)
    assert isinstance(tools[f"custom__{api.id}__listOrders"], CustomTool)
    # Read-only and GET run; each other action asks, keyed by the integration.
    approvals = {name: tool.approval for name, tool in tools.items()}
    assert approvals == {
        f"mcp__{mcp.id}__crm__search": None,
        f"mcp__{mcp.id}__crm__update": ToolApprovalScope(
            integration_id=mcp.id, action_id="update"
        ),
        f"custom__{api.id}__listOrders": None,
        f"custom__{api.id}__createOrder": ToolApprovalScope(
            integration_id=api.id, action_id="createOrder"
        ),
    }


def test_blocked_by_the_agent_or_the_admin_is_not_offered(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    mcp = _mcp(db_session, integration_ids, tools=("search", "update", "delete"))
    _access(db_session, [mcp])
    set_policy(db_session, mcp.id, "delete", BLOCKED)

    tools = _build(
        db_session,
        user,
        _configuration({mcp.id: {"actions": {"update": "blocked"}}}),
    )

    assert set(tools) == {f"mcp__{mcp.id}__crm__search"}


def test_an_agent_default_of_blocked_offers_only_listed_actions(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    """The shape the migration writes for an agent with some MCP tools."""
    mcp = _mcp(db_session, integration_ids, tools=("search", "update", "delete"))
    _access(db_session, [mcp])

    tools = _build(
        db_session,
        user,
        _configuration(
            {mcp.id: {"default": "blocked", "actions": {"update": "inherit"}}}
        ),
    )

    assert set(tools) == {f"mcp__{mcp.id}__crm__update"}


def test_the_user_token_wins_over_a_literal_authorization_header(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    """A migrated OpenAPI tool keeps its static headers as literal template
    values. The user's token replaced a static Authorization header before."""
    literal = _openapi(
        db_session,
        integration_ids,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={"Authorization": "Bearer static", "X-Team": "blue"},
    )
    templated = _openapi(
        db_session,
        integration_ids,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={"Authorization": "token {access_token}"},
    )
    for integration in (literal, templated):
        add_connection(
            db_session, integration, user.id, ConnectionSecret(access_token="mine")
        )
    _access(db_session, [literal, templated])

    tools = _build(db_session, user, _configuration({literal.id: {}, templated.id: {}}))

    literal_tool = tools[f"custom__{literal.id}__listOrders"]
    templated_tool = tools[f"custom__{templated.id}__listOrders"]
    assert isinstance(literal_tool, CustomTool)
    assert isinstance(templated_tool, CustomTool)
    assert literal_tool.headers == {"Authorization": "Bearer mine", "X-Team": "blue"}
    assert templated_tool.headers == {"Authorization": "token mine"}


def test_an_integration_with_no_usable_credential_offers_nothing(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    individual = _mcp(
        db_session,
        integration_ids,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"X-Key": "{api_key}"},
    )
    shared = _openapi(
        db_session,
        integration_ids,
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"X-Key": "{api_key}"},
    )
    _access(db_session, [individual, shared])
    configuration = _configuration({individual.id: {}, shared.id: {}})

    assert _build(db_session, user, configuration) == {}

    add_connection(
        db_session, individual, user.id, ConnectionSecret(fields={"api_key": "mine"})
    )
    add_connection(
        db_session, shared, None, ConnectionSecret(fields={"api_key": "org"})
    )
    tools = _build(db_session, user, configuration)

    assert len(tools) == 4
    orders = tools[f"custom__{shared.id}__listOrders"]
    assert isinstance(orders, CustomTool)
    assert orders.headers == {"X-Key": "org"}


def test_a_disabled_integration_offers_nothing(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    mcp = _mcp(db_session, integration_ids)
    mcp.enabled = False
    db_session.commit()
    _access(db_session, [mcp])

    assert _build(db_session, user, _configuration({mcp.id: {}})) == {}


def test_an_integration_with_no_access_gives_no_actions(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    mcp = _mcp(db_session, integration_ids)
    _access(db_session, [mcp], PluginInstallationPolicy.NOT_AVAILABLE)

    assert _build(db_session, user, _configuration({mcp.id: {}})) == {}


def test_an_agent_integration_the_user_turned_off_still_gives_its_actions(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    """The on/off choice applies only to the default agent."""
    mcp = _mcp(db_session, integration_ids)
    _access(db_session, [mcp], PluginInstallationPolicy.AVAILABLE)

    assert len(_build(db_session, user, _configuration({mcp.id: {}}))) == 2


def test_ask_actions_follow_the_approval_mode(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    api = _openapi(db_session, integration_ids)
    _access(db_session, [api])
    configuration = _configuration({api.id: {}})
    create = f"custom__{api.id}__createOrder"

    interactive = _build(db_session, user, configuration)
    no_approver = _build(db_session, user, configuration, ApprovalMode.NO_APPROVER)
    evals = _build(db_session, user, configuration, ApprovalMode.RUN_WITHOUT_ASKING)

    assert interactive[create].approval == ToolApprovalScope(
        integration_id=api.id, action_id="createOrder"
    )
    assert create not in no_approver
    assert evals[create].approval is None


def test_a_new_openapi_operation_asks_while_a_migrated_one_runs(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    """The U1 migration writes an admin default allow row for each OpenAPI
    tool that exists at the upgrade. An integration made after it has none."""
    migrated = _openapi(db_session, integration_ids)
    set_policy(db_session, migrated.id, "", ALLOW)
    new = _openapi(db_session, integration_ids)
    _access(db_session, [migrated, new])

    tools = _build(db_session, user, _configuration({migrated.id: {}, new.id: {}}))

    assert tools[f"custom__{migrated.id}__createOrder"].approval is None
    assert tools[f"custom__{new.id}__createOrder"].approval == ToolApprovalScope(
        integration_id=new.id, action_id="createOrder"
    )


def test_a_slack_channel_run_uses_shared_sign_in_and_the_bot_freeze(
    db_session: Session, integration_ids: list[int]
) -> None:
    """A Slack channel runs as the anonymous user with no approver: it offers
    no integration with individual sign-in, and an Ask action only when the
    agent sets it to Allow."""
    anonymous = get_anonymous_user()
    shared = _mcp(db_session, integration_ids, tools=("search", "update", "delete"))
    individual = _openapi(
        db_session,
        integration_ids,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"X-Key": "{api_key}"},
    )
    _access(db_session, [shared, individual])

    tools = _build(
        db_session,
        anonymous,
        _configuration(
            {
                shared.id: {"actions": {"update": "allow"}},
                individual.id: {"actions": {"update": "allow"}},
            }
        ),
        ApprovalMode.NO_APPROVER,
    )

    assert set(tools) == {
        f"mcp__{shared.id}__crm__search",
        f"mcp__{shared.id}__crm__update",
    }
    assert all(tool.approval is None for tool in tools.values())


def test_a_share_of_the_integration_gives_its_actions_on_an_agent(
    db_session: Session,
    user: User,
    make_test_user: MakeTestUser,
    integration_ids: list[int],
) -> None:
    """On an agent that links a private integration, a user with a share of
    the integration gets its actions. A user of the same agent with no access
    gets none: the agent gives no access."""
    owner = make_test_user("chat_share_owner")
    no_access = make_test_user("chat_share_no_access")
    mcp = _mcp(db_session, integration_ids)
    give_access(db_session, [mcp], published=False, owner_user_id=owner.id)
    db_session.add(Integration__User(integration_id=mcp.id, user_id=user.id))
    db_session.commit()
    configuration = _configuration({mcp.id: {}})

    def actions(member: User, on: PersonaToolConfiguration) -> set[str]:
        return {
            name for name in _build(db_session, member, on) if f"__{mcp.id}__" in name
        }

    assert actions(user, configuration) == {
        f"mcp__{mcp.id}__crm__search",
        f"mcp__{mcp.id}__crm__update",
    }
    assert actions(no_access, configuration) == set()
    # The share gives Available, which is off on the default agent until the
    # user turns it on.
    assert actions(user, _configuration({}, persona_id=DEFAULT_PERSONA_ID)) == set()


def test_an_anonymous_user_gets_only_organization_integrations(
    db_session: Session,
    make_test_user: MakeTestUser,
    integration_ids: list[int],
) -> None:
    owner = make_test_user("anonymous_private_owner")
    mcp = _mcp(db_session, integration_ids)
    give_access(db_session, [mcp], published=False, owner_user_id=owner.id)

    assert _build(db_session, get_anonymous_user(), _configuration({mcp.id: {}})) == {}


def test_the_default_agent_uses_the_integrations_that_are_on(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    on = _mcp(db_session, integration_ids)
    off = _openapi(db_session, integration_ids)
    available = _openapi(db_session, integration_ids)
    _access(db_session, [on])
    _access(db_session, [off])
    _access(db_session, [available], PluginInstallationPolicy.AVAILABLE)
    db_session.add(
        UserIntegrationPreference(user_id=user.id, integration_id=off.id, enabled=False)
    )
    db_session.commit()

    tools = _build(
        db_session,
        user,
        # The persona 0 link holds the bot freeze of the integration.
        _configuration(
            {on.id: {"actions": {"update": "blocked"}}},
            persona_id=DEFAULT_PERSONA_ID,
        ),
    )

    ours = {name for name in tools if f"__{on.id}__" in name}
    assert ours == {f"mcp__{on.id}__crm__search"}
    assert not any(f"__{off.id}__" in name for name in tools)
    assert not any(f"__{available.id}__" in name for name in tools)


def test_tool_options_cannot_drop_a_blocked_agent_link(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    mcp = _mcp(db_session, integration_ids)
    _access(db_session, [mcp])

    tools = _build(
        db_session,
        user,
        _configuration({mcp.id: {"actions": {"update": "blocked"}}}),
        tool_options=ToolOptions(
            allowed=[IntegrationEntry(integration_id=mcp.id, actions=["update"])]
        ),
    )

    assert not any(f"__{mcp.id}__" in name for name in tools)


def test_tool_options_cannot_drop_a_required_integration(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    """A member cannot turn a Required integration off, so tool options that leave
    it out still give its actions."""
    required = _mcp(db_session, integration_ids)
    other = _openapi(db_session, integration_ids)
    _access(db_session, [required], PluginInstallationPolicy.REQUIRED)
    _access(db_session, [other])

    tools = _build(
        db_session,
        user,
        _configuration({required.id: {}, other.id: {}}),
        tool_options=ToolOptions(allowed=[IntegrationEntry(integration_id=other.id)]),
    )

    assert any(f"__{required.id}__" in name for name in tools)
    assert any(f"__{other.id}__" in name for name in tools)


def test_an_onyx_login_integration_sends_the_login_token(
    db_session: Session, user: User, integration_ids: list[int]
) -> None:
    api = _openapi(
        db_session,
        integration_ids,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.ONYX_LOGIN,
    )
    _access(db_session, [api])
    configuration = _configuration({api.id: {}})

    login_account = patch(
        "onyx.integrations.connections._live_login_account", return_value=MagicMock()
    )
    with (
        login_account,
        patch(
            "onyx.integrations.connections._fresh_onyx_login_account",
            return_value=None,
        ),
    ):
        assert _build(db_session, user, configuration) == {}
    with (
        login_account,
        patch(
            "onyx.integrations.connections._fresh_onyx_login_account",
            return_value=MagicMock(access_token="login-token", expires_at=None),
        ),
    ):
        tools = _build(db_session, user, configuration)

    orders = tools[f"custom__{api.id}__listOrders"]
    assert isinstance(orders, CustomTool)
    assert orders.headers == {"Authorization": "Bearer login-token"}
