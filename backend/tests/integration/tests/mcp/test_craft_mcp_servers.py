"""Integration tests for the craft-enabled MCP server listing.

Verifies the `available_in_craft` admin toggle and that the user-facing craft
listing reflects chat-side credential state (one credential store for both
surfaces).
"""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

MCP_SERVER_HOST = os.getenv("TEST_WEB_HOSTNAME", "127.0.0.1")
# Distinct from the no-auth test's port (8010) so the suites can't collide.
MCP_SERVER_PORT = int(os.getenv("MOCK_MCP_PER_USER_SERVER_PORT", "8011"))
MCP_SERVER_URL = f"http://{MCP_SERVER_HOST}:{MCP_SERVER_PORT}/mcp"

# Keys baked into the mock server's pretend database.
ALICE_API_KEY = "mcp_live-kid_alice_001-S3cr3tAlice"
BOB_API_KEY = "mcp_live-kid_bob_001-S3cr3tBob"

MCP_SERVER_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "mock_services"
    / "mcp_test_server"
    / "run_mcp_server_per_user_key.py"
)


def _wait_for_port(
    host: str,
    port: int,
    process: subprocess.Popen[bytes],
    timeout_seconds: float = 10.0,
) -> None:
    start = time.monotonic()
    while time.monotonic() - start < timeout_seconds:
        if process.poll() is not None:
            raise RuntimeError("MCP server process exited unexpectedly during startup")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect((host, port))
                return
            except OSError:
                time.sleep(0.1)

    raise TimeoutError("Timed out waiting for MCP server to accept connections")


@pytest.fixture(scope="module")
def mcp_per_user_key_server() -> Generator[None, None, None]:
    if not MCP_SERVER_SCRIPT.exists():
        raise FileNotFoundError(
            f"Expected MCP server script at {MCP_SERVER_SCRIPT}, but it was not found"
        )

    process = subprocess.Popen(
        [sys.executable, str(MCP_SERVER_SCRIPT), str(MCP_SERVER_PORT)],
        cwd=MCP_SERVER_SCRIPT.parent,
    )

    try:
        _wait_for_port(MCP_SERVER_HOST, MCP_SERVER_PORT, process)
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _get_craft_servers(user: DATestUser) -> list[dict]:
    response = client.get(
        f"{API_SERVER_URL}/mcp/servers/craft",
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()
    return response.json()["mcp_servers"]


def test_craft_mcp_server_listing(
    mcp_per_user_key_server: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    # Admin creates a per-user API-token server (not craft-enabled yet)
    create_response = client.post(
        f"{API_SERVER_URL}/admin/mcp/servers/create",
        json={
            "name": "integration-mcp-craft",
            "description": "Integration test MCP server for craft listing",
            "server_url": MCP_SERVER_URL,
            "transport": MCPTransport.STREAMABLE_HTTP.value,
            "auth_type": MCPAuthenticationType.API_TOKEN.value,
            "auth_performer": MCPAuthenticationPerformer.PER_USER.value,
            "auth_template": {
                "headers": {"Authorization": "Bearer {api_key}"},
                "required_fields": ["api_key"],
            },
            "admin_credentials": {"api_key": ALICE_API_KEY},
            "admin_credentials_changed": {"api_key": True},
        },
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    create_response.raise_for_status()
    server_id = create_response.json()["server_id"]

    # Not craft-enabled: absent from the craft listing, flag false in the
    # regular user listing
    assert _get_craft_servers(basic_user) == []
    user_listing_response = client.get(
        f"{API_SERVER_URL}/mcp/servers",
        headers=basic_user.headers,
        cookies=basic_user.cookies,
    )
    user_listing_response.raise_for_status()
    listed = [
        server
        for server in user_listing_response.json()["mcp_servers"]
        if server["id"] == server_id
    ]
    assert len(listed) == 1
    assert listed[0]["available_in_craft"] is False

    # Admin toggles the flag on
    toggle_response = client.patch(
        f"{API_SERVER_URL}/admin/mcp/server/{server_id}",
        json={"available_in_craft": True},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    toggle_response.raise_for_status()
    assert toggle_response.json()["available_in_craft"] is True

    # Craft listing now includes the server; basic user has no credentials yet
    craft_servers = _get_craft_servers(basic_user)
    assert [server["id"] for server in craft_servers] == [server_id]
    entry = craft_servers[0]
    assert entry["available_in_craft"] is True
    assert entry["user_authenticated"] is False
    assert entry["is_authenticated"] is False

    # User connects through the chat-side credential endpoint...
    credentials_response = client.post(
        f"{API_SERVER_URL}/mcp/user-credentials",
        json={
            "server_id": server_id,
            "credentials": {"api_key": BOB_API_KEY},
            "transport": "streamable-http",
        },
        headers=basic_user.headers,
        cookies=basic_user.cookies,
    )
    credentials_response.raise_for_status()

    # ...and the craft listing reflects the chat-side auth state
    entry = _get_craft_servers(basic_user)[0]
    assert entry["user_authenticated"] is True
    assert entry["is_authenticated"] is True

    # Toggling the flag off removes the server from the craft listing
    toggle_off_response = client.patch(
        f"{API_SERVER_URL}/admin/mcp/server/{server_id}",
        json={"available_in_craft": False},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    toggle_off_response.raise_for_status()
    assert toggle_off_response.json()["available_in_craft"] is False
    assert _get_craft_servers(basic_user) == []
