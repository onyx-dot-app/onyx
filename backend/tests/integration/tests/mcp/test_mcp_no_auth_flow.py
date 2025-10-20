import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path

import pytest
import requests

from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

MCP_SERVER_HOST = os.getenv("TEST_WEB_HOSTNAME", "127.0.0.1")
MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8010"))
MCP_SERVER_URL = f"http://{MCP_SERVER_HOST}:{MCP_SERVER_PORT}/mcp"
MCP_HELLO_TOOL = "hello"

MCP_SERVER_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "mock_services"
    / "mcp_test_server"
    / "run_mcp_server_no_auth.py"
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
def mcp_no_auth_server() -> Generator[None, None, None]:
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


@pytest.fixture(scope="module", autouse=True)
def ensure_mcp_server_exists() -> None:
    if not MCP_SERVER_SCRIPT.exists():
        raise FileNotFoundError(
            f"Expected MCP server script at {MCP_SERVER_SCRIPT}, but it was not found"
        )


def test_mcp_no_auth_flow(
    mcp_no_auth_server: None,
    reset: None,
    admin_user: DATestUser,
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    # Step a) Create a no-auth MCP server via the admin API
    create_response = requests.post(
        f"{API_SERVER_URL}/admin/mcp/servers/create",
        json={
            "name": "integration-mcp-no-auth",
            "description": "Integration test MCP server",
            "server_url": MCP_SERVER_URL,
            "transport": MCPTransport.STREAMABLE_HTTP.value,
            "auth_type": MCPAuthenticationType.NONE.value,
            "auth_performer": MCPAuthenticationPerformer.ADMIN.value,
        },
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    create_response.raise_for_status()
    server_id = create_response.json()["server_id"]

    # Step b) list the server's tools
    tools_response = requests.get(
        f"{API_SERVER_URL}/admin/mcp/server/{server_id}/tools",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    tools_response.raise_for_status()
    tool_entries = tools_response.json()["tools"]
    assert len(tool_entries) == 101

    # Step c) Attach the "hello" tool from the MCP server
    update_response = requests.post(
        f"{API_SERVER_URL}/admin/mcp/servers/update",
        json={
            "server_id": server_id,
            "selected_tools": [MCP_HELLO_TOOL],
        },
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    update_response.raise_for_status()
    assert update_response.json()["updated_tools"] == 1

    tools_response = requests.get(
        f"{API_SERVER_URL}/admin/mcp/server/{server_id}/db-tools",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    tools_response.raise_for_status()
    tool_entries = tools_response.json()["tools"]
    hello_tool_entry = next(
        tool for tool in tool_entries if tool["name"] == MCP_HELLO_TOOL
    )
    tool_id = hello_tool_entry["id"]

    # Step c) Create an assistant (persona) with the MCP tool attached
    persona = PersonaManager.create(
        name="integration-mcp-persona",
        description="Persona for MCP integration test",
        tool_ids=[tool_id],
        user_performing_action=admin_user,
    )
    persona_tools_response = requests.get(
        f"{API_SERVER_URL}/persona",
        headers=basic_user.headers,
        cookies=basic_user.cookies,
    )
    persona_tools_response.raise_for_status()
    persona_entries = persona_tools_response.json()
    persona_entry = next(
        entry for entry in persona_entries if entry["id"] == persona.id
    )
    persona_tool_ids = {tool["id"] for tool in persona_entry["tools"]}
    assert tool_id in persona_tool_ids
