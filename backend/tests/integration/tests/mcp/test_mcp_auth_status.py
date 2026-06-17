"""Integration test for the per-user MCP re-auth status endpoint.

Verifies GET /mcp/servers/auth-status/{assistant_id}: for a PER_USER MCP server
attached to an assistant, a user with NO stored credentials is told
needs_reauth=true (never_authenticated); after the user saves credentials the
same endpoint reports needs_reauth=false. Also asserts the response is
caller-scoped — it never leaks another user's status or any token material.
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
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

# Loopback is allowed by the api_server's SSRF guard, so the mock can be
# registered as a real MCP server. Distinct port to avoid clashing with the
# Onyx MCP server (8090) and the other mock-server tests.
MOCK_HOST = os.getenv("TEST_WEB_HOSTNAME", "127.0.0.1")
MOCK_PORT = int(os.getenv("MCP_AUTH_STATUS_MOCK_PORT", "8902"))
MOCK_URL = f"http://{MOCK_HOST}:{MOCK_PORT}/mcp"

# Baked into run_mcp_server_per_user_key.py.
ADMIN_API_KEY = "mcp_live-kid_alice_001-S3cr3tAlice"
USER_API_KEY = "mcp_live-kid_bob_001-S3cr3tBob"

AUTH_TEMPLATE = {
    "headers": {"Authorization": "Bearer {api_key}"},
    "required_fields": ["api_key"],
}

MOCK_SERVER_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "mock_services"
    / "mcp_test_server"
    / "run_mcp_server_per_user_key.py"
)


def _wait_for_port(
    host: str,
    port: int,
    process: subprocess.Popen[bytes],
    timeout_seconds: float = 15.0,
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
def mcp_per_user_server() -> Generator[None, None, None]:
    if not MOCK_SERVER_SCRIPT.exists():
        raise FileNotFoundError(
            f"Mock MCP server script not found at {MOCK_SERVER_SCRIPT}"
        )
    # Fail loud if something else already owns the port, so we never register
    # the test server against a stranger's process.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex((MOCK_HOST, MOCK_PORT)) == 0:
            raise RuntimeError(
                f"Port {MOCK_PORT} already in use; set MCP_AUTH_STATUS_MOCK_PORT"
            )
    process = subprocess.Popen(
        [sys.executable, str(MOCK_SERVER_SCRIPT), str(MOCK_PORT)],
        cwd=MOCK_SERVER_SCRIPT.parent,
    )
    try:
        _wait_for_port(MOCK_HOST, MOCK_PORT, process)
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _get_auth_status(persona_id: int, user: DATestUser) -> dict:
    response = client.get(
        f"{API_SERVER_URL}/mcp/servers/auth-status/{persona_id}",
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()
    return response.json()


def test_mcp_per_user_auth_status_flow(
    mcp_per_user_server: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    # Second credential-less user, to prove caller-scoping (basic_user's saved
    # creds never leak into another user's status).
    other_user = UserManager.create(name=f"auth-status-other-{int(time.time())}")
    # a) Admin registers a PER_USER / API_TOKEN MCP server pointed at the mock.
    create_response = client.post(
        f"{API_SERVER_URL}/admin/mcp/servers/create",
        json={
            "name": f"auth-status-per-user-{int(time.time())}",
            "description": "Per-user MCP server for auth-status integration test",
            "server_url": MOCK_URL,
            "transport": MCPTransport.STREAMABLE_HTTP.value,
            "auth_type": MCPAuthenticationType.API_TOKEN.value,
            "auth_performer": MCPAuthenticationPerformer.PER_USER.value,
            "auth_template": AUTH_TEMPLATE,
            "admin_credentials": {"api_key": ADMIN_API_KEY},
            "admin_credentials_changed": {"api_key": True},
        },
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    create_response.raise_for_status()
    server_id = create_response.json()["server_id"]

    # b) Discover tools (source=mcp also flips the server to CONNECTED).
    snapshots_response = client.get(
        f"{API_SERVER_URL}/admin/mcp/server/{server_id}/tools/snapshots",
        params={"source": "mcp"},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    snapshots_response.raise_for_status()

    db_tools_response = client.get(
        f"{API_SERVER_URL}/admin/mcp/server/{server_id}/db-tools",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    db_tools_response.raise_for_status()
    whoami_tool = next(
        tool for tool in db_tools_response.json()["tools"] if tool["name"] == "whoami"
    )

    # c) Public assistant with the per-user MCP tool attached.
    persona = PersonaManager.create(
        name=f"auth-status-persona-{int(time.time())}",
        description="Persona for MCP auth-status integration test",
        tool_ids=[whoami_tool["id"]],
        is_public=True,
        user_performing_action=admin_user,
    )

    # d) basic_user has no per-user credentials yet -> never_authenticated.
    before = _get_auth_status(persona.id, basic_user)
    assert before["assistant_id"] == str(persona.id)
    statuses = before["auth_statuses"]
    assert len(statuses) == 1, statuses
    status = statuses[0]
    assert status["server_id"] == server_id
    assert status["name"] is not None
    assert status["needs_reauth"] is True
    assert status["reason"] == "never_authenticated"
    assert status["auth_performer"] == MCPAuthenticationPerformer.PER_USER.value
    assert status["auth_type"] == MCPAuthenticationType.API_TOKEN.value
    # No token material is ever surfaced through this endpoint.
    serialized = before.__repr__() + str(before)
    assert USER_API_KEY not in serialized
    assert ADMIN_API_KEY not in serialized
    assert "api_key" not in {k for s in statuses for k in s.keys()}

    # e) basic_user saves credentials -> needs_reauth flips to false.
    save_response = client.post(
        f"{API_SERVER_URL}/mcp/user-credentials",
        json={
            "server_id": server_id,
            "credentials": {"api_key": USER_API_KEY},
            "transport": MCPTransport.STREAMABLE_HTTP.value,
        },
        headers=basic_user.headers,
        cookies=basic_user.cookies,
    )
    save_response.raise_for_status()

    after = _get_auth_status(persona.id, basic_user)
    after_status = after["auth_statuses"][0]
    assert after_status["server_id"] == server_id
    assert after_status["needs_reauth"] is False
    assert after_status["reason"] is None

    # f) Caller-scoping: other_user saved nothing, so it must still see
    #    never_authenticated — basic_user's freshly-saved creds never leak across.
    other = _get_auth_status(persona.id, other_user)
    other_status = other["auth_statuses"][0]
    assert other_status["server_id"] == server_id
    assert other_status["needs_reauth"] is True
    assert other_status["reason"] == "never_authenticated"
