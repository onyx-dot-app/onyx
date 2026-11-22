"""MCP helper routes for the integration add form: the probe and the OAuth
discovery, and the MCP servers that Craft runs. Integrations are managed
through ``/admin/integrations``.

The admin server routes are the public API of the release before
integrations, which the Terraform provider calls. They read and write the
integration of the server and return the id of its ``mcp_server`` row."""

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, require_permission
from onyx.db.engine.sql_engine import get_session, get_session_with_current_tenant
from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
    Permission,
    PluginInstallationPolicy,
)
from onyx.db.integration import (
    count_integration_actions,
    get_integration_by_kind_row,
    get_mcp_server_for_integration,
)
from onyx.db.integration_access import (
    load_integration_group_settings,
    load_integration_shares,
)
from onyx.db.integration_connection import get_connection
from onyx.db.mcp import get_mcp_server_by_id
from onyx.db.models import Integration, User
from onyx.db.models import MCPServer as DbMCPServer
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.access import (
    publish_integration__no_commit,
    set_company_policy__no_commit,
    set_group_settings__no_commit,
    share_integration__no_commit,
)
from onyx.integrations.connection_models import read_connection_secret
from onyx.integrations.connections import (
    header_field_keys,
)
from onyx.integrations.service import (
    craft_users_of_integration,
    create_integration__no_commit,
    delete_integration_for_user__no_commit,
    get_manageable_integration,
    get_viewable_integration,
    is_private,
    masked_header_template,
    reload_craft_sessions,
    save_connection_fields__no_commit,
    update_integration__no_commit,
)
from onyx.server.features.integrations.models import (
    IntegrationCreate,
    IntegrationUpdate,
    McpServerConfigInput,
)
from onyx.server.features.mcp.client_metadata import (
    router as client_metadata_router,
)
from onyx.server.features.mcp.models import (
    MCPAuthTemplate,
    MCPOAuthDiscoveryRequest,
    MCPOAuthDiscoveryResponse,
    MCPServerAdminView,
    MCPServerCreateResponse,
    MCPServerDeleteResponse,
    MCPServerSimpleUpdateRequest,
    MCPSetupProbeRequest,
    MCPToolCreateRequest,
)
from onyx.server.features.mcp.oauth_discovery import discover_oauth_capabilities
from onyx.server.features.mcp.setup_probe import stream_mcp_probe
from onyx.utils.encryption import is_masked_credential, reject_masked_credentials

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
        integration = get_integration_by_kind_row(
            Integration.mcp_server_id, server.id, db_session
        )
        if integration is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "MCP server not found")
        get_manageable_integration(user, integration.id, db_session)
        return server.server_url


_SHARED_TOKEN_TEMPLATE = {"Authorization": "Bearer {api_key}"}
_manager = require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)


def _alias_integration(server_id: int, db_session: Session) -> Integration:
    integration = get_integration_by_kind_row(
        Integration.mcp_server_id, server_id, db_session
    )
    if integration is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "MCP server not found")
    return integration


def _server_row(integration: Integration, db_session: Session) -> DbMCPServer:
    server = get_mcp_server_for_integration(integration.id, db_session)
    if server is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "MCP server not found")
    return server


def _legacy_auth(
    integration: Integration,
) -> tuple[MCPAuthenticationType, MCPAuthenticationPerformer]:
    performer = (
        MCPAuthenticationPerformer.ADMIN
        if integration.auth_mode is not IntegrationAuthMode.INDIVIDUAL
        else MCPAuthenticationPerformer.PER_USER
    )
    if integration.auth_mode is IntegrationAuthMode.NONE:
        return MCPAuthenticationType.NONE, performer
    if integration.auth_method is IntegrationAuthMethod.ONYX_LOGIN:
        return MCPAuthenticationType.PT_OAUTH, performer
    if integration.auth_method is IntegrationAuthMethod.OAUTH2:
        return MCPAuthenticationType.OAUTH, performer
    return MCPAuthenticationType.API_TOKEN, performer


def _sign_in(
    request: MCPToolCreateRequest, stored_template: dict[str, str] | None
) -> tuple[IntegrationAuthMode, IntegrationAuthMethod | None, dict[str, str] | None]:
    """The integration sign-in of the request. An omitted template keeps the
    stored one; a shared token defaults to a Bearer header."""
    if request.auth_type is MCPAuthenticationType.NONE:
        return IntegrationAuthMode.NONE, None, None
    if request.auth_type is not MCPAuthenticationType.API_TOKEN:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Set up OAuth sign-in of an MCP server on its integration "
            "(/admin/integrations).",
        )
    shared = request.auth_performer is MCPAuthenticationPerformer.ADMIN
    template = (
        dict(request.auth_template.headers)
        if request.auth_template is not None
        else stored_template
    )
    if template is None:
        if not shared:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "auth_template is required when auth_performer is 'per_user'",
            )
        template = dict(_SHARED_TOKEN_TEMPLATE)
    return (
        IntegrationAuthMode.SHARED if shared else IntegrationAuthMode.INDIVIDUAL,
        IntegrationAuthMethod.API_KEY,
        template,
    )


def _save_credentials(
    integration: Integration,
    request: MCPToolCreateRequest,
    user: User,
    *,
    is_new: bool,
    db_session: Session,
) -> None:
    """A shared token and the admin values go to the organization connection
    of a shared server. The admin values of a per-user server go to the
    admin's own connection. A value that is not sent as changed stays."""
    if integration.auth_mode is IntegrationAuthMode.NONE:
        return
    owner = user if integration.auth_mode is IntegrationAuthMode.INDIVIDUAL else None
    connection = get_connection(
        db_session, integration.id, owner.id if owner is not None else None
    )
    stored = read_connection_secret(connection).fields if connection else {}
    written = {
        key: value
        for key, value in (request.admin_credentials or {}).items()
        if request.admin_credentials_changed.get(key) or key not in stored
    }
    token = request.api_token
    if (
        owner is None
        and token
        and (request.api_token_changed or not is_masked_credential(token))
    ):
        written["api_key"] = token
    try:
        reject_masked_credentials(written)
    except ValueError as error:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(error)) from error
    values = {**stored, **written}
    fields = {
        key: values[key]
        for key in header_field_keys(integration.header_template or {})
        if key in values
    }
    if not is_new and fields == stored:
        return
    if not fields and owner is not None:
        return
    save_connection_fields__no_commit(integration, owner, fields, db_session)


def _apply_access(
    user: User,
    integration: Integration,
    *,
    is_public: bool | None,
    group_ids: list[int] | None,
    user_ids: list[UUID] | None,
    db_session: Session,
) -> set[UUID]:
    """Public is Available to the organization, with no shares. Private has
    the users and groups as its shares. ``group_ids`` is the full set of
    groups with access; ``None`` keeps the groups. The caller locked the
    integration and checked that the user manages it. Returns the affected
    users."""
    if is_public is None and group_ids is None and user_ids is None:
        return set()
    affected: set[UUID] = set()
    public = is_public if is_public is not None else not is_private(integration)
    if public:
        if is_private(integration):
            affected |= share_integration__no_commit(
                user, integration, [], [], db_session
            )
            affected |= publish_integration__no_commit(user, integration, db_session)
        return affected
    if not is_private(integration):
        affected |= set_company_policy__no_commit(
            integration, PluginInstallationPolicy.NOT_AVAILABLE, db_session
        )
    if group_ids is not None:
        # The legacy groups are each group with access (_admin_view). A
        # group left out loses the setting that gives it access, too.
        dropped = {
            setting.group_id: None
            for setting in load_integration_group_settings(integration.id, db_session)
            if setting.installation_policy != PluginInstallationPolicy.NOT_AVAILABLE
            and setting.group_id not in group_ids
        }
        if dropped:
            affected |= set_group_settings__no_commit(
                user, integration, dropped, db_session
            )
    users, groups = _shares(integration, db_session)
    return affected | share_integration__no_commit(
        user,
        integration,
        user_ids if user_ids is not None else users,
        group_ids if group_ids is not None else groups,
        db_session,
    )


def _shares(
    integration: Integration, db_session: Session
) -> tuple[list[UUID], list[int]]:
    shares = load_integration_shares(integration.id, db_session)
    return (
        [share.user_id for share in shares.user_shares],
        [share.group_id for share in shares.group_shares],
    )


def _private_access(
    integration: Integration, db_session: Session
) -> tuple[list[UUID], list[int]]:
    """The users and groups of a private server in the legacy view. A group
    with its own setting above Not available also has access, and the legacy
    view has no group settings, so it lists such a group too. A public server
    lists none: each user has access."""
    users, groups = _shares(integration, db_session)
    return users, sorted(
        set(groups)
        | {
            setting.group_id
            for setting in load_integration_group_settings(integration.id, db_session)
            if setting.installation_policy != PluginInstallationPolicy.NOT_AVAILABLE
        }
    )


def _admin_view(integration: Integration, db_session: Session) -> MCPServerAdminView:
    server = _server_row(integration, db_session)
    is_public = not is_private(integration)
    users, groups = ([], []) if is_public else _private_access(integration, db_session)
    auth_type, auth_performer = _legacy_auth(integration)
    template = masked_header_template(integration.header_template)
    return MCPServerAdminView(
        id=server.id,
        name=integration.name,
        description=integration.description,
        server_url=server.server_url,
        owner=server.owner,
        transport=server.transport,
        auth_type=auth_type,
        auth_performer=auth_performer,
        status=server.status,
        is_public=is_public,
        groups=groups,
        users=users,
        available_in_craft=server.available_in_craft,
        integration_id=integration.id,
        last_refreshed_at=server.last_refreshed_at,
        tool_count=count_integration_actions([integration.id], db_session)[
            integration.id
        ],
        auth_template=(
            MCPAuthTemplate(
                headers=template,
                required_fields=sorted(header_field_keys(template)),
            )
            if template
            else None
        ),
    )


@admin_router.post("/servers/create")
def upsert_mcp_server_alias(
    request: MCPToolCreateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(_manager),
) -> MCPServerCreateResponse:
    """Create an MCP server, or update the one of ``existing_server_id``."""
    if request.existing_server_id is None:
        stored_template = None
        integration = None
    else:
        integration = get_manageable_integration(
            user,
            _alias_integration(request.existing_server_id, db_session).id,
            db_session,
        )
        stored_template = integration.header_template
    auth_mode, auth_method, header_template = _sign_in(request, stored_template)
    if integration is None:
        integration = create_integration__no_commit(
            user,
            IntegrationCreate(
                for_organization=(
                    request.is_public
                    if request.is_public is not None
                    else has_global_permission(user, Permission.MANAGE_ACTIONS)
                ),
                name=request.name,
                description=request.description,
                auth_mode=auth_mode,
                auth_method=auth_method,
                header_template=header_template,
                config=McpServerConfigInput(
                    server_url=request.server_url,
                    transport=request.transport or MCPTransport.STREAMABLE_HTTP,
                ),
            ),
            db_session,
            # The Terraform provider route keeps its old behavior: it saves
            # the server before Onyx can reach it.
            save_unreachable_server=True,
        )
        is_new = True
    else:
        server = _server_row(integration, db_session)
        update = IntegrationUpdate(
            name=request.name,
            auth_mode=auth_mode,
            auth_method=auth_method,
            header_template=header_template,
            config=McpServerConfigInput(
                server_url=request.server_url,
                transport=request.transport
                or server.transport
                or MCPTransport.STREAMABLE_HTTP,
            ),
        )
        if request.description is not None:
            update.description = request.description
        integration = update_integration__no_commit(
            user, integration.id, update, db_session
        )
        is_new = False
    _save_credentials(integration, request, user, is_new=is_new, db_session=db_session)
    affected = _apply_access(
        user,
        integration,
        is_public=None if is_new else request.is_public,
        group_ids=request.groups,
        user_ids=request.users,
        db_session=db_session,
    )
    db_session.commit()
    reload_craft_sessions(
        affected | craft_users_of_integration(integration.id, db_session), db_session
    )
    server = _server_row(integration, db_session)
    auth_type, auth_performer = _legacy_auth(integration)
    return MCPServerCreateResponse(
        server_id=server.id,
        server_name=integration.name,
        server_url=server.server_url,
        auth_type=auth_type.value,
        auth_performer=auth_performer.value,
        no_user_authentication_required=integration.auth_mode
        is not IntegrationAuthMode.INDIVIDUAL,
    )


@admin_router.get("/servers/{server_id}")
def get_mcp_server_alias(
    server_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(_manager),
) -> MCPServerAdminView:
    integration = get_viewable_integration(
        user, _alias_integration(server_id, db_session).id, db_session
    )
    return _admin_view(integration, db_session)


@admin_router.patch("/server/{server_id}")
def update_mcp_server_alias(
    server_id: int,
    request: MCPServerSimpleUpdateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(_manager),
) -> MCPServerAdminView:
    integration = get_manageable_integration(
        user, _alias_integration(server_id, db_session).id, db_session
    )
    server = _server_row(integration, db_session)
    update = IntegrationUpdate()
    if request.name is not None:
        update.name = request.name
    if request.description is not None:
        update.description = request.description
    if request.server_url is not None:
        update.config = McpServerConfigInput(
            server_url=request.server_url,
            transport=server.transport or MCPTransport.STREAMABLE_HTTP,
        )
    integration = update_integration__no_commit(
        user, integration.id, update, db_session
    )
    if request.available_in_craft is not None:
        # A kind setting that the alias returns; the runtime does not read it.
        server.available_in_craft = request.available_in_craft
    affected = _apply_access(
        user,
        integration,
        is_public=request.is_public,
        group_ids=request.groups,
        user_ids=request.users,
        db_session=db_session,
    )
    db_session.commit()
    reload_craft_sessions(
        affected | craft_users_of_integration(integration.id, db_session), db_session
    )
    return _admin_view(integration, db_session)


@admin_router.delete("/server/{server_id}")
def delete_mcp_server_alias(
    server_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(_manager),
) -> MCPServerDeleteResponse:
    integration_id = _alias_integration(server_id, db_session).id
    affected = craft_users_of_integration(integration_id, db_session)
    delete_integration_for_user__no_commit(user, integration_id, db_session)
    db_session.commit()
    reload_craft_sessions(affected, db_session)
    return MCPServerDeleteResponse(success=True)
