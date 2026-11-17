"""MCP helper routes for the integration add form: the probe and the OAuth
discovery, and the MCP servers that Craft runs. Integrations are managed
through ``/admin/integrations``."""

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session, get_session_with_current_tenant
from onyx.db.enums import IntegrationKind, Permission
from onyx.db.integration import (
    get_integration_plugin_ids,
    get_mcp_server_for_integration,
)
from onyx.db.mcp import get_mcp_server_by_id
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.connection_models import ConnectionState
from onyx.integrations.connections import integration_status
from onyx.integrations.craft import list_runnable_integrations
from onyx.integrations.service import get_manageable_integration
from onyx.server.features.mcp.client_metadata import (
    router as client_metadata_router,
)
from onyx.server.features.mcp.models import (
    MCPConnectionStatus,
    MCPOAuthDiscoveryRequest,
    MCPOAuthDiscoveryResponse,
    MCPServer,
    MCPServersResponse,
    MCPSetupProbeRequest,
)
from onyx.server.features.mcp.oauth_discovery import discover_oauth_capabilities
from onyx.server.features.mcp.setup_probe import stream_mcp_probe

router = APIRouter(prefix="/mcp")
router.include_router(client_metadata_router)
admin_router = APIRouter(prefix="/admin/mcp")


@admin_router.post("/probe")
async def stream_admin_mcp_probe(
    request: MCPSetupProbeRequest,
    _user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> StreamingResponse:
    return StreamingResponse(
        stream_mcp_probe(request.server_url),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@admin_router.post("/oauth/discover")
async def discover_admin_oauth(
    request: MCPOAuthDiscoveryRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> MCPOAuthDiscoveryResponse:
    server_url = await run_in_threadpool(
        lambda: _get_authorized_discovery_url(request.server_id, user)
    )
    return await discover_oauth_capabilities(server_url)


def _get_authorized_discovery_url(server_id: int, user: User) -> str:
    """The server URL, when the user manages the integration of the server."""
    with get_session_with_current_tenant() as db_session:
        try:
            server = get_mcp_server_by_id(server_id, db_session)
        except ValueError as error:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "MCP server not found") from error
        if server.integration_id is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "MCP server not found")
        get_manageable_integration(user, server.integration_id, db_session)
        return server.server_url


_CONNECTION_STATUS: dict[ConnectionState, MCPConnectionStatus] = {
    ConnectionState.CONNECTED: MCPConnectionStatus.CONNECTED,
    ConnectionState.NOT_CONNECTED: MCPConnectionStatus.NOT_CONNECTED,
    ConnectionState.NOT_SET_UP: MCPConnectionStatus.NOT_CONNECTED,
    ConnectionState.NEEDS_RECONNECT: MCPConnectionStatus.REAUTH_REQUIRED,
}


@router.get("/servers/craft")
def get_craft_mcp_servers_for_user(
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPServersResponse:
    """The MCP servers of the integrations of the plugins the user runs, with
    the user's connection state."""
    pairs = [
        (integration, server)
        for integration in list_runnable_integrations(db_session, user.id)
        if integration.kind is IntegrationKind.MCP
        and (server := get_mcp_server_for_integration(integration.id, db_session))
        is not None
    ]
    plugin_ids = get_integration_plugin_ids(
        [integration.id for integration, _ in pairs], db_session
    )
    servers: list[MCPServer] = []
    for integration, server in pairs:
        state = integration_status(integration, user, db_session).state
        servers.append(
            MCPServer(
                id=server.id,
                name=integration.name,
                description=integration.description,
                server_url=server.server_url,
                owner=server.owner,
                transport=server.transport,
                connection_status=_CONNECTION_STATUS[state],
                status=server.status,
                available_in_craft=True,
                plugin_ids=plugin_ids.get(integration.id, []),
                craft_connected=state is ConnectionState.CONNECTED,
            )
        )
    return MCPServersResponse(mcp_servers=servers)
