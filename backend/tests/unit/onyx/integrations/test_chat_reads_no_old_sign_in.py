"""Chat and tool construction read sign-in, access and approval data only from
the integration tables. This test fails when their code reads an old column
or calls an old resolver again."""

import re
from pathlib import Path

from onyx.tools.models import ToolConfiguration

BACKEND = Path(__file__).resolve().parents[4]
SCANNED = [
    BACKEND / "onyx" / "tools",
    BACKEND / "onyx" / "chat",
    BACKEND / "onyx" / "integrations" / "chat_tools.py",
    BACKEND / "onyx" / "integrations" / "call_credentials.py",
    BACKEND / "onyx" / "integrations" / "policy.py",
]
# Attribute reads of old sign-in columns, and the old resolvers and tables.
FORBIDDEN = re.compile(
    r"\.(custom_headers|passthrough_auth|oauth_config_id|admin_connection_config"
    r"|live_oauth_token)\b"
    r"|\b(resolve_mcp_credentials|ToolUserPreference|MCPServerUserPreference"
    r"|user_can_access_mcp_server|resolve_user_action_policies"
    r"|current_action_policy|OAuthTokenManager|get_tool_user_preferences"
    r"|get_mcp_server_user_preferences|ResolvedMCPCredentials"
    r"|refresh_mcp_oauth_token_if_expired|make_oauth_provider)\b"
)


def _python_files() -> list[Path]:
    files: list[Path] = []
    for path in SCANNED:
        files.extend([path] if path.is_file() else sorted(path.rglob("*.py")))
    return files


def test_chat_code_reads_no_old_sign_in_column() -> None:
    files = _python_files()
    assert files
    hits = [
        f"{path.relative_to(BACKEND)}:{number}: {line.strip()}"
        for path in files
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if FORBIDDEN.search(line)
    ]
    assert hits == []


def test_captured_tools_hold_no_sign_in_fields() -> None:
    assert not {
        "custom_headers",
        "passthrough_auth",
        "oauth_config_id",
        "mcp_server_id",
        "openapi_schema",
    } & set(ToolConfiguration.model_fields)
