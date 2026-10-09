"""A Notion connector set to permission sync must fail validation until a
per-user OAuth Notion MCP server is registered, since the query-time censor
has nothing to fetch pages with otherwise."""

from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.connectors.perm_sync_valid import validate_perm_sync
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.notion.connector import NotionConnector
from onyx.db.enums import MCPAuthenticationPerformer, MCPAuthenticationType

_MODULE = "ee.onyx.connectors.perm_sync_valid"


def _server(
    url: str = "https://mcp.notion.com/mcp",
    auth_type: MCPAuthenticationType = MCPAuthenticationType.OAUTH,
    performer: MCPAuthenticationPerformer = MCPAuthenticationPerformer.PER_USER,
) -> MagicMock:
    server: MagicMock = MagicMock()
    server.server_url = url
    server.auth_type = auth_type
    server.auth_performer = performer
    return server


def _validate(servers: list[MagicMock]) -> None:
    with (
        patch(f"{_MODULE}.get_session_with_current_tenant"),
        patch(f"{_MODULE}.get_all_mcp_servers", return_value=servers),
    ):
        validate_perm_sync(MagicMock(spec=NotionConnector))


def test_passes_with_a_per_user_notion_mcp_server() -> None:
    _validate([_server(url="https://mcp.example.com/mcp"), _server()])


@pytest.mark.parametrize(
    "servers",
    [
        [],
        [_server(url="https://mcp.example.com/mcp")],
        [_server(performer=MCPAuthenticationPerformer.ADMIN)],
        [_server(auth_type=MCPAuthenticationType.API_TOKEN)],
    ],
    ids=["none", "other host", "admin level", "api token"],
)
def test_fails_without_a_per_user_notion_mcp_server(servers: list[MagicMock]) -> None:
    with pytest.raises(ConnectorValidationError, match="mcp.notion.com"):
        _validate(servers)
