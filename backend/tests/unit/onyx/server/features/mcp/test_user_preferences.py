from collections.abc import Generator
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, Integer, MetaData, Table, Uuid, create_engine
from sqlalchemy.orm import Session

from onyx.db.mcp import (
    get_mcp_server_user_preferences,
    upsert_mcp_server_user_preferences__no_commit,
)
from onyx.db.models import MCPServer, MCPServerUserPreference, User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api
from onyx.server.features.mcp.models import (
    MCPConnectionStatus,
    MCPUserPreferencesUpdateRequest,
)


@pytest.fixture
def preference_db() -> Generator[Session, None, None]:
    metadata = MetaData()
    Table("user", metadata, Column("id", Uuid, primary_key=True))
    Table("mcp_server", metadata, Column("id", Integer, primary_key=True))
    cast(Table, MCPServerUserPreference.__table__).to_metadata(metadata)
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_partial_updates_preserve_other_surface_and_user(
    preference_db: Session,
) -> None:
    user_id, other_user_id = uuid4(), uuid4()
    assert get_mcp_server_user_preferences([42], user_id, preference_db) == {}
    first = upsert_mcp_server_user_preferences__no_commit(
        42, user_id, preference_db, enabled_in_chat=False
    )
    assert (first.enabled_in_chat, first.enabled_in_craft) == (False, True)
    updated = upsert_mcp_server_user_preferences__no_commit(
        42, user_id, preference_db, enabled_in_craft=False
    )
    assert (updated.enabled_in_chat, updated.enabled_in_craft) == (False, False)
    updated = upsert_mcp_server_user_preferences__no_commit(
        42, user_id, preference_db, enabled_in_chat=True
    )
    assert (updated.enabled_in_chat, updated.enabled_in_craft) == (True, False)
    assert get_mcp_server_user_preferences([42], other_user_id, preference_db) == {}
    other = upsert_mcp_server_user_preferences__no_commit(
        42, other_user_id, preference_db, enabled_in_craft=True
    )
    assert (other.enabled_in_chat, other.enabled_in_craft) == (True, True)
    assert get_mcp_server_user_preferences([43], user_id, preference_db) == {}


@pytest.mark.parametrize(
    "payload", [{}, {"enabled_in_chat": None}, {"enabled_in_craft": None}]
)
def test_update_requires_boolean_preference(payload: dict[str, None]) -> None:
    with pytest.raises(ValidationError):
        MCPUserPreferencesUpdateRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("accessible", "chat_available", "craft_available", "payload"),
    [
        (False, True, True, {"enabled_in_chat": False}),
        (True, False, True, {"enabled_in_chat": True}),
        (True, True, False, {"enabled_in_craft": True}),
    ],
)
def test_update_cannot_exceed_access_or_admin_availability(
    monkeypatch: pytest.MonkeyPatch,
    accessible: bool,
    chat_available: bool,
    craft_available: bool,
    payload: dict[str, bool],
) -> None:
    db = MagicMock(spec=Session)
    monkeypatch.setattr(api, "user_can_access_mcp_server", lambda *_: accessible)
    monkeypatch.setattr(
        api,
        "get_mcp_server_by_id",
        lambda *_: MCPServer(id=42, available_in_craft=craft_available),
    )
    monkeypatch.setattr(
        api,
        "get_default_chat_mcp_server_ids",
        lambda *_: {42} if chat_available else set(),
    )
    write = MagicMock()
    monkeypatch.setattr(api, "upsert_mcp_server_user_preferences__no_commit", write)
    with pytest.raises(OnyxError):
        api.update_mcp_user_preferences(
            42, MCPUserPreferencesUpdateRequest(**payload), db, User(id=uuid4())
        )
    write.assert_not_called()
    db.commit.assert_not_called()


def test_update_preserves_credentials_and_restamps_only_current_user(
    monkeypatch: pytest.MonkeyPatch,
    preference_db: Session,
) -> None:
    user = User(id=uuid4())
    monkeypatch.setattr(api, "user_can_access_mcp_server", lambda *_: True)
    monkeypatch.setattr(
        api,
        "get_mcp_server_by_id",
        lambda *_: MCPServer(id=42, available_in_craft=True),
    )
    restamp = MagicMock()
    delete_credentials = MagicMock()
    monkeypatch.setattr(api, "_hot_reload_craft_sessions", restamp)
    monkeypatch.setattr(
        api, "delete_user_connection_configs_for_server", delete_credentials
    )
    response = api.update_mcp_user_preferences(
        42, MCPUserPreferencesUpdateRequest(enabled_in_craft=False), preference_db, user
    )
    assert response.model_dump() == {"enabled_in_chat": True, "enabled_in_craft": False}
    restamp.assert_called_once_with({user.id}, preference_db)
    delete_credentials.assert_not_called()


def test_member_catalog_retains_personal_disabled_servers(
    monkeypatch: pytest.MonkeyPatch,
    preference_db: Session,
) -> None:
    from onyx.db.enums import MCPServerStatus
    from onyx.server.features.mcp.models import MCPServer as MCPServerResponse

    user = User(id=uuid4())
    upsert_mcp_server_user_preferences__no_commit(
        42, user.id, preference_db, enabled_in_chat=False, enabled_in_craft=False
    )
    monkeypatch.setattr(
        api,
        "get_mcp_servers_accessible_to_user",
        lambda *_: [MCPServer(id=42), MCPServer(id=43)],
    )
    monkeypatch.setattr(api, "get_default_chat_mcp_server_ids", lambda *_: {42, 43})
    monkeypatch.setattr(
        api,
        "_db_mcp_server_to_api_mcp_server",
        lambda server, *_, **__: MCPServerResponse(
            id=server.id,
            name="Server",
            owner="admin",
            server_url="https://example.com",
            status=MCPServerStatus.CREATED,
            connection_status=MCPConnectionStatus.NOT_CONNECTED,
        ),
    )
    response = api.get_mcp_servers_for_user(preference_db, user)
    assert [
        (s.id, s.default_chat_enabled, s.user_enabled_in_chat, s.user_enabled_in_craft)
        for s in response.mcp_servers
    ] == [(42, True, False, False), (43, True, True, True)]
