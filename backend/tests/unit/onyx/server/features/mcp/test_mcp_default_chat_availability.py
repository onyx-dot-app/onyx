from unittest.mock import MagicMock

import pytest
from sqlalchemy import Boolean, Column, Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from onyx.db import persona as persona_db
from onyx.db.models import MCPServer, Persona, Tool, User
from onyx.server.features.default_assistant import api as default_api
from onyx.server.features.default_assistant.models import DefaultAssistantUpdateRequest
from onyx.server.features.mcp.models import MCPConnectionStatus


def test_default_chat_server_summary_uses_visible_tool_attachments() -> None:
    from onyx.db.mcp import get_default_chat_mcp_server_ids

    metadata = MetaData()
    personas = Table(
        "persona",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("builtin_persona", Boolean),
        Column("deleted", Boolean),
    )
    tools = Table(
        "tool",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("mcp_server_id", Integer),
        Column("enabled", Boolean),
    )
    attachments = Table(
        "persona__tool",
        metadata,
        Column("persona_id", Integer),
        Column("tool_id", Integer),
    )
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with Session(engine) as db:
        db.execute(
            personas.insert(),
            [
                {"id": 0, "builtin_persona": True, "deleted": False},
                {"id": 1, "builtin_persona": False, "deleted": False},
                {"id": 2, "builtin_persona": True, "deleted": True},
            ],
        )
        db.execute(
            tools.insert(),
            [
                {"id": 1, "mcp_server_id": 42, "enabled": True},
                {"id": 2, "mcp_server_id": 42, "enabled": False},
                {"id": 3, "mcp_server_id": 43, "enabled": False},
                {"id": 4, "mcp_server_id": 44, "enabled": True},
                {"id": 5, "mcp_server_id": 45, "enabled": True},
                {"id": 6, "mcp_server_id": 46, "enabled": True},
                {"id": 7, "mcp_server_id": None, "enabled": True},
            ],
        )
        db.execute(
            attachments.insert(),
            [
                {"persona_id": persona_id, "tool_id": tool_id}
                for persona_id, tool_id in [
                    (0, 1),
                    (0, 2),
                    (0, 3),
                    (1, 4),
                    (2, 5),
                    (0, 6),
                    (0, 7),
                ]
            ],
        )

        assert get_default_chat_mcp_server_ids([42, 43, 44, 45], db) == {42, 43}
        assert get_default_chat_mcp_server_ids([44, 45], db) == set()
        assert get_default_chat_mcp_server_ids([], db) == set()


def test_scoped_manager_server_summary_reports_only_visible_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.db.enums import MCPServerStatus, PermissionAuthority
    from onyx.server.features.mcp import api
    from onyx.server.features.mcp.models import MCPServer as MCPServerResponse

    db = MagicMock(spec=Session)
    user = User(email="manager@example.com")
    servers = [
        MCPServer(id=42, owner=user.email),
        MCPServer(id=43, owner="other@example.com"),
        MCPServer(id=44, owner="other@example.com"),
    ]
    selected_servers = MagicMock(return_value={43})
    monkeypatch.setattr(api, "get_all_mcp_servers", lambda _: servers)
    monkeypatch.setattr(api, "has_permission", lambda *_: PermissionAuthority.SCOPED)
    monkeypatch.setattr(api, "get_scoped_groups", lambda *_: [])
    monkeypatch.setattr(api, "get_mcp_server_ids_connected_to_groups", lambda *_: {43})
    monkeypatch.setattr(api, "get_default_chat_mcp_server_ids", selected_servers)
    monkeypatch.setattr(api, "can_manage_mcp_server", lambda *_: False)
    monkeypatch.setattr(
        api,
        "_db_mcp_server_to_api_mcp_server",
        lambda server, *_, **__: MCPServerResponse(
            id=server.id,
            name="Server",
            server_url="",
            owner="",
            status=MCPServerStatus.CREATED,
            connection_status=MCPConnectionStatus.NOT_CONNECTED,
        ),
    )

    response = api.get_mcp_servers_for_admin(db, user)

    selected_servers.assert_called_once_with([42, 43], db)
    assert [
        (server.id, server.default_chat_enabled) for server in response.mcp_servers
    ] == [
        (42, False),
        (43, True),
    ]


def test_member_server_summary_reports_only_accessible_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.db.enums import MCPServerStatus
    from onyx.server.features.mcp import api
    from onyx.server.features.mcp.models import MCPServer as MCPServerResponse

    db = MagicMock(spec=Session)
    user = User(email="member@example.com")
    servers = [MCPServer(id=42), MCPServer(id=43)]
    selected_servers = MagicMock(return_value={43})
    monkeypatch.setattr(api, "get_mcp_servers_accessible_to_user", lambda *_: servers)
    monkeypatch.setattr(api, "get_default_chat_mcp_server_ids", selected_servers)
    monkeypatch.setattr(
        api,
        "_db_mcp_server_to_api_mcp_server",
        lambda server, *_, **__: MCPServerResponse(
            id=server.id,
            name="Server",
            server_url="",
            owner="",
            status=MCPServerStatus.CREATED,
            connection_status=MCPConnectionStatus.NOT_CONNECTED,
        ),
    )

    response = api.get_mcp_servers_for_user(db, user)

    selected_servers.assert_called_once_with([42, 43], db)
    assert [
        (server.id, server.default_chat_enabled) for server in response.mcp_servers
    ] == [(42, False), (43, True)]


def tool(tool_id: int, server_id: int | None, name: str) -> Tool:
    return Tool(id=tool_id, name=name, mcp_server_id=server_id, enabled=True)


def test_default_chat_views_share_existing_tool_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = tool(1, 42, "selected")
    other_mcp = tool(2, 43, "other_server")
    built_in = tool(3, None, "search")
    unselected = tool(4, 42, "unselected")
    default = Persona(id=0, tools=[selected, other_mcp, built_in])
    custom = Persona(id=5, tools=[selected, unselected])
    db = MagicMock(spec=Session)
    user = User()
    monkeypatch.setattr(persona_db, "get_default_assistant", lambda _: default)
    monkeypatch.setattr(default_api, "get_default_assistant", lambda _: default)
    monkeypatch.setattr(persona_db, "should_expose_tool_to_fe", lambda _: True)

    def save_selection(tools: list[Tool]) -> None:
        db.query.return_value.filter.return_value.one_or_none.side_effect = tools
        response = default_api.update_default_assistant(
            DefaultAssistantUpdateRequest(tool_ids=[item.id for item in tools]),
            user,
            db,
        )
        assert response.tool_ids == [item.id for item in tools]
        assert (
            default_api.get_default_assistant_configuration(user, db).tool_ids
            == response.tool_ids
        )
        assert custom.tools == [selected, unselected]

    save_selection([other_mcp, built_in])
    save_selection([selected, other_mcp, built_in])
    save_selection([selected, unselected, other_mcp, built_in])
    assert default.system_prompt is None
    assert db.commit.call_count == 3


def test_default_chat_availability_has_no_separate_server_field() -> None:
    from onyx.server.features.mcp.models import MCPServer as MCPServerResponse

    assert "available_in_default_chat" not in MCPServer.__table__.columns
    assert "available_in_default_chat" not in MCPServerResponse.model_fields


def test_discovery_does_not_change_default_or_custom_agent_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.types import Tool as DiscoveredTool

    from onyx.server.features.mcp import api

    existing = tool(1, 42, "old")
    default = Persona(id=0, tools=[existing])
    custom = Persona(id=5, tools=[existing])
    db = MagicMock(spec=Session)
    monkeypatch.setattr(api, "get_tools_by_mcp_server_id", lambda *_, **__: [existing])
    monkeypatch.setattr(api, "create_tool__no_commit", lambda **_: tool(2, 42, "new"))

    api._sync_mcp_server_tools(
        42,
        [
            DiscoveredTool(name="old", inputSchema={}),
            DiscoveredTool(name="new", inputSchema={}),
        ],
        db,
    )

    assert default.tools == [existing]
    assert custom.tools == [existing]
    db.scalar.assert_not_called()
    db.scalars.assert_not_called()
    db.commit.assert_called_once()


@pytest.mark.parametrize(
    "persona_id,accessible,expected_resolution",
    [
        (0, False, False),
        (0, True, True),
        (5, False, True),
    ],
)
def test_default_chat_checks_access_before_resolving_credentials(
    monkeypatch: pytest.MonkeyPatch,
    persona_id: int,
    accessible: bool,
    expected_resolution: bool,
) -> None:
    from onyx.chat.emitter import Emitter
    from onyx.db.models import User
    from onyx.llm.interfaces import LLM
    from onyx.server.features.mcp.credentials import MCPCredentialsError
    from onyx.tools import tool_constructor
    from onyx.tools.models import PersonaToolConfiguration, ToolConfiguration
    from onyx.tools.tool_implementations.search.search_tool import PersonaSearchInfo

    server = MCPServer(id=42)
    configuration = PersonaToolConfiguration(
        persona_id=persona_id,
        persona_name="Test",
        tools=[
            ToolConfiguration(
                id=1,
                name="tool",
                description=None,
                display_name=None,
                in_code_tool_id=None,
                enabled=True,
                openapi_schema=None,
                mcp_input_schema=None,
                custom_headers=None,
                passthrough_auth=False,
                mcp_server_id=42,
                oauth_config_id=None,
            )
        ],
        search=PersonaSearchInfo(
            document_set_names=[],
            search_start_date=None,
            attached_document_ids=[],
            hierarchy_node_ids=[],
        ),
    )
    resolve = MagicMock(side_effect=MCPCredentialsError("No credential"))
    monkeypatch.setattr(tool_constructor, "get_current_search_settings", MagicMock())
    monkeypatch.setattr(tool_constructor, "get_default_document_index", MagicMock())
    monkeypatch.setattr(tool_constructor, "get_mcp_server_by_id", lambda *_: server)
    monkeypatch.setattr(
        tool_constructor, "user_can_access_mcp_server", lambda *_: accessible
    )
    monkeypatch.setattr(tool_constructor, "resolve_mcp_credentials", resolve)

    result = tool_constructor._construct_tools_impl(
        configuration=configuration,
        db_session=MagicMock(spec=Session),
        emitter=MagicMock(spec=Emitter),
        user=User(enable_memory_tool=False),
        llm=MagicMock(spec=LLM),
    )

    assert result == {}
    assert resolve.called is expected_resolution
