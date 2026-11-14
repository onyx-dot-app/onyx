import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
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
    id: int
    name: str
    tool_ids: dict[str, int]

    def callable_name(self, tool_name: str) -> str:
        """The name the LLM sees for one of the server's tools."""
        return f"mcp__{self.id}__{self.name}__{tool_name}"


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
    """A connected no-auth MCP server with its tools saved. Teardown deletes
    the server with its tools, policies and approval requests."""
    name = f"integration-mcp-{uuid4().hex[:8]}"
    create_response = client.post(
        f"{API_SERVER_URL}/admin/mcp/servers/create",
        json={
            "name": name,
            "description": "Integration test MCP server",
            "server_url": NO_AUTH_MCP_SERVER_URL,
            "transport": MCPTransport.STREAMABLE_HTTP.value,
            "auth_type": MCPAuthenticationType.NONE.value,
            "auth_performer": MCPAuthenticationPerformer.ADMIN.value,
        },
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    create_response.raise_for_status()
    server_id = create_response.json()["server_id"]
    try:
        client.get(
            f"{API_SERVER_URL}/admin/mcp/server/{server_id}/tools",
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        ).raise_for_status()
        client.patch(
            f"{API_SERVER_URL}/admin/mcp/server/{server_id}/status",
            params={"status": "CONNECTED"},
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        ).raise_for_status()
        db_tools_response = client.get(
            f"{API_SERVER_URL}/admin/mcp/server/{server_id}/db-tools",
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        )
        db_tools_response.raise_for_status()
        yield ConnectedMCPServer(
            id=server_id,
            name=name,
            tool_ids={
                tool["name"]: tool["id"] for tool in db_tools_response.json()["tools"]
            },
        )
    finally:
        client.delete(
            f"{API_SERVER_URL}/admin/mcp/server/{server_id}",
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        ).raise_for_status()
