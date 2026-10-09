"""A shared (admin-managed) API-token template must only be serialized in
the owner/admin auth-config response. Basic users who can merely attach the
server never supply shared credentials and must not receive the template,
which can carry literal header values alongside the `{api_key}` placeholder.
Basic users receive only the required placeholder names for per-user templates."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.mcp import (
    create_connection_config,
    get_mcp_server_by_id,
    get_user_connection_config,
)
from onyx.server.features.mcp.api import (
    _db_mcp_server_to_api_mcp_server,
    _upsert_mcp_server,
)
from onyx.server.features.mcp.credentials import get_mcp_auth_template
from onyx.server.features.mcp.models import (
    MCPAuthTemplate,
    MCPConnectionData,
    MCPToolCreateRequest,
)
from onyx.utils.encryption import is_masked_credential
from tests.external_dependency_unit.conftest import create_test_user

_LITERAL_HEADER_VALUE = "literal-secret-value"


def _create_shared_api_token_server(db_session: Session, admin_email: str) -> int:
    admin = create_test_user(db_session, admin_email, is_admin=True)
    request = MCPToolCreateRequest(
        name=f"shared-token-{uuid4().hex[:8]}",
        description="shared token server",
        server_url="http://upstream.example.com/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
        transport=MCPTransport.STREAMABLE_HTTP,
        api_token="shared-secret",
        # A second header carries a literal value alongside `{api_key}` to
        # prove literals are never surfaced to basic users.
        auth_template=MCPAuthTemplate(
            headers={
                "Authorization": "Bearer {api_key}",
                "X-Literal": _LITERAL_HEADER_VALUE,
            },
            required_fields=["api_key"],
        ),
    )
    mcp_server = _upsert_mcp_server(request, db_session, admin)
    return mcp_server.id


def test_basic_user_does_not_receive_shared_template(db_session: Session) -> None:
    server_id = _create_shared_api_token_server(db_session, "admin_shared_vis")
    basic_user = create_test_user(db_session, "basic_shared_vis")

    server = get_mcp_server_by_id(server_id, db_session)
    view = _db_mcp_server_to_api_mcp_server(server, db_session, request_user=basic_user)

    assert view.auth_template is None


def test_admin_receives_shared_template_with_auth_config(
    db_session: Session,
) -> None:
    server_id = _create_shared_api_token_server(db_session, "admin_shared_vis_owner")
    admin = create_test_user(db_session, "admin_shared_vis_viewer", is_admin=True)

    server = get_mcp_server_by_id(server_id, db_session)
    view = _db_mcp_server_to_api_mcp_server(
        server, db_session, request_user=admin, include_auth_config=True
    )

    assert view.auth_template is not None
    assert view.auth_template.headers["Authorization"] == "Bearer {api_key}"
    assert is_masked_credential(view.auth_template.headers["X-Literal"])


def test_basic_user_receives_only_per_user_placeholder_names(
    db_session: Session,
) -> None:
    admin = create_test_user(db_session, "admin_per_user_vis", is_admin=True)
    request = MCPToolCreateRequest(
        name=f"per-user-token-{uuid4().hex[:8]}",
        description="per-user token server",
        server_url="http://upstream.example.com/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_template=MCPAuthTemplate(
            headers={"Authorization": "Bearer {api_key}"},
            required_fields=["api_key"],
        ),
        admin_credentials={"api_key": "admin-key"},
    )
    mcp_server = _upsert_mcp_server(request, db_session, admin)
    basic_user = create_test_user(db_session, "basic_per_user_vis")

    server = get_mcp_server_by_id(mcp_server.id, db_session)
    view = _db_mcp_server_to_api_mcp_server(server, db_session, request_user=basic_user)

    assert view.auth_template is not None
    assert view.auth_template.headers == {}
    assert view.auth_template.required_fields == ["api_key"]


@pytest.mark.parametrize(
    "auth_type",
    [
        MCPAuthenticationType.OAUTH,
        MCPAuthenticationType.PT_OAUTH,
        MCPAuthenticationType.NONE,
    ],
)
def test_header_template_persists_for_every_auth_type(
    db_session: Session,
    auth_type: MCPAuthenticationType,
) -> None:
    admin = create_test_user(
        db_session, f"admin_cross_auth_{auth_type.value}", is_admin=True
    )
    server = _upsert_mcp_server(
        MCPToolCreateRequest(
            name=f"cross-auth-{auth_type.value}-{uuid4().hex[:8]}",
            server_url="http://upstream.example.com/mcp",
            auth_type=auth_type,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_template=MCPAuthTemplate(headers={"X-Gateway-Key": "{gateway_key}"}),
            admin_credentials={"gateway_key": "admin-gateway-key"},
        ),
        db_session,
        admin,
    )

    stored_template = get_mcp_auth_template(server)
    assert stored_template is not None
    assert stored_template.headers == {"X-Gateway-Key": "{gateway_key}"}
    assert stored_template.required_fields == ["gateway_key"]


def test_template_change_requires_users_to_reconnect(db_session: Session) -> None:
    admin = create_test_user(db_session, "admin_template_reauth", is_admin=True)
    other_user = create_test_user(db_session, "user_template_reauth")
    server = _upsert_mcp_server(
        MCPToolCreateRequest(
            name=f"template-reauth-{uuid4().hex[:8]}",
            server_url="http://upstream.example.com/mcp",
            auth_type=MCPAuthenticationType.OAUTH,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_template=MCPAuthTemplate(headers={"X-Gateway-Key": "{gateway_key}"}),
            admin_credentials={"gateway_key": "admin-key"},
        ),
        db_session,
        admin,
    )
    create_connection_config(
        config_data=MCPConnectionData(
            headers={"X-Gateway-Key": "user-key"},
            header_substitutions={"gateway_key": "user-key"},
        ),
        db_session=db_session,
        mcp_server_id=server.id,
        user_email=other_user.email,
    )
    db_session.commit()

    _upsert_mcp_server(
        MCPToolCreateRequest(
            name=server.name,
            server_url=server.server_url,
            auth_type=MCPAuthenticationType.OAUTH,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            transport=server.transport,
            auth_template=MCPAuthTemplate(
                headers={"X-New-Gateway-Key": "{gateway_key}"}
            ),
            admin_credentials={"gateway_key": "admin-key"},
            existing_server_id=server.id,
        ),
        db_session,
        admin,
    )

    assert get_user_connection_config(server.id, other_user.email, db_session) is None
    assert get_user_connection_config(server.id, admin.email, db_session) is not None
