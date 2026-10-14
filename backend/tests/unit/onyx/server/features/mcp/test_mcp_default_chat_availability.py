from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.db import persona as persona_db
from onyx.db.models import MCPServer, Persona, Tool, User
from onyx.server.features.default_assistant import api as default_api
from onyx.server.features.default_assistant.models import DefaultAssistantUpdateRequest


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

    # The MCP page removes only its server's tools from the shared selection.
    save_selection([other_mcp, built_in])
    # Chat Preferences can select a subset; the MCP page reads the same IDs.
    save_selection([selected, other_mcp, built_in])
    # Enabling the server adds its tools without removing other selections.
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
