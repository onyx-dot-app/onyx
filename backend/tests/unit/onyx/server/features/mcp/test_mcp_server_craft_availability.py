from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import MCPServerStatus
from onyx.db.models import MCPServer, User
from onyx.server.features.mcp import api
from onyx.server.features.mcp.models import MCPServerSimpleCreateRequest


@pytest.mark.parametrize("available", [None, False, True])
def test_create_persists_craft_availability_atomically(
    monkeypatch: pytest.MonkeyPatch, available: bool | None
) -> None:
    db = MagicMock(spec=Session)
    user = User(email="admin@example.com")
    added: list[MCPServer] = []

    def add(server: MCPServer) -> None:
        server.id = 42
        server.status = MCPServerStatus.CREATED
        added.append(server)

    db.add.side_effect = add
    monkeypatch.setattr(api, "_validate_mcp_server_url", lambda *_, **__: None)
    monkeypatch.setattr(api, "_apply_mcp_server_access", lambda **_: None)
    request = MCPServerSimpleCreateRequest(
        name="Example", server_url="https://example.com/mcp"
    )
    if available is not None:
        request.available_in_craft = available

    result = api.create_mcp_server_simple(request, db, user)

    assert added[0].available_in_craft is (available is True)
    assert result.available_in_craft is (available is True)
    db.commit.assert_called_once_with()
