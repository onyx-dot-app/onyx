import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from onyx.db.enums import MCPTransport
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

# The client tests do not use the Onyx MCP server, so the mock keeps its own
# port (MOCK_MCP_SERVER_PORT, default 8010) instead of 8090.
NO_AUTH_MCP_SERVER_HOST = os.getenv("TEST_WEB_HOSTNAME", "127.0.0.1")
NO_AUTH_MCP_SERVER_PORT = int(os.getenv("MOCK_MCP_SERVER_PORT", "8010"))
NO_AUTH_MCP_SERVER_URL = (
    f"http://{NO_AUTH_MCP_SERVER_HOST}:{NO_AUTH_MCP_SERVER_PORT}/mcp"
)
NO_AUTH_MCP_SERVER_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "mock_services"
    / "mcp_test_server"
    / "run_mcp_server_no_auth.py"
)


class ConnectedMCPServer(BaseModel):
    name: str
    # The integration of the server and the plugin that holds it.
    integration_id: int
    plugin_id: UUID

    def callable_name(self, tool_name: str) -> str:
        """The name the LLM sees for one of the server's tools."""
        return f"mcp__{self.integration_id}__{self.name}__{tool_name}"


@pytest.fixture(scope="session")
def mcp_no_auth_server() -> Generator[None, None, None]:
    """Run the no-auth mock MCP server for the session's tests."""
    if not NO_AUTH_MCP_SERVER_SCRIPT.exists():
        raise FileNotFoundError(
            f"Expected MCP server script at {NO_AUTH_MCP_SERVER_SCRIPT}, but it was not found"
        )
    process = subprocess.Popen(
        [sys.executable, str(NO_AUTH_MCP_SERVER_SCRIPT), str(NO_AUTH_MCP_SERVER_PORT)],
        cwd=NO_AUTH_MCP_SERVER_SCRIPT.parent,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                raise RuntimeError(
                    "MCP server process exited unexpectedly during startup"
                )
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                if (
                    sock.connect_ex((NO_AUTH_MCP_SERVER_HOST, NO_AUTH_MCP_SERVER_PORT))
                    == 0
                ):
                    break
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "Timed out waiting for MCP server to accept connections"
                )
            time.sleep(0.1)
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture
def connected_mcp_server(
    mcp_no_auth_server: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> Generator[ConnectedMCPServer, None, None]:
    """A no-auth MCP integration for the organization, with its tools
    discovered at create. Teardown deletes it and its plugin."""
    name = f"integration-mcp-{uuid4().hex[:8]}"
    create_response = client.post(
        f"{API_SERVER_URL}/admin/integrations",
        json={
            "for_organization": True,
            "name": name,
            "description": "Integration test MCP server",
            "auth_mode": "none",
            "auth_method": None,
            "config": {
                "shape": "mcp_server",
                "server_url": NO_AUTH_MCP_SERVER_URL,
                "transport": MCPTransport.STREAMABLE_HTTP.value,
            },
        },
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    create_response.raise_for_status()
    detail = create_response.json()
    integration_id = detail["id"]
    try:
        if detail["action_count"] == 0:
            client.post(
                f"{API_SERVER_URL}/admin/integrations/{integration_id}/actions/refresh",
                headers=admin_user.headers,
                cookies=admin_user.cookies,
            ).raise_for_status()
        yield ConnectedMCPServer(
            name=name,
            integration_id=integration_id,
            plugin_id=UUID(detail["plugins"][0]["plugin_id"]),
        )
    finally:
        client.delete(
            f"{API_SERVER_URL}/admin/integrations/{integration_id}",
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        ).raise_for_status()
