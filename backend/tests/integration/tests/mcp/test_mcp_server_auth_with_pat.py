"""Integration tests for MCP Server Phase 1 - HTTP + PAT Auth."""

import requests

from tests.integration.common_utils.constants import MCP_SERVER_URL
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.test_models import DATestUser


def test_mcp_server_health_check(reset: None) -> None:
    """Test MCP server health check endpoint."""
    response = requests.get(f"{MCP_SERVER_URL}/health", timeout=10)
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["service"] == "mcp_server"


def test_mcp_server_auth_missing_pat(reset: None) -> None:
    """Test MCP server rejects requests without PAT."""
    response = requests.post(f"{MCP_SERVER_URL}/")
    assert response.status_code == 401
    assert "Missing Personal Access Token" in response.json()["detail"]


def test_mcp_server_auth_invalid_pat(reset: None) -> None:
    """Test MCP server rejects requests with invalid PAT."""
    response = requests.post(
        f"{MCP_SERVER_URL}/",
        headers={"Authorization": "Bearer onyx_pat_invalid123"},
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
    )
    assert response.status_code == 401
    assert "Invalid or expired token" in response.json()["detail"]


def test_mcp_server_auth_valid_pat(reset: None, admin_user: DATestUser) -> None:
    """Test MCP server accepts requests with valid PAT."""
    # Create PAT via API
    pat_data = PATManager.create(
        name="Test MCP Token",
        expiration_days=7,
        user_performing_action=admin_user,
    )
    pat_token = pat_data["token"]

    # Test connection with MCP protocol request
    response = requests.post(
        f"{MCP_SERVER_URL}/",
        headers={
            "Authorization": f"Bearer {pat_token}",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
        },
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
    )

    # Should be authenticated (may return MCP protocol response or error)
    # 200 = valid MCP protocol response
    # 400 = valid protocol error (authenticated but bad request)
    assert response.status_code in [200, 400]
