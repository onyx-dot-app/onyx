"""Integration tests for MCP Server auth delegated to API /me."""

import requests

from tests.integration.common_utils.constants import MCP_SERVER_URL
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.test_models import DATestUser


STREAMABLE_HTTP_URL = f"{MCP_SERVER_URL.rstrip('/')}/?transportType=streamable-http"


def test_mcp_server_health_check(reset: None) -> None:
    """Test MCP server health check endpoint."""
    response = requests.get(f"{MCP_SERVER_URL}/health", timeout=10)
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["service"] == "mcp_server"


def test_mcp_server_auth_missing_token(reset: None) -> None:
    """Test MCP server rejects requests without credentials."""
    response = requests.post(STREAMABLE_HTTP_URL)
    assert response.status_code == 401


def test_mcp_server_auth_invalid_token(reset: None) -> None:
    """Test MCP server rejects requests with an invalid bearer token."""
    response = requests.post(
        STREAMABLE_HTTP_URL,
        headers={"Authorization": "Bearer invalid-token"},
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
    )
    assert response.status_code == 401


def test_mcp_server_auth_valid_token(reset: None, admin_user: DATestUser) -> None:
    """Test MCP server accepts requests with a valid bearer token."""
    token_data = PATManager.create(
        name="Test MCP Token",
        expiration_days=7,
        user_performing_action=admin_user,
    )
    access_token = token_data["token"]

    # Test connection with MCP protocol request
    response = requests.post(
        STREAMABLE_HTTP_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
        },
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
    )

    # Should be authenticated (may return MCP protocol response or error)
    # 200 = valid MCP protocol response
    # 400 = valid protocol error (authenticated but bad request)
    assert response.status_code in [200, 400]
