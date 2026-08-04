"""Backward compatibility: legacy stored templates and masked round-trips.

Stored templates predate write-time name validation, so reads must tolerate
rows the current validator would reject; masked read-back values must survive
edits that only change a header name's casing.
"""

import json

from onyx.db.enums import MCPAuthenticationPerformer, MCPAuthenticationType
from onyx.db.mcp import ResolvedMCPCredentials, get_mcp_auth_template
from onyx.db.models import MCPConnectionConfig, MCPServer
from onyx.server.features.mcp.api import _resolve_auth_template
from onyx.server.features.mcp.models import MCPAuthTemplate
from onyx.utils.sensitive import SensitiveValue


def _sensitive(config_data: dict) -> SensitiveValue[dict]:
    return SensitiveValue(
        encrypted_bytes=json.dumps(config_data).encode(),
        decrypt_fn=lambda b: b.decode(),
        is_json=True,
    )


def _server_with_admin_config(config_data: dict) -> MCPServer:
    return MCPServer(
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        admin_connection_config=MCPConnectionConfig(config=_sensitive(config_data)),
    )


def test_legacy_template_with_invalid_names_still_loads_and_sends() -> None:
    """A stored template the current validator would reject (denylisted,
    invalid, and case-duplicate names) must not fail resolution; the offending
    names are dropped and the rest of the template keeps working."""
    server = _server_with_admin_config(
        {
            "headers": {
                "Host": "internal.example.com",
                "bad name": "value",
                "X-Gateway-Key": "stale-key",
                "x-gateway-key": "literal-key",
            }
        }
    )
    template = get_mcp_auth_template(server)
    assert template is not None
    assert template.headers == {"x-gateway-key": "literal-key"}
    assert template.required_fields == []

    creds = ResolvedMCPCredentials(
        connection_config=None,
        user_oauth_token="login-token",
        auth_type=MCPAuthenticationType.PT_OAUTH,
        auth_template=template,
        user_email="user@example.com",
    )
    headers = creds.build_headers()
    assert "Host" not in headers
    assert headers["x-gateway-key"] == "literal-key"
    assert headers["Authorization"] == "Bearer login-token"


def test_legacy_template_placeholders_still_derive_required_fields() -> None:
    server = _server_with_admin_config(
        {"headers": {"Authorization": "Bearer {api_key}", "Host": "legacy"}}
    )
    template = get_mcp_auth_template(server)
    assert template is not None
    assert template.required_fields == ["api_key"]


def test_casing_only_rename_reuses_stored_masked_value() -> None:
    """Renaming only a header's casing replays the masked value; resolution
    must keep the stored value instead of rejecting the masked placeholder."""
    existing = MCPAuthTemplate(headers={"X-Gateway-Key": "stored-secret"})
    resolved = _resolve_auth_template(
        MCPAuthTemplate.model_construct(
            headers={"x-gateway-key": "••••••••••••"}, required_fields=[]
        ),
        {"x-gateway-key": False},
        existing,
    )
    assert resolved.headers == {"x-gateway-key": "stored-secret"}
