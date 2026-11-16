from collections.abc import Generator
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, Integer, MetaData, Table, Uuid, create_engine
from sqlalchemy.orm import Session

from onyx.db.models import Tool, ToolUserPreference, User
from onyx.db.tools import (
    get_tool_user_preferences,
    upsert_tool_user_preference__no_commit,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.tool import api
from onyx.server.features.tool.models import ToolSnapshot, ToolUserPreferences


@pytest.fixture
def preference_db() -> Generator[Session, None, None]:
    metadata = MetaData()
    Table("user", metadata, Column("id", Uuid, primary_key=True))
    Table("tool", metadata, Column("id", Integer, primary_key=True))
    cast(Table, ToolUserPreference.__table__).to_metadata(metadata)
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_updates_are_scoped_to_user_and_tool(preference_db: Session) -> None:
    user_id, other_user_id = uuid4(), uuid4()
    assert get_tool_user_preferences([42], user_id, preference_db) == {}
    for enabled in (False, True, False):
        preference = upsert_tool_user_preference__no_commit(
            42, user_id, preference_db, enabled_in_chat=enabled
        )
        assert preference.enabled_in_chat is enabled
    assert get_tool_user_preferences([42], other_user_id, preference_db) == {}
    assert get_tool_user_preferences([43], user_id, preference_db) == {}


@pytest.mark.parametrize("payload", [{}, {"enabled_in_chat": None}])
def test_update_requires_boolean(payload: dict[str, None]) -> None:
    with pytest.raises(ValidationError):
        ToolUserPreferences.model_validate(payload)


@pytest.mark.parametrize(
    "tool",
    [
        Tool(id=42, in_code_tool_id="SearchTool"),
        Tool(id=42, mcp_server_id=1),
        Tool(id=42),
        Tool(id=42, openapi_schema={"paths": {}}, enabled=False),
    ],
)
def test_update_rejects_wrong_kind_or_disabled_plugin(
    monkeypatch: pytest.MonkeyPatch, tool: Tool
) -> None:
    db = MagicMock(spec=Session)
    monkeypatch.setattr(api, "get_tool_by_id", lambda *_: tool)
    write = MagicMock()
    monkeypatch.setattr(api, "upsert_tool_user_preference__no_commit", write)
    with pytest.raises(OnyxError):
        api.update_tool_user_preferences(
            42, ToolUserPreferences(enabled_in_chat=True), db, User(id=uuid4())
        )
    write.assert_not_called()
    db.commit.assert_not_called()


def test_update_rejects_missing_hidden_or_admin_unselected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    user = User(id=uuid4())
    tool = Tool(id=42, openapi_schema={"paths": {}}, enabled=True)
    monkeypatch.setattr(api, "get_tool_by_id", MagicMock(side_effect=ValueError()))
    with pytest.raises(OnyxError):
        api.update_tool_user_preferences(
            42, ToolUserPreferences(enabled_in_chat=False), db, user
        )
    monkeypatch.setattr(api, "get_tool_by_id", lambda *_: tool)
    monkeypatch.setattr(api, "should_expose_tool_to_fe", lambda *_: False)
    with pytest.raises(OnyxError):
        api.update_tool_user_preferences(
            42, ToolUserPreferences(enabled_in_chat=False), db, user
        )
    monkeypatch.setattr(api, "should_expose_tool_to_fe", lambda *_: True)
    monkeypatch.setattr(api, "get_default_chat_tool_ids", lambda *_: set())
    with pytest.raises(OnyxError):
        api.update_tool_user_preferences(
            42, ToolUserPreferences(enabled_in_chat=True), db, user
        )
    db.commit.assert_not_called()


def test_update_and_catalog_preserve_admin_state_and_connection(
    monkeypatch: pytest.MonkeyPatch, preference_db: Session
) -> None:
    user = User(id=uuid4())
    tool = Tool(
        id=42,
        name="Plugin",
        openapi_schema={"paths": {}},
        enabled=True,
        passthrough_auth=False,
        oauth_config_id=12,
    )
    monkeypatch.setattr(api, "get_tool_by_id", lambda *_: tool)
    response = api.update_tool_user_preferences(
        42, ToolUserPreferences(enabled_in_chat=False), preference_db, user
    )
    snapshots = [ToolSnapshot.from_model(tool)]
    api._stamp_personal_tool_preferences(snapshots, user, preference_db)
    assert response.enabled_in_chat is False
    assert snapshots[0].user_enabled_in_chat is False
    assert tool.enabled is True
    assert tool.oauth_config_id == 12
    other_snapshots = [ToolSnapshot.from_model(tool)]
    api._stamp_personal_tool_preferences(
        other_snapshots, User(id=uuid4()), preference_db
    )
    assert other_snapshots[0].user_enabled_in_chat is True
    monkeypatch.setattr(api, "get_tools", lambda *_, **__: [tool])
    monkeypatch.setattr(api, "get_mcp_servers_accessible_to_user", lambda *_: [])
    monkeypatch.setattr(api, "get_default_chat_tool_ids", lambda *_: {42})
    catalog = api.list_tools(preference_db, user)
    assert [
        (item.id, item.default_chat_enabled, item.user_enabled_in_chat)
        for item in catalog
    ] == [(42, True, False)]
    response = api.update_tool_user_preferences(
        42, ToolUserPreferences(enabled_in_chat=True), preference_db, user
    )
    assert response.enabled_in_chat is True
    assert tool.enabled is True
    assert tool.oauth_config_id == 12
