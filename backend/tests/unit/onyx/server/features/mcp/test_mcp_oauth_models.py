import pytest
from pydantic import ValidationError

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
    MCPTransport,
)
from onyx.server.features.mcp.models import (
    MCPToolCreateRequest,
    MCPUserOAuthConnectRequest,
)


def _known_provider_request(**overrides: object) -> MCPToolCreateRequest:
    values: dict[str, object] = {
        "name": "Protected MCP",
        "server_url": "https://mcp.example.com/mcp",
        "auth_type": MCPAuthenticationType.OAUTH,
        "auth_performer": MCPAuthenticationPerformer.PER_USER,
        "oauth_provider_mode": MCPOAuthProviderMode.KNOWN_PROVIDER,
        "oauth_authorization_endpoint": "https://accounts.example.com/authorize",
        "oauth_token_endpoint": "https://accounts.example.com/token",
        "transport": MCPTransport.STREAMABLE_HTTP,
    }
    values.update(overrides)
    return MCPToolCreateRequest.model_validate(values)


def test_oauth_configuration_requires_per_user_authentication() -> None:
    with pytest.raises(ValidationError, match="must be performed per user"):
        _known_provider_request(auth_performer=MCPAuthenticationPerformer.ADMIN)


@pytest.mark.parametrize(
    "reserved_parameter",
    [
        "client_id",
        "code_challenge",
        "code_challenge_method",
        "redirect_uri",
        "resource",
        "response_type",
        "scope",
        "state",
    ],
)
def test_known_provider_cannot_override_authorization_security_parameters(
    reserved_parameter: str,
) -> None:
    with pytest.raises(ValidationError, match=reserved_parameter):
        _known_provider_request(
            oauth_additional_auth_params={reserved_parameter: "attacker-controlled"}
        )


@pytest.mark.parametrize(
    "return_path",
    ["//external.example/path", "/\\external.example", "/path\nheader"],
)
def test_oauth_return_path_rejects_unsafe_navigation(return_path: str) -> None:
    with pytest.raises(ValidationError, match="safe internal path"):
        MCPUserOAuthConnectRequest(
            server_id=42,
            return_path=return_path,
            include_resource_param=True,
        )


def test_oauth_return_path_accepts_internal_path_with_query() -> None:
    request = MCPUserOAuthConnectRequest(
        server_id=42,
        return_path="/admin/actions/mcp?server_id=42&trigger_fetch=true",
        include_resource_param=True,
    )

    assert request.return_path == "/admin/actions/mcp?server_id=42&trigger_fetch=true"
