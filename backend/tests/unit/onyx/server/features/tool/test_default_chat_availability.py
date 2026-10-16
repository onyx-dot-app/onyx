from unittest.mock import MagicMock

import pytest
from sqlalchemy import Boolean, Column, Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from onyx.db.models import MCPServer, Tool, User
from onyx.server.features.tool import api
from onyx.server.features.tool.models import ToolSnapshot


def test_default_chat_tool_summary_uses_visible_tool_attachments() -> None:
    from onyx.db.tools import get_default_chat_tool_ids

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
                {"id": 1, "enabled": True},
                {"id": 2, "enabled": False},
                {"id": 3, "enabled": True},
                {"id": 4, "enabled": True},
                {"id": 5, "enabled": True},
            ],
        )
        db.execute(
            attachments.insert(),
            [
                {"persona_id": persona_id, "tool_id": tool_id}
                for persona_id, tool_id in [(0, 1), (0, 2), (1, 3), (2, 4), (0, 5)]
            ],
        )

        assert get_default_chat_tool_ids([1, 2, 3, 4], db) == {1, 2}
        assert get_default_chat_tool_ids([3, 4], db) == set()
        assert get_default_chat_tool_ids([], db) == set()


def test_member_tool_list_stamps_default_chat_after_existing_visibility_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    user = User(email="member@example.com")
    selected = Tool(
        id=1,
        name="selected",
        enabled=True,
        passthrough_auth=False,
        openapi_schema={"paths": {}},
    )
    unselected = Tool(
        id=2,
        name="unselected",
        enabled=True,
        passthrough_auth=False,
        openapi_schema={"paths": {}},
    )
    hidden = Tool(id=3, name="hidden", enabled=True, passthrough_auth=False)
    inaccessible_mcp = Tool(
        id=4, name="private", mcp_server_id=44, enabled=True, passthrough_auth=False
    )
    get_tools = MagicMock(return_value=[selected, unselected, hidden, inaccessible_mcp])
    selected_tools = MagicMock(return_value={1})
    monkeypatch.setattr(api, "get_tools", get_tools)
    monkeypatch.setattr(
        api,
        "get_mcp_servers_accessible_to_user",
        lambda *_: [MCPServer(id=42)],
    )
    monkeypatch.setattr(api, "should_expose_tool_to_fe", lambda tool: tool.id != 3)
    monkeypatch.setattr(api, "get_default_chat_tool_ids", selected_tools)

    response = api.list_tools(db, user)

    get_tools.assert_called_once_with(db, only_enabled=True, only_connected_mcp=True)
    selected_tools.assert_called_once_with([1, 2], db)
    assert [(tool.id, tool.default_chat_enabled) for tool in response] == [
        (1, True),
        (2, False),
    ]
    assert all(tool.permissions == {} for tool in response)


def test_default_chat_summary_is_response_only_and_optional() -> None:
    tool = Tool(id=1, name="custom", enabled=True, passthrough_auth=False)

    assert "default_chat_enabled" not in Tool.__table__.columns
    assert ToolSnapshot.from_model(tool).default_chat_enabled is None
