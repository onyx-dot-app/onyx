"""Integration test for the persisted runtime-401 ("recent_failure") signal.

Verifies that GET /mcp/servers/auth-status/{assistant_id} reports
needs_reauth=true with reason="recent_failure" once a runtime 401 has been
persisted against a PER_USER MCP server's per-user connection config (via the
db helper the tool path uses), that the signal SURVIVES a re-query (simulated
page reload), and that a subsequent successful credential save clears it
(needs_reauth=false again).

This complements test_mcp_auth_status.py, which covers the purely-derived
never_authenticated / (cleared) cases; recent_failure is the case those derived
checks can't see — a token that was valid but died mid-session.
"""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport
from onyx.db.mcp import get_user_connection_config
from onyx.db.mcp import record_user_connection_auth_failure
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

MOCK_HOST = os.getenv("TEST_WEB_HOSTNAME", "127.0.0.1")
MOCK_PORT = int(os.getenv("MCP_RECENT_FAILURE_MOCK_PORT", "8903"))
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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex((MOCK_HOST, MOCK_PORT)) == 0:
            raise RuntimeError(
                f"Port {MOCK_PORT} already in use; set MCP_RECENT_FAILURE_MOCK_PORT"
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


def _save_credentials(server_id: int, user: DATestUser) -> None:
    response = client.post(
        f"{API_SERVER_URL}/mcp/user-credentials",
        json={
            "server_id": server_id,
            "credentials": {"api_key": USER_API_KEY},
            "transport": MCPTransport.STREAMABLE_HTTP.value,
        },
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()


def test_mcp_recent_failure_persists_and_clears(
    mcp_per_user_server: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    # a) Admin registers a PER_USER / API_TOKEN MCP server pointed at the mock.
    create_response = client.post(
        f"{API_SERVER_URL}/admin/mcp/servers/create",
        json={
            "name": f"recent-failure-per-user-{int(time.time())}",
            "description": "Per-user MCP server for recent-failure integration test",
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
        name=f"recent-failure-persona-{int(time.time())}",
        description="Persona for MCP recent-failure integration test",
        tool_ids=[whoami_tool["id"]],
        is_public=True,
        user_performing_action=admin_user,
    )

    # d) basic_user saves credentials -> needs_reauth=false (the valid-token
    #    starting state, which recent_failure later contradicts).
    _save_credentials(server_id, basic_user)
    valid = _get_auth_status(persona.id, basic_user)
    assert valid["auth_statuses"][0]["needs_reauth"] is False

    # e) Simulate a runtime 401: stamp the per-user config via the db helper the
    #    tool path uses. The endpoint must now report recent_failure.
    with get_session_with_current_tenant() as db_session:
        user_config = get_user_connection_config(
            server_id, basic_user.email, db_session
        )
        assert user_config is not None
        record_user_connection_auth_failure(user_config.id, db_session)
        db_session.commit()

    after_failure = _get_auth_status(persona.id, basic_user)
    failure_status = after_failure["auth_statuses"][0]
    assert failure_status["server_id"] == server_id
    assert failure_status["needs_reauth"] is True
    assert failure_status["reason"] == "recent_failure"

    # f) Survives a re-query (simulated page reload): still recent_failure.
    reloaded = _get_auth_status(persona.id, basic_user)
    reloaded_status = reloaded["auth_statuses"][0]
    assert reloaded_status["needs_reauth"] is True
    assert reloaded_status["reason"] == "recent_failure"

    # g) basic_user re-authenticates (credential save) -> marker cleared.
    _save_credentials(server_id, basic_user)
    cleared = _get_auth_status(persona.id, basic_user)
    cleared_status = cleared["auth_statuses"][0]
    assert cleared_status["needs_reauth"] is False
    assert cleared_status["reason"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-xv"])
