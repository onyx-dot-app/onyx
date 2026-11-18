"""The one credential check for a chat call of an integration action."""

from collections.abc import Mapping
from datetime import datetime, timezone
from uuid import UUID

from mcp.client.auth import OAuthClientProvider
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    MCPTransport,
)
from onyx.db.integration import get_integration_by_id, get_mcp_server_for_integration
from onyx.db.integration_connection import (
    get_connection_by_id,
    get_oauth_client,
    mark_connection_needs_reconnect__no_commit,
)
from onyx.db.models import Integration, IntegrationConnection, User
from onyx.db.users import fetch_user_by_id
from onyx.integrations.connection_models import (
    SIGN_IN_REJECTED_REASON,
    ConnectionState,
    connection_secret_fingerprint,
)
from onyx.integrations.connections import (
    REFRESH_SKEW,
    ConnectionProblem,
    MissingHeaderValueError,
    has_placeholder,
    render_headers,
    resolve_connection,
)
from onyx.integrations.models import CallCredentials
from onyx.server.features.mcp.models import MCPServerConnection, merge_mcp_headers
from onyx.server.features.mcp.oauth import (
    IntegrationTokenStorage,
    integration_mcp_server_connection,
    make_integration_oauth_provider,
)

# Sign-in methods whose credential is a bearer token.
_TOKEN_METHODS = frozenset(
    {IntegrationAuthMethod.OAUTH2, IntegrationAuthMethod.ONYX_LOGIN}
)


def _fills_authorization(header_template: Mapping[str, str] | None) -> bool:
    """Whether the template fills Authorization from a placeholder, such as
    ``token {access_token}``."""
    return any(
        name.lower() == "authorization" and has_placeholder(value)
        for name, value in (header_template or {}).items()
    )


def resolve_call_credentials(
    integration: Integration,
    acting_user: User | None,
    db_session: Session,
    *,
    connections: Mapping[tuple[int, UUID | None], IntegrationConnection] | None = None,
) -> CallCredentials | ConnectionProblem:
    """The headers for a call by ``acting_user`` (None or the anonymous user
    for a caller with no user), or why the call cannot authenticate."""
    if acting_user is not None and acting_user.is_anonymous:
        acting_user = None
    resolved = resolve_connection(
        integration, acting_user, db_session, connections=connections
    )
    if isinstance(resolved, ConnectionProblem):
        return resolved
    try:
        headers = render_headers(
            integration.header_template,
            resolved.secret,
            extra_values=(
                {"user_email": acting_user.email} if acting_user is not None else None
            ),
        )
    except MissingHeaderValueError as error:
        return ConnectionProblem(
            code=ConnectionState.NEEDS_RECONNECT, reason=error.detail
        )
    secret = resolved.secret
    if (
        integration.auth_method in _TOKEN_METHODS
        and secret is not None
        and secret.access_token
        and not _fills_authorization(integration.header_template)
    ):
        # The user's token wins over a literal Authorization header, as it
        # did for the old OpenAPI tools.
        headers = merge_mcp_headers(
            headers, {"Authorization": f"Bearer {secret.access_token}"}
        )
    return CallCredentials(
        integration_id=integration.id,
        auth_method=integration.auth_method,
        connection_id=resolved.connection_id,
        connection_user_id=(
            acting_user.id
            if integration.auth_mode is IntegrationAuthMode.INDIVIDUAL
            and acting_user is not None
            else None
        ),
        headers=headers,
        secret_fingerprint=resolved.secret_fingerprint,
        expires_at=resolved.expires_at,
    )


def credentials_near_expiry(credentials: CallCredentials) -> bool:
    """Whether the bearer token of a token method expires within the refresh
    window, so a call must resolve the credential again."""
    return (
        credentials.auth_method in _TOKEN_METHODS
        and credentials.expires_at is not None
        and credentials.expires_at - datetime.now(timezone.utc) <= REFRESH_SKEW
    )


def resolve_fresh_call_credentials(
    integration_id: int, acting_user_id: UUID | None
) -> CallCredentials | ConnectionProblem:
    """``resolve_call_credentials`` in a session of its own, for a call that
    runs after construction with a token near expiry."""
    with get_session_with_current_tenant() as db_session:
        integration = get_integration_by_id(integration_id, db_session)
        if integration is None or not integration.enabled:
            return ConnectionProblem(
                code=ConnectionState.NOT_SET_UP,
                reason="The integration is no longer available.",
            )
        acting_user = (
            fetch_user_by_id(db_session, acting_user_id)
            if acting_user_id is not None
            else None
        )
        return resolve_call_credentials(integration, acting_user, db_session)


def mcp_oauth_server(
    integration: Integration,
    credentials: CallCredentials,
    transport: MCPTransport | None,
    db_session: Session,
) -> MCPServerConnection | None:
    """The server settings for the MCP SDK provider that refreshes an OAuth2
    token during a call. None for other methods and for SSE, where the
    refresh before the call (``resolve_connection``) does the job."""
    if (
        credentials.auth_method is not IntegrationAuthMethod.OAUTH2
        or transport is MCPTransport.SSE
    ):
        return None
    server = get_mcp_server_for_integration(integration.id, db_session)
    oauth_client = get_oauth_client(db_session, integration.id)
    if server is None or oauth_client is None:
        return None
    return integration_mcp_server_connection(server, integration, oauth_client)


def mcp_oauth_provider(
    server: MCPServerConnection, credentials: CallCredentials
) -> OAuthClientProvider:
    return make_integration_oauth_provider(
        server,
        IntegrationTokenStorage(
            credentials.integration_id, credentials.connection_user_id
        ),
    )


def mark_api_key_rejected(credentials: CallCredentials) -> None:
    """Set Needs reconnect on an API key connection that the service
    rejected, when the row still holds the key the call sent. OAuth2
    connections are left to the refresh."""
    if (
        credentials.auth_method is not IntegrationAuthMethod.API_KEY
        or credentials.connection_id is None
    ):
        return
    with get_session_with_current_tenant() as db_session:
        connection = get_connection_by_id(
            db_session, credentials.connection_id, for_update=True
        )
        if (
            connection is None
            or connection_secret_fingerprint(connection)
            != credentials.secret_fingerprint
        ):
            return
        mark_connection_needs_reconnect__no_commit(
            db_session, connection, SIGN_IN_REJECTED_REASON
        )
        db_session.commit()
