"""End-to-end proactive OAuth against the GCP-handshake MCP mock.

Requires Postgres and Redis. Starts the mock IdP and handshake MCP server on ephemeral
local ports (see ``tests/integration/mock_services/mcp_test_server/``).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import parse_qs
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport
from onyx.db.mcp import create_connection_config
from onyx.db.mcp import create_mcp_server__no_commit
from onyx.db.mcp import extract_connection_data
from onyx.db.mcp import get_user_connection_config
from onyx.server.features.mcp import api as mcp_api
from onyx.server.features.mcp.models import MCPOAuthKeys
from onyx.server.features.mcp.models import MCPUserOAuthConnectRequest
from onyx.tools.tool_implementations.mcp.mcp_client import call_mcp_tool
from onyx.tools.tool_implementations.mcp.mcp_client import discover_mcp_tools
from tests.external_dependency_unit.conftest import create_test_user
from tests.integration.mock_services.mcp_test_server.dev_oauth_constants import (
    DEV_OAUTH_CLIENT_ID,
)
from tests.integration.mock_services.mcp_test_server.dev_oauth_constants import (
    DEV_OAUTH_CLIENT_SECRET,
)

_MOCK_DIR = (
    Path(__file__).resolve().parents[2]
    / "integration"
    / "mock_services"
    / "mcp_test_server"
)
_IDP_SCRIPT = _MOCK_DIR / "mock_oauth_idp.py"
_HANDSHAKE_SCRIPT = _MOCK_DIR / "run_mcp_server_gcp_handshake.py"
_RETURN_PATH = "/app/chat"


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(
    host: str,
    port: int,
    process: subprocess.Popen[bytes],
    timeout_seconds: float = 15.0,
) -> None:
    start = time.monotonic()
    while time.monotonic() - start < timeout_seconds:
        if process.poll() is not None:
            raise RuntimeError("Mock process exited during startup")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect((host, port))
                return
            except OSError:
                time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {host}:{port}")


def _exchange_code_from_auth_url(auth_url: str) -> tuple[str, str]:
    with httpx.Client(follow_redirects=False, timeout=10.0) as client:
        response = client.get(auth_url)
        assert response.status_code in (302, 307), response.text
        location = response.headers["location"]
        query = parse_qs(urlparse(location).query)
        return query["code"][0], query["state"][0]


@pytest.fixture(scope="module")
def mcp_handshake_oauth_stack() -> Generator[dict[str, str], None, None]:
    if not _IDP_SCRIPT.exists() or not _HANDSHAKE_SCRIPT.exists():
        pytest.skip("MCP OAuth mock server scripts are missing")

    host = "127.0.0.1"
    idp_port = _pick_free_port()
    handshake_port = _pick_free_port()
    issuer = f"http://{host}:{idp_port}"
    handshake_url = f"http://{host}:{handshake_port}/mcp"
    handshake_env = os.environ.copy()
    handshake_env["DEV_OAUTH_ISSUER"] = issuer

    idp = subprocess.Popen(
        [sys.executable, str(_IDP_SCRIPT), str(idp_port)],
        cwd=_MOCK_DIR,
    )
    handshake = subprocess.Popen(
        [sys.executable, str(_HANDSHAKE_SCRIPT), str(handshake_port)],
        cwd=_MOCK_DIR,
        env=handshake_env,
    )
    try:
        _wait_for_port(host, idp_port, idp)
        _wait_for_port(host, handshake_port, handshake)
        with httpx.Client(timeout=5.0) as client:
            assert client.get(f"{issuer}/healthz").status_code == 200
            assert (
                client.get(f"http://{host}:{handshake_port}/healthz").status_code == 200
            )
        yield {"issuer": issuer, "handshake_url": handshake_url}
    finally:
        for proc in (handshake, idp):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.mark.asyncio
async def test_proactive_handshake_oauth_connect_callback_and_tool_call(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    mcp_handshake_oauth_stack: dict[str, str],
) -> None:
    """Regression: handshake without tokens still completes proactive OAuth end-to-end."""
    handshake_url = mcp_handshake_oauth_stack["handshake_url"]
    user = create_test_user(db_session, "proactive_oauth")
    admin_config_data = mcp_api._build_oauth_admin_config_data(
        client_id=DEV_OAUTH_CLIENT_ID,
        client_secret=DEV_OAUTH_CLIENT_SECRET,
    )
    mcp_server = create_mcp_server__no_commit(
        owner_email=user.email,
        name=f"Handshake OAuth {uuid4().hex[:8]}",
        description="GCP-handshake proactive OAuth regression",
        server_url=handshake_url,
        auth_type=MCPAuthenticationType.OAUTH,
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        db_session=db_session,
    )
    admin_config = create_connection_config(
        config_data=admin_config_data,
        mcp_server_id=mcp_server.id,
        user_email="",
        db_session=db_session,
    )
    mcp_server.admin_connection_config_id = admin_config.id
    db_session.commit()

    connect_request = MCPUserOAuthConnectRequest(
        server_id=mcp_server.id,
        return_path=_RETURN_PATH,
        include_resource_param=True,
        oauth_client_id=DEV_OAUTH_CLIENT_ID,
        oauth_client_secret=DEV_OAUTH_CLIENT_SECRET,
        oauth_client_id_changed=True,
        oauth_client_secret_changed=True,
    )

    first_connect = await mcp_api._connect_oauth(
        connect_request, db_session, is_admin=False, user=user
    )
    assert first_connect.oauth_url != _RETURN_PATH
    assert "code_challenge=" in first_connect.oauth_url

    code, state = _exchange_code_from_auth_url(first_connect.oauth_url)

    callback_request = MagicMock()
    callback_request.query_params = {"code": code, "state": state}
    await mcp_api.process_oauth_callback(callback_request, db_session, user=user)

    user_config = get_user_connection_config(mcp_server.id, user.email, db_session)
    assert user_config is not None
    db_session.refresh(user_config)
    config_dict = extract_connection_data(user_config, apply_mask=False)
    assert config_dict.get(MCPOAuthKeys.TOKENS.value)
    assert config_dict.get("headers", {}).get("Authorization", "").startswith("Bearer ")

    reconnect_request = MCPUserOAuthConnectRequest(
        server_id=mcp_server.id,
        return_path=_RETURN_PATH,
        include_resource_param=True,
        oauth_client_id=DEV_OAUTH_CLIENT_ID,
        oauth_client_secret=DEV_OAUTH_CLIENT_SECRET,
        oauth_client_id_changed=False,
        oauth_client_secret_changed=False,
    )
    second_connect = await mcp_api._connect_oauth(
        reconnect_request, db_session, is_admin=False, user=user
    )
    assert second_connect.oauth_url == _RETURN_PATH

    headers = config_dict.get("headers", {})
    tools = discover_mcp_tools(
        handshake_url,
        connection_headers=headers,
        transport=MCPTransport.STREAMABLE_HTTP,
    )
    tool_names = {tool.name for tool in tools}
    assert "echo" in tool_names

    result = call_mcp_tool(
        handshake_url,
        tool_name="echo",
        arguments={"message": "proactive-oauth-ok"},
        connection_headers=headers,
        transport=MCPTransport.STREAMABLE_HTTP,
    )
    assert "proactive-oauth-ok" in result
