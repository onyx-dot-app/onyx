import pytest

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.server.features.mcp.api import (
    _build_shared_api_token_config_data,
    _resolve_shared_api_token,
    _resolve_shared_api_token_template,
)
from onyx.server.features.mcp.models import (
    MCPAuthTemplate,
    MCPConnectionData,
    MCPToolCreateRequest,
)


def _shared_request(
    auth_template: MCPAuthTemplate | None = None,
) -> MCPToolCreateRequest:
    return MCPToolCreateRequest(
        name="Semrush",
        description="Shared API-token MCP server",
        server_url="https://mcp.semrush.com/v2/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
        api_token="shared-secret",
        auth_template=auth_template,
        transport=MCPTransport.STREAMABLE_HTTP,
    )


def test_shared_api_token_template_renders_and_persists_template() -> None:
    template = MCPAuthTemplate(
        headers={"Authorization": "Apikey {api_key}"},
        required_fields=["api_key"],
    )

    config_data = _build_shared_api_token_config_data(
        api_token="shared-secret",
        auth_template=template,
        user_email="admin@example.com",
    )

    assert config_data["headers"] == {"Authorization": "Apikey shared-secret"}
    assert config_data["header_template"] == {"Authorization": "Apikey {api_key}"}
    assert config_data["api_token"] == "shared-secret"


def test_shared_api_token_template_defaults_to_bearer() -> None:
    request = _shared_request()

    assert request.auth_template is None

    config_data = _build_shared_api_token_config_data(
        api_token="shared-secret",
        auth_template=request.auth_template,
        user_email="admin@example.com",
    )

    assert config_data["headers"] == {"Authorization": "Bearer shared-secret"}


def test_shared_api_token_template_rejects_non_api_key_placeholders() -> None:
    with pytest.raises(ValueError, match=r"only support the \{api_key\}"):
        _shared_request(
            MCPAuthTemplate(
                headers={"Authorization": "Apikey {user_email}"},
                required_fields=[],
            )
        )


def test_shared_api_token_template_rejects_crlf_in_header_name() -> None:
    with pytest.raises(ValueError, match="invalid header name"):
        _shared_request(
            MCPAuthTemplate(
                headers={"X-API-Key\r\nInjected": "{api_key}"},
                required_fields=[],
            )
        )


def test_shared_api_token_update_reuses_existing_token() -> None:
    existing = MCPConnectionData(
        headers={"Authorization": "Bearer shared-secret"},
    )

    token = _resolve_shared_api_token(
        request_api_token="••••••••••••",
        request_api_token_changed=False,
        existing_config=existing,
    )

    assert token == "shared-secret"


def test_shared_api_token_prefers_new_token_during_auth_mode_conversion() -> None:
    existing = MCPConnectionData(
        headers={},
        client_info={"client_id": "oauth-client"},
    )

    token = _resolve_shared_api_token(
        request_api_token="new-shared-secret",
        request_api_token_changed=False,
        existing_config=existing,
    )

    assert token == "new-shared-secret"


def test_shared_api_token_template_update_preserves_omitted_template() -> None:
    existing = MCPConnectionData(
        headers={"X-API-Key": "shared-secret"},
        header_template={"X-API-Key": "{api_key}"},
        api_token="shared-secret",
    )

    template = _resolve_shared_api_token_template(
        request_template=None,
        existing_config=existing,
    )

    assert template is not None
    assert template.headers == {"X-API-Key": "{api_key}"}
