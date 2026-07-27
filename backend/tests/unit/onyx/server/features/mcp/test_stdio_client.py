import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from onyx.auth.schemas import UserRole
from onyx.db.enums import MCPTransport
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api as mcp_api
from onyx.server.features.mcp.api import _ensure_stdio_admin, _resolve_stdio_env
from onyx.server.features.mcp.client import call_mcp_tool, discover_mcp_tools
from onyx.server.features.mcp.models import MCPStdioServerConfig
from onyx.utils.encryption import mask_string

_TEST_SERVER = Path(__file__).with_name("stdio_test_server.py")


def test_stdio_transport_discovers_and_calls_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONYX_UNRELATED_SECRET", "must-not-leak")
    config = MCPStdioServerConfig(
        command=sys.executable,
        args=[str(_TEST_SERVER)],
        env={"ONYX_STDIO_TEST_VALUE": "configured-secret"},
    )

    tools = discover_mcp_tools(
        "",
        transport=MCPTransport.STDIO,
        stdio_config=config,
    )
    assert {tool.name for tool in tools} == {
        "read_configured_value",
        "read_unrelated_secret",
    }

    result = call_mcp_tool(
        "",
        "read_configured_value",
        {},
        transport=MCPTransport.STDIO,
        stdio_config=config,
    )
    assert result == "configured-secret"

    unrelated = call_mcp_tool(
        "",
        "read_unrelated_secret",
        {},
        transport=MCPTransport.STDIO,
        stdio_config=config,
    )
    assert unrelated == "not-inherited"


def test_stdio_transport_requires_process_configuration() -> None:
    with pytest.raises(
        ValueError, match="stdio transport requires process configuration"
    ):
        discover_mcp_tools("", transport=MCPTransport.STDIO)


def test_stdio_configuration_requires_deployment_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_api, "MCP_STDIO_ENABLED", False)
    admin = cast(User, SimpleNamespace(role=UserRole.ADMIN))

    with pytest.raises(OnyxError, match="disabled for this deployment"):
        _ensure_stdio_admin(admin)


def test_stdio_configuration_requires_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_api, "MCP_STDIO_ENABLED", True)
    basic_user = cast(User, SimpleNamespace(role=UserRole.BASIC))

    with pytest.raises(OnyxError, match="Only Onyx admins"):
        _ensure_stdio_admin(basic_user)


def test_stdio_env_edit_preserves_masked_values_and_removes_omitted_keys() -> None:
    existing = {
        "WORDPRESS_TOKEN": "a-long-existing-wordpress-token",
        "REMOVED_VALUE": "remove-me",
    }

    assert _resolve_stdio_env(
        {
            "WORDPRESS_TOKEN": mask_string(existing["WORDPRESS_TOKEN"]),
            "SITE_URL": "https://example.com",
        },
        existing,
    ) == {
        "WORDPRESS_TOKEN": existing["WORDPRESS_TOKEN"],
        "SITE_URL": "https://example.com",
    }


def test_stdio_env_edit_rejects_unknown_masked_value() -> None:
    with pytest.raises(OnyxError, match="has no stored value"):
        _resolve_stdio_env({"UNKNOWN": "••••••••••••"}, {})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("command", "\x00bad"),
        ("args", ["safe", "bad\x00"]),
        ("env", {"INVALID-NAME": "value"}),
        ("env", {"VALID_NAME": "bad\x00"}),
    ],
)
def test_stdio_config_rejects_unsafe_process_values(
    field: str, value: str | list[str] | dict[str, str]
) -> None:
    kwargs: dict[str, object] = {
        "command": sys.executable,
        "args": [],
        "env": {},
    }
    kwargs[field] = value

    with pytest.raises(ValidationError):
        MCPStdioServerConfig.model_validate(kwargs)
