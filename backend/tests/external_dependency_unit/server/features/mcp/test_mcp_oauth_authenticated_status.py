"""`is_authenticated` for per-user OAuth servers must reflect a completed
handshake (stored tokens), not mere connection-config row existence, since the
row is created before token exchange. API-token servers stay authenticated on
row existence alone."""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.mcp import create_connection_config
from onyx.db.models import MCPServer
from onyx.server.features.mcp.api import _db_mcp_server_to_api_mcp_server
from onyx.server.features.mcp.models import MCPConnectionData
from tests.external_dependency_unit.conftest import create_test_user


def _make_per_user_server(
    db_session: Session,
    auth_type: MCPAuthenticationType,
) -> MCPServer:
    admin_config = create_connection_config(
        config_data=MCPConnectionData(headers={}),
        db_session=db_session,
        user_email="",
    )
    db_session.flush()
    server = MCPServer(
        owner="admin@example.com",
        name=f"oauth_status_server_{uuid4().hex[:8]}",
        server_url="https://example.com/mcp",
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_type=auth_type,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        admin_connection_config_id=admin_config.id,
        is_public=True,
    )
    db_session.add(server)
    db_session.commit()
    db_session.refresh(server)
    return server


def test_oauth_tokenless_row_is_not_authenticated(db_session: Session) -> None:
    user = create_test_user(db_session, "mcp_oauth_pending")
    server = _make_per_user_server(db_session, MCPAuthenticationType.OAUTH)
    create_connection_config(
        config_data=MCPConnectionData(headers={}, client_info={"client_id": "abc"}),
        db_session=db_session,
        mcp_server_id=server.id,
        user_email=user.email,
    )
    db_session.commit()

    api_server = _db_mcp_server_to_api_mcp_server(server, db_session, request_user=user)
    assert api_server.user_authenticated is False
    assert api_server.is_authenticated is False


def test_oauth_row_with_tokens_is_authenticated(db_session: Session) -> None:
    user = create_test_user(db_session, "mcp_oauth_done")
    server = _make_per_user_server(db_session, MCPAuthenticationType.OAUTH)
    create_connection_config(
        config_data=MCPConnectionData(
            headers={"Authorization": "Bearer tok"},
            tokens={"access_token": "tok", "token_type": "Bearer"},
        ),
        db_session=db_session,
        mcp_server_id=server.id,
        user_email=user.email,
    )
    db_session.commit()

    api_server = _db_mcp_server_to_api_mcp_server(server, db_session, request_user=user)
    assert api_server.user_authenticated is True
    assert api_server.is_authenticated is True


def test_api_token_row_is_authenticated_without_tokens_key(
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "mcp_api_token")
    server = _make_per_user_server(db_session, MCPAuthenticationType.API_TOKEN)
    create_connection_config(
        config_data=MCPConnectionData(
            headers={"Authorization": "Bearer key"},
            header_substitutions={"api_key": "key"},
        ),
        db_session=db_session,
        mcp_server_id=server.id,
        user_email=user.email,
    )
    db_session.commit()

    api_server = _db_mcp_server_to_api_mcp_server(server, db_session, request_user=user)
    assert api_server.user_authenticated is True
    assert api_server.is_authenticated is True
