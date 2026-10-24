import json
import sqlite3
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Boolean, Column, Integer, MetaData, Table, Text, create_engine
from sqlalchemy.orm import Session

from onyx.db.models import MCPServer, Tool, User
from onyx.server.features.tool import api
from onyx.server.features.tool.models import ToolSnapshot


@pytest.mark.parametrize("nondefault_builtin_deleted", [True, False])
def test_default_chat_tool_summary_uses_visible_tool_attachments(
    nondefault_builtin_deleted: bool,
) -> None:
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
        Column("openapi_schema", Text),
        Column("in_code_tool_id", Text),
        Column("mcp_server_id", Integer),
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
        driver = db.connection().connection.driver_connection
        assert isinstance(driver, sqlite3.Connection)
        driver.create_function(
            "jsonb_typeof",
            1,
            lambda value: (
                "object" if isinstance(json.loads(value or "null"), dict) else "null"
            ),
        )
        db.execute(
            personas.insert(),
            [
                {"id": 0, "builtin_persona": True, "deleted": False},
                {"id": 1, "builtin_persona": False, "deleted": False},
                {
                    "id": 2,
                    "builtin_persona": True,
                    "deleted": nondefault_builtin_deleted,
                },
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
                {"id": 6, "enabled": False},
            ],
        )
        db.execute(tools.update().where(tools.c.id == 6).values(openapi_schema="{}"))
        db.execute(
            attachments.insert(),
            [
                {"persona_id": persona_id, "tool_id": tool_id}
                for persona_id, tool_id in [
                    (0, 1),
                    (0, 2),
                    (1, 3),
                    (2, 4),
                    (0, 5),
                    (0, 6),
                ]
            ],
        )

        assert get_default_chat_tool_ids([1, 2, 3, 4, 6], db) == {1, 2}
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


def test_openapi_list_stamps_default_chat_without_changing_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    tools = [
        Tool(
            id=tool_id,
            name=f"API {tool_id}",
            enabled=True,
            passthrough_auth=False,
            openapi_schema={},
        )
        for tool_id in [1, 2, 3]
    ]
    selected_tools = MagicMock(return_value={1})
    monkeypatch.setattr(api, "get_tools", lambda *_args, **_kwargs: tools)
    monkeypatch.setattr(api, "_connected_tool_ids", lambda *_: set())
    monkeypatch.setattr(api, "_may_view_tool", lambda tool, *_: tool.id != 3)
    monkeypatch.setattr(api, "can_manage_tool", lambda *_: True)
    monkeypatch.setattr(api, "get_default_chat_tool_ids", selected_tools)
    response = api.list_openapi_tools(db, User())
    selected_tools.assert_called_once_with([1, 2], db)
    assert [(tool.id, tool.default_chat_enabled) for tool in response] == [
        (1, True),
        (2, False),
    ]
