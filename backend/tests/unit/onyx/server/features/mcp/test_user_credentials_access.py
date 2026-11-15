from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.models import MCPServer, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api
from onyx.server.features.mcp.credentials import ResolvedMCPCredentials
from onyx.server.features.mcp.models import MCPUserCredentialsRequest


@pytest.mark.parametrize(
    "auth_type", [MCPAuthenticationType.API_TOKEN, MCPAuthenticationType.OAUTH]
)
def test_inaccessible_server_denies_credentials_before_reads_writes_or_validation(
    monkeypatch: pytest.MonkeyPatch, auth_type: MCPAuthenticationType
) -> None:
    db = MagicMock(spec=Session)
    user = User(id=uuid4(), email="member@example.com")
    server = MCPServer(id=42, auth_type=auth_type)
    access = MagicMock(return_value=False)
    monkeypatch.setattr(api, "get_mcp_server_by_id", lambda *_: server)
    monkeypatch.setattr(api, "user_can_configure_mcp_credentials", access)
    credential_operations = [
        "get_mcp_auth_template",
        "get_user_connection_config",
        "extract_connection_data",
        "test_mcp_server_credentials",
        "upsert_user_connection_config",
        "resolve_mcp_credentials",
        "_hot_reload_craft_sessions",
    ]
    operations = {name: MagicMock() for name in credential_operations}
    for name, operation in operations.items():
        monkeypatch.setattr(api, name, operation)

    with pytest.raises(OnyxError) as error:
        api.save_user_credentials(
            MCPUserCredentialsRequest(
                server_id=42,
                credentials={"api_key": "personal-key"},
                transport="streamable-http",
            ),
            db,
            user,
        )

    assert error.value.error_code is OnyxErrorCode.NOT_FOUND
    access.assert_called_once_with(user, server, db)
    for operation in operations.values():
        operation.assert_not_called()
    db.commit.assert_not_called()


def test_accessible_member_saves_only_their_validated_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    user = User(id=uuid4(), email="member@example.com")
    server = MCPServer(
        id=42,
        name="Personal integration",
        server_url="https://example.com/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
    )
    access = MagicMock(return_value=True)
    validate = MagicMock(return_value=(True, "Connected"))
    save = MagicMock()
    reload = MagicMock()
    resolved = ResolvedMCPCredentials(
        connection_config_id=1,
        connection_data={"headers": {"Authorization": "Bearer personal-key"}},
        user_oauth_token=None,
        auth_type=MCPAuthenticationType.API_TOKEN,
    )
    monkeypatch.setattr(api, "get_mcp_server_by_id", lambda *_: server)
    monkeypatch.setattr(api, "user_can_configure_mcp_credentials", access)
    monkeypatch.setattr(api, "get_mcp_auth_template", lambda *_: None)
    monkeypatch.setattr(api, "test_mcp_server_credentials", validate)
    monkeypatch.setattr(api, "upsert_user_connection_config", save)
    monkeypatch.setattr(api, "resolve_mcp_credentials", lambda *_: resolved)
    monkeypatch.setattr(api, "_hot_reload_craft_sessions", reload)

    response = api.save_user_credentials(
        MCPUserCredentialsRequest(
            server_id=42,
            credentials={"api_key": "personal-key"},
            transport="streamable-http",
        ),
        db,
        user,
    )

    access.assert_called_once_with(user, server, db)
    validate.assert_called_once_with(
        "https://example.com/mcp",
        {"Authorization": "Bearer personal-key"},
        transport=MCPTransport.STREAMABLE_HTTP,
        auth=None,
    )
    save.assert_called_once_with(
        server_id=42,
        user_email="member@example.com",
        config_data={
            "headers": {"Authorization": "Bearer personal-key"},
            "header_substitutions": {"api_key": "personal-key"},
        },
        db_session=db,
    )
    db.commit.assert_called_once()
    reload.assert_called_once_with({user.id}, db)
    assert response.success is True
    assert response.authenticated is True
    assert response.validation_tested is True
    assert response.server_id == 42
