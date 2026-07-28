"""A shared (admin-managed) API-token template must only be serialized in
the owner/admin auth-config response. Basic users who can merely attach the
server never supply shared credentials and must not receive the template,
which can carry literal header values alongside the `{api_key}` placeholder.
Per-user templates stay visible to basic users because they drive the
per-user credential prompt."""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.mcp import get_mcp_server_by_id
from onyx.server.features.mcp.api import (
    _db_mcp_server_to_api_mcp_server,
    _upsert_mcp_server,
)
from onyx.server.features.mcp.models import (
    MCPAuthTemplate,
    MCPToolCreateRequest,
)
from tests.external_dependency_unit.conftest import create_test_user

_LITERAL_HEADER_VALUE = "literal-secret-value"


def _create_shared_api_token_server(db_session: Session, admin_email: str) -> int:
    admin = create_test_user(db_session, admin_email, role=UserRole.ADMIN)
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
    admin = create_test_user(db_session, "admin_shared_vis_viewer", role=UserRole.ADMIN)

    server = get_mcp_server_by_id(server_id, db_session)
    view = _db_mcp_server_to_api_mcp_server(
        server, db_session, request_user=admin, include_auth_config=True
    )

    assert view.auth_template is not None
    assert view.auth_template.headers == {
        "Authorization": "Bearer {api_key}",
        "X-Literal": _LITERAL_HEADER_VALUE,
    }


def test_basic_user_still_receives_per_user_template(db_session: Session) -> None:
    """Guard against over-restricting: per-user templates must remain visible
    to basic users so the credential prompt can render."""
    admin = create_test_user(db_session, "admin_per_user_vis", role=UserRole.ADMIN)
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
    assert view.auth_template.headers == {"Authorization": "Bearer {api_key}"}
