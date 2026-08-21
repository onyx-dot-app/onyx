import datetime
import ipaddress
import secrets
import time
from collections.abc import Mapping
from enum import Enum
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull
from mcp.types import Tool as MCPLibTool
from pydantic import AnyUrl, BaseModel
from sqlalchemy.orm import Session

from onyx.auth.oauth_token_manager import validate_oauth_endpoint_url
from onyx.auth.permission_projection import mcp_server_permissions, tool_permissions
from onyx.auth.permissions import (
    get_effective_permissions,
    has_permission,
    require_permission,
)
from onyx.auth.scoped_permissions import assert_within_scope, get_scoped_groups
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import (
    EndpointPolicy,
    GatedAppKind,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
    MCPServerStatus,
    MCPTransport,
    Permission,
    PermissionAuthority,
)
from onyx.db.gated_app import (
    get_action_policies,
    get_or_create_gated_app_id,
    replace_action_policies__no_commit,
)
from onyx.db.mcp import (
    affected_user_ids_for_mcp_server,
    create_connection_config,
    create_mcp_server__no_commit,
    delete_all_user_connection_configs_for_server_no_commit,
    delete_connection_config,
    delete_mcp_server,
    delete_user_connection_configs_for_server,
    get_all_mcp_servers,
    get_all_mcp_tools_for_server,
    get_craft_enabled_mcp_servers,
    get_mcp_server_by_id,
    get_mcp_servers_accessible_to_user,
    get_mcp_servers_for_persona,
    get_user_connection_config,
    get_user_connection_configs,
    update_connection_config,
    update_connection_config__no_commit,
    update_mcp_server__no_commit,
    upsert_user_connection_config,
    user_can_access_mcp_server,
)
from onyx.db.models import MCPConnectionConfig, Tool, User
from onyx.db.models import MCPServer as DbMCPServer
from onyx.db.tools import (
    can_manage_mcp_server,
    can_manage_tool,
    create_tool__no_commit,
    delete_tool__no_commit,
    get_mcp_server_ids_connected_to_groups,
    get_tools_by_mcp_server_id,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp.client import (
    discover_mcp_tools,
    log_exception_group,
)
from onyx.server.features.mcp.client_metadata import (
    router as client_metadata_router,
)
from onyx.server.features.mcp.credentials import (
    extract_connection_data,
    get_mcp_auth_template,
    mcp_oauth_client_information_fingerprint,
    mcp_token_expired,
    requires_user_authentication,
    resolve_mcp_credentials,
    user_can_authenticate,
)
from onyx.server.features.mcp.models import (
    MCPApiKeyResponse,
    MCPAuthTemplate,
    MCPConnectionData,
    MCPOAuthCallbackResponse,
    MCPOAuthKeys,
    MCPServer,
    MCPServerCreateResponse,
    MCPServerSimpleCreateRequest,
    MCPServerSimpleUpdateRequest,
    MCPServersResponse,
    MCPServerUpdateResponse,
    MCPToolCreateRequest,
    MCPToolListResponse,
    MCPToolUpdateRequest,
    MCPUserCredentialsRequest,
    MCPUserOAuthConnectRequest,
    MCPUserOAuthConnectResponse,
    contains_mcp_placeholder,
    merge_mcp_headers,
)
from onyx.server.features.mcp.oauth import (
    REQUESTED_SCOPE,
    MCPReauthenticationRequired,
    complete_mcp_oauth_authorization,
    make_oauth_provider,
)
from onyx.server.features.mcp.oauth_flow import (
    OAuthAlreadyAuthenticated,
    OAuthAuthorizationRedirect,
    mcp_oauth_attempt_store,
    start_auto_discovery_oauth_flow,
    start_known_provider_oauth_flow,
    validate_mcp_oauth_flow_configuration,
)
from onyx.server.features.mcp.ssrf import validate_mcp_outbound_url
from onyx.server.features.tool.models import ToolSnapshot
from onyx.utils.encryption import (
    is_masked_credential,
    mask_string,
    reject_masked_credentials,
)
from onyx.utils.logger import setup_logger
from onyx.utils.url import BLOCKED_HOSTNAMES, SSRFException
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# A tool with no stored override is treated as ASK; stored policies stay sparse
# by omitting this value (mirrors the gate evaluator's default).
MCP_TOOL_DEFAULT_POLICY = EndpointPolicy.ASK


_SSRF_HINT_NEVER_ALLOWED = (
    " localhost, unspecified, and link-local/cloud-metadata addresses are never "
    "permitted; use a loopback or private-network address instead."
)
_SSRF_HINT_SET_ALLOW_PRIVATE = (
    " To reach a private-network MCP server, set SSRF Protection to Allow Private "
    "Network (or Disabled) in the admin Security settings (loopback and "
    "cloud-metadata stay blocked at Allow Private Network)."
)
_SSRF_HINT_SET_DISABLED = (
    " To reach a loopback MCP server, set SSRF Protection to Disabled in the admin "
    "Security settings (cloud-metadata stays blocked)."
)


def _ssrf_error_hint(url: str, error: Exception) -> str:
    """Suffix steering the operator to the remedy for a blocked host. A private
    LAN target is reachable at Allow Private Network (or Disabled); loopback needs
    Disabled (it hits the app host itself). Link-local/metadata, unspecified, and
    BLOCKED_HOSTNAMES (e.g. localhost) are never reachable, so suggest a different
    address; scheme errors get no hint. Only literal IPs are classified —
    store-time validation doesn't resolve hostnames, so a bare name can't reach
    the address-specific branches."""
    if "scheme" in str(error).lower():
        return ""
    host = (urlparse(url).hostname or "").lower()
    if host in BLOCKED_HOSTNAMES:
        return _SSRF_HINT_NEVER_ALLOWED
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return ""
    if ip.is_unspecified or ip.is_link_local:
        return _SSRF_HINT_NEVER_ALLOWED
    # Loopback reaches the app host itself, so it needs the Disabled level; other
    # private/reserved targets open one notch lower, at Allow Private Network.
    if ip.is_loopback:
        return _SSRF_HINT_SET_DISABLED
    if not ip.is_global:
        return _SSRF_HINT_SET_ALLOW_PRIVATE
    return ""


def _validate_mcp_server_url(
    url: str | None, field: str, *, require_https: bool
) -> None:
    """Store-time SSRF guard for a curator-supplied URL; raises ``OnyxError`` as
    a field-level frontend error. ``require_https`` routes OAuth endpoints through
    the same validator the token exchange uses, so a URL that saves can't be
    rejected later. Structural-only (``resolve_dns=False``): rejects bad
    scheme/credentials/blocked hosts and literal internal IPs but doesn't resolve
    hostnames, so a transient/internal-DNS host doesn't block a save; fetch-time
    guards resolve DNS and cover SDK redirects/rebinding."""
    if not url:
        return
    validator = (
        validate_oauth_endpoint_url if require_https else validate_mcp_outbound_url
    )
    try:
        validator(url, resolve_dns=False)
    except (SSRFException, ValueError) as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Invalid {field}: {e}{_ssrf_error_hint(url, e)}",
        )


def _truncate_description(description: str | None, max_length: int = 500) -> str:
    """Truncate description to max_length characters, adding ellipsis if truncated."""
    if not description:
        return ""
    if len(description) <= max_length:
        return description
    return description[: max_length - 3] + "..."


def _resolve_oauth_credentials(
    *,
    request_client_id: str | None,
    request_client_id_changed: bool,
    request_client_secret: str | None,
    request_client_secret_changed: bool,
    existing_client: OAuthClientInformationFull | None,
) -> tuple[str | None, str | None]:
    """Pick the effective client_id / client_secret for an upsert/connect.

    Mirrors the LLM-provider `api_key_changed` pattern: when the frontend
    flags a field as unchanged, ignore whatever value it sent (it is most
    likely a masked placeholder) and reuse the stored value. When the
    frontend flags a field as changed, take the request value as-is, but
    defensively reject masked placeholders so a buggy client can't write
    a mask to the database.

    When there is no stored client yet (`existing_client is None`), an
    unchanged flag means the user did not edit since load — still use the
    request body (`_connect_oauth` runs after upsert with the same payload).
    Treating unchanged plus no storage as None would rebuild empty OAuth config.
    """
    resolved_id = request_client_id
    if not request_client_id_changed:
        resolved_id = (
            existing_client.client_id if existing_client else request_client_id
        )
    elif resolved_id:
        reject_masked_credentials({"oauth_client_id": resolved_id})

    resolved_secret = request_client_secret
    if not request_client_secret_changed:
        resolved_secret = (
            existing_client.client_secret if existing_client else request_client_secret
        )
    elif resolved_secret:
        reject_masked_credentials({"oauth_client_secret": resolved_secret})

    return resolved_id, resolved_secret


def _resolve_admin_credentials(
    *,
    request_credentials: dict[str, str],
    request_credentials_changed: dict[str, bool],
    existing_user_credentials: dict[str, str] | None,
) -> dict[str, str]:
    """Per-key analogue of ``_resolve_oauth_credentials``: reuse the
    stored value when the changed flag is False, otherwise take the
    request value and reject masked placeholders defensively. Stored
    values are sourced from the editing admin's own per-user
    ``header_substitutions``."""
    resolved: dict[str, str] = {}
    for key, request_value in request_credentials.items():
        changed = request_credentials_changed.get(key, False)
        if (
            not changed
            and existing_user_credentials
            and key in existing_user_credentials
        ):
            resolved[key] = existing_user_credentials[key]
            continue
        if request_value:
            reject_masked_credentials({key: request_value})
        resolved[key] = request_value
    return resolved


def _default_shared_api_token_template() -> MCPAuthTemplate:
    """Return the legacy shared API-token template."""
    return MCPAuthTemplate(
        headers={"Authorization": "Bearer {api_key}"},
        required_fields=["api_key"],
    )


def _extract_shared_api_token(config_data: MCPConnectionData) -> str:
    """Read the encrypted shared token, with compatibility for old configs."""
    if api_token := config_data.get("api_token"):
        return api_token

    authorization = config_data.get("headers", {}).get("Authorization", "")
    if authorization:
        return authorization.rsplit(" ", 1)[-1]

    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        "Existing shared MCP API token could not be recovered; please re-enter it.",
    )


def _resolve_shared_api_token(
    *,
    request_api_token: str | None,
    request_api_token_changed: bool,
    existing_config: MCPConnectionData | None,
) -> str | None:
    """Preserve masked shared tokens when only configuration is edited."""
    if request_api_token_changed:
        if request_api_token:
            reject_masked_credentials({"api_token": request_api_token})
        return request_api_token

    # A real token in the request takes precedence during auth-mode
    # conversion, even when older clients omit the changed flag.
    if request_api_token and not is_masked_credential(request_api_token):
        return request_api_token

    if existing_config and (
        "api_token" in existing_config
        or "Authorization" in existing_config.get("headers", {})
    ):
        return _extract_shared_api_token(existing_config)

    if request_api_token:
        reject_masked_credentials({"api_token": request_api_token})
    return request_api_token


def _resolve_shared_api_token_template(
    *,
    request_template: MCPAuthTemplate | None,
    existing_config: MCPConnectionData | None,
) -> MCPAuthTemplate | None:
    """Preserve an existing shared header template when omitted on update."""
    if request_template is not None:
        return request_template

    if existing_config:
        stored_template: dict[str, str] | None = existing_config.get("header_template")
        if stored_template:
            return MCPAuthTemplate(
                headers=stored_template,
                required_fields=["api_key"],
            )

    return None


def _resolve_auth_template(
    request_template: MCPAuthTemplate,
    changed_headers: dict[str, bool],
    existing_template: MCPAuthTemplate | None,
) -> MCPAuthTemplate:
    headers: dict[str, str] = {}
    existing_headers = existing_template.headers if existing_template else {}
    for name, request_value in request_template.headers.items():
        existing_value = existing_headers.get(name)
        if (
            not changed_headers.get(name, False)
            and existing_value is not None
            and (request_value == existing_value or is_masked_credential(request_value))
        ):
            headers[name] = existing_value
            continue
        reject_masked_credentials({name: request_value})
        headers[name] = request_value
    return MCPAuthTemplate(headers=headers)


def _mask_auth_template(template: MCPAuthTemplate) -> MCPAuthTemplate:
    headers = {
        name: value if contains_mcp_placeholder(value) else mask_string(value)
        for name, value in template.headers.items()
    }
    return MCPAuthTemplate.model_construct(
        headers=headers,
        required_fields=template.required_fields,
    )


def _build_shared_api_token_config_data(
    *,
    api_token: str,
    auth_template: MCPAuthTemplate | None,
    header_substitutions: dict[str, str] | None,
    user_email: str,
) -> MCPConnectionData:
    """Render and persist a shared API-token header template."""
    template = auth_template or _default_shared_api_token_template()
    substitutions = {**(header_substitutions or {}), "api_key": api_token}
    return MCPConnectionData(
        headers=template.render(substitutions, user_email=user_email),
        header_template=template.headers,
        api_token=api_token,
        header_substitutions=header_substitutions or {},
        required_fields=template.required_fields,
    )


def _build_oauth_admin_config_data(
    *,
    client_id: str | None,
    client_secret: str | None,
    auth_template: MCPAuthTemplate | None = None,
) -> MCPConnectionData:
    """Construct the admin connection config payload for an OAuth client.

    A public client legitimately has no `client_secret`, so we only require
    a `client_id` to seed `client_info`. When no client_id is available we
    fall through to an empty config (the OAuth provider will rely on
    Dynamic Client Registration to obtain credentials).
    """
    config_data = MCPConnectionData(headers={})
    if auth_template is not None:
        config_data["header_template"] = auth_template.headers
        config_data["required_fields"] = auth_template.required_fields
    if not client_id:
        return config_data
    token_endpoint_auth_method = "client_secret_post" if client_secret else "none"
    client_info = OAuthClientInformationFull(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uris=[AnyUrl(f"{WEB_DOMAIN}/mcp/oauth/callback")],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=REQUESTED_SCOPE,  # TODO(evan): allow specifying scopes?
        token_endpoint_auth_method=token_endpoint_auth_method,
    )
    config_data[MCPOAuthKeys.CLIENT_INFO.value] = client_info.model_dump(mode="json")
    return config_data


def _build_oauth_admin_config_data_for_update(
    *,
    client_id: str | None,
    client_secret: str | None,
    existing_client: OAuthClientInformationFull,
    auth_template: MCPAuthTemplate | None = None,
) -> MCPConnectionData:
    """Construct the admin connection config payload for an OAuth client
    that already has a stored `client_info`, preserving provider-managed
    fields (DCR registration token, expiry timestamps, negotiated auth
    method, etc.) wherever possible.

    When `client_id` matches the stored client_id, the merged payload
    starts from `existing_client` and only overwrites the admin-managed
    fields (`client_secret`, `redirect_uris`, `scope`). When `client_id`
    differs, the admin is pointing at a brand-new OAuth registration so
    the old DCR metadata is stale; we fall back to the template path.
    """
    if not client_id:
        # No id means we have nothing to seed client_info with; matches
        # the template-path behavior of returning an empty config so the
        # OAuth provider can attempt DCR.
        return _build_oauth_admin_config_data(
            client_id=client_id,
            client_secret=client_secret,
            auth_template=auth_template,
        )

    if existing_client.client_id != client_id:
        logger.info(
            "OAuth client_id changed for existing MCP server; discarding "
            "stored DCR registration metadata and starting fresh."
        )
        return _build_oauth_admin_config_data(
            client_id=client_id,
            client_secret=client_secret,
            auth_template=auth_template,
        )

    merged = existing_client.model_copy(deep=True)
    merged.client_secret = client_secret
    merged.redirect_uris = [AnyUrl(f"{WEB_DOMAIN}/mcp/oauth/callback")]
    merged.scope = REQUESTED_SCOPE  # TODO(evan): allow specifying scopes?
    # Heal stale records that were seeded before `_upsert_mcp_server` always
    # set `token_endpoint_auth_method`. The SDK silently omits the client
    # secret on token exchange when this is None, which manifests as
    # `invalid_client` from the IdP. Preserve any explicitly-negotiated
    # method (e.g. DCR's `client_secret_basic`).
    if merged.token_endpoint_auth_method is None:
        merged.token_endpoint_auth_method = (
            "client_secret_post" if client_secret else "none"
        )

    config_data = MCPConnectionData(headers={})
    if auth_template is not None:
        config_data["header_template"] = auth_template.headers
        config_data["required_fields"] = auth_template.required_fields
    config_data[MCPOAuthKeys.CLIENT_INFO.value] = merged.model_dump(mode="json")
    return config_data


def _build_template_config_data(
    auth_template: MCPAuthTemplate | None,
) -> MCPConnectionData:
    config_data = MCPConnectionData(headers={})
    if auth_template is not None:
        config_data["header_template"] = auth_template.headers
        config_data["required_fields"] = auth_template.required_fields
    return config_data


def _persist_admin_connection_config(
    mcp_server: DbMCPServer,
    config_data: MCPConnectionData,
    db_session: Session,
) -> int:
    if mcp_server.admin_connection_config_id is not None:
        update_connection_config__no_commit(
            mcp_server.admin_connection_config_id, db_session, config_data
        )
        return mcp_server.admin_connection_config_id
    return create_connection_config(
        config_data=config_data,
        mcp_server_id=mcp_server.id,
        db_session=db_session,
    ).id


def _upsert_user_template_config(
    *,
    mcp_server: DbMCPServer,
    template: MCPAuthTemplate,
    substitutions: dict[str, str],
    user_email: str,
    db_session: Session,
) -> None:
    existing = get_user_connection_config(mcp_server.id, user_email, db_session)
    existing_data = extract_connection_data(existing, apply_mask=False)
    config_data = MCPConnectionData(
        headers=template.render(substitutions, user_email=user_email),
        header_substitutions=substitutions,
    )
    for oauth_key in MCPOAuthKeys:
        field_key: Literal["client_info", "tokens", "metadata", "token_expires_at"] = (
            oauth_key.value
        )
        if field_value := existing_data.get(field_key):
            config_data[field_key] = field_value
    upsert_user_connection_config(
        server_id=mcp_server.id,
        user_email=user_email,
        config_data=config_data,
        db_session=db_session,
    )


router = APIRouter(prefix="/mcp")
router.include_router(client_metadata_router)
admin_router = APIRouter(prefix="/admin/mcp")

HEADER_SUBSTITUTIONS: Literal["header_substitutions"] = "header_substitutions"


def _hot_reload_craft_sessions(user_ids: set[UUID], db_session: Session) -> None:
    """Restamp affected users' running sandboxes with the current craft MCP
    fingerprint so a live Craft session picks up the change on its next turn
    (via the session reload) without a pod re-provision. Updates only
    ``mcp_config_hash`` — it does not re-push skill files. Best-effort; imported
    lazily to avoid a build-layer import cycle at module load."""
    if not user_ids:
        return
    from onyx.server.features.build.session.sandbox_lifecycle import (
        refresh_mcp_config_hashes_for_users,
    )

    refresh_mcp_config_hashes_for_users(user_ids, db_session)


def _build_headers_from_template(
    template_data: MCPAuthTemplate, credentials: dict[str, str], user_email: str
) -> dict[str, str]:
    return template_data.render(credentials, user_email=user_email)


def test_mcp_server_credentials(
    server_url: str,
    connection_headers: dict[str, str] | None,
    auth: OAuthClientProvider | None,
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
) -> tuple[bool, str]:
    """Test if credentials work by calling the MCP server's tools/list endpoint"""
    try:
        # Attempt to discover tools using the provided credentials
        tools = discover_mcp_tools(
            server_url, connection_headers, transport=transport, auth=auth
        )

        if (
            tools is not None and len(tools) >= 0
        ):  # Even 0 tools is a successful connection
            return True, f"Successfully connected. Found {len(tools)} tools."
        else:
            return False, "Failed to retrieve tools list from server."

    except Exception as e:
        logger.error("Failed to test MCP server credentials: %s", e)
        return False, f"Connection failed: {str(e)}"


@admin_router.post("/oauth/connect", response_model=MCPUserOAuthConnectResponse)
async def connect_admin_oauth(
    request: MCPUserOAuthConnectRequest,
    db: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> MCPUserOAuthConnectResponse:
    """Connect OAuth flow for admin MCP server authentication"""
    return await _connect_oauth(request, db, is_admin=True, user=user)


@router.post("/oauth/connect", response_model=MCPUserOAuthConnectResponse)
async def connect_user_oauth(
    request: MCPUserOAuthConnectRequest,
    db: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPUserOAuthConnectResponse:
    return await _connect_oauth(request, db, is_admin=False, user=user)


async def _connect_oauth(
    request: MCPUserOAuthConnectRequest,
    db: Session,
    is_admin: bool,
    user: User,
) -> MCPUserOAuthConnectResponse:
    """Connect OAuth flow for per-user MCP server authentication"""

    logger.info("Initiating per-user OAuth for server: %s", request.server_id)

    server_id = request.server_id
    try:
        mcp_server = get_mcp_server_by_id(server_id, db)
    except ValueError as error:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "MCP server not found") from error

    if is_admin:
        _ensure_mcp_server_owner_or_admin(mcp_server, user)
    elif not user_can_access_mcp_server(user, server_id, db):
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "You do not have access to this MCP server.",
        )

    if mcp_server.auth_type != MCPAuthenticationType.OAUTH:
        auth_type_str = mcp_server.auth_type.value if mcp_server.auth_type else "None"
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Server was configured with authentication type {auth_type_str}",
        )
    if mcp_server.auth_performer != MCPAuthenticationPerformer.PER_USER:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "OAuth MCP servers must use per-user authentication.",
        )

    # Resolve the effective OAuth credentials, falling back to the stored
    # values for any field the frontend marked as unchanged. This protects
    # against the resubmit case where the form replays masked placeholders.
    existing_client: OAuthClientInformationFull | None = None
    if mcp_server.admin_connection_config:
        existing_data = extract_connection_data(
            mcp_server.admin_connection_config, apply_mask=False
        )
        existing_client_raw = existing_data.get(MCPOAuthKeys.CLIENT_INFO.value)
        if existing_client_raw:
            existing_client = OAuthClientInformationFull.model_validate(
                existing_client_raw
            )

    oauth_client_id, oauth_client_secret = _resolve_oauth_credentials(
        request_client_id=request.oauth_client_id,
        request_client_id_changed=request.oauth_client_id_changed,
        request_client_secret=request.oauth_client_secret,
        request_client_secret_changed=request.oauth_client_secret_changed,
        existing_client=existing_client,
    )

    # When we already have a stored `client_info`, merge into it so we
    # preserve any provider-managed fields (DCR registration token,
    # `client_secret_expires_at`, negotiated `token_endpoint_auth_method`,
    # etc.) that the hardcoded template would otherwise drop.
    config_data = (
        _build_oauth_admin_config_data_for_update(
            client_id=oauth_client_id,
            client_secret=oauth_client_secret,
            existing_client=existing_client,
            auth_template=get_mcp_auth_template(mcp_server),
        )
        if existing_client is not None
        else _build_oauth_admin_config_data(
            client_id=oauth_client_id,
            client_secret=oauth_client_secret,
            auth_template=get_mcp_auth_template(mcp_server),
        )
    )

    if mcp_server.admin_connection_config_id is None:
        if not is_admin:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Admin connection config not found for this server",
            )

        admin_config = create_connection_config(
            config_data=config_data,
            mcp_server_id=mcp_server.id,
            user_email="",
            db_session=db,
        )
        mcp_server.admin_connection_config = admin_config
        mcp_server.admin_connection_config_id = (
            admin_config.id
        )  # might not have to do this
    elif is_admin:  # only update admin config if we're an admin
        update_connection_config(mcp_server.admin_connection_config_id, db, config_data)

    connection_config = get_user_connection_config(mcp_server.id, user.email, db)
    existing_user_data = extract_connection_data(connection_config, apply_mask=False)
    oauth_credentials_unchanged = bool(
        connection_config is not None
        and not request.oauth_client_id_changed
        and not request.oauth_client_secret_changed
    )
    credentials_usable = bool(
        oauth_credentials_unchanged
        and not mcp_token_expired(existing_user_data)
        and user_can_authenticate(
            mcp_server,
            user,
            db,
            user_configs={mcp_server.id: connection_config},
        )
    )
    auth_template = get_mcp_auth_template(mcp_server)
    if auth_template is not None and auth_template.required_fields:
        substitutions = existing_user_data.get(HEADER_SUBSTITUTIONS, {})
        missing_fields = [
            field
            for field in auth_template.required_fields
            if not substitutions.get(field)
        ]
        if missing_fields:
            raise OnyxError(
                OnyxErrorCode.MISSING_REQUIRED_FIELD,
                "Submit MCP header values before starting OAuth: "
                f"{', '.join(sorted(missing_fields))}",
            )

    user_config_data = config_data
    if connection_config is not None:
        user_config_data = MCPConnectionData(
            headers=existing_user_data.get("headers", {}),
        )
        user_config_data.update(config_data)
        user_config_data["headers"] = existing_user_data.get("headers", {})
        if substitutions := existing_user_data.get(HEADER_SUBSTITUTIONS):
            user_config_data[HEADER_SUBSTITUTIONS] = substitutions
        if oauth_credentials_unchanged:
            for key in (
                MCPOAuthKeys.TOKENS.value,
                MCPOAuthKeys.TOKEN_EXPIRES_AT.value,
                MCPOAuthKeys.METADATA.value,
            ):
                if (value := existing_user_data.get(key)) is not None:
                    user_config_data[key] = value

    if connection_config is None:
        connection_config = create_connection_config(
            config_data=user_config_data,
            mcp_server_id=mcp_server.id,
            user_email=user.email,
            db_session=db,
        )
    else:
        update_connection_config(connection_config.id, db, user_config_data)

    db.commit()

    connection_config_dict = extract_connection_data(
        connection_config, apply_mask=False
    )

    if mcp_server.oauth_provider_mode == MCPOAuthProviderMode.KNOWN_PROVIDER:
        client_info_raw = connection_config_dict.get(MCPOAuthKeys.CLIENT_INFO.value)
        if not client_info_raw:
            raise OnyxError(
                OnyxErrorCode.MISSING_REQUIRED_FIELD,
                "Known-provider OAuth mode requires a configured OAuth client_id. "
                "Please set client credentials in the auth modal.",
            )

        client_info = OAuthClientInformationFull.model_validate(client_info_raw)
        if not client_info.client_id:
            raise OnyxError(
                OnyxErrorCode.MISSING_REQUIRED_FIELD,
                "Known-provider OAuth mode requires a non-empty client_id",
            )

        if credentials_usable and not request.force_reauthentication:
            return MCPUserOAuthConnectResponse(
                server_id=server_id,
                status="already_authenticated",
                authorization_url=None,
                redirect_url=request.return_path,
            )

        oauth_result = start_known_provider_oauth_flow(
            mcp_server=mcp_server,
            user_id=str(user.id),
            connection_config_id=connection_config.id,
            return_path=request.return_path,
            connection_headers=connection_config_dict.get("headers", {}),
            client_information=client_info,
            include_resource_param=request.include_resource_param,
        )
        return MCPUserOAuthConnectResponse(
            server_id=int(request.server_id),
            status="authorization_required",
            authorization_url=oauth_result.url,
            redirect_url=request.return_path,
        )

    if mcp_server.transport is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "MCP server transport is not configured",
        )

    try:
        oauth_result = await start_auto_discovery_oauth_flow(
            mcp_server=mcp_server,
            user_id=str(user.id),
            return_path=request.return_path,
            connection_config_id=connection_config.id,
            shared_client_config_id=mcp_server.admin_connection_config_id,
            connection_headers=connection_config_dict.get("headers", {}),
            transport=mcp_server.transport,
            credentials_usable=credentials_usable,
            force_reauthentication=request.force_reauthentication,
        )
    except OnyxError:
        raise
    except Exception as e:
        saved_e = log_exception_group(e) if isinstance(e, ExceptionGroup) else e
        logger.error("OAuth initialization failed: %s", saved_e)
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Failed to initialize OAuth client: {str(saved_e)}",
        ) from e

    match oauth_result:
        case OAuthAuthorizationRedirect(url=oauth_url):
            status = "authorization_required"
        case OAuthAlreadyAuthenticated():
            status = "already_authenticated"
            oauth_url = None

    return MCPUserOAuthConnectResponse(
        server_id=int(request.server_id),
        status=status,
        authorization_url=oauth_url,
        redirect_url=request.return_path,
    )


@router.post("/oauth/callback", response_model=MCPOAuthCallbackResponse)
async def process_oauth_callback(
    request: Request,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPOAuthCallbackResponse:
    """Complete an attempt-scoped OAuth flow and persist its tokens."""

    # Get callback data from query parameters (like federated OAuth does)
    callback_data = dict(request.query_params)

    state = callback_data.get("state")
    code = callback_data.get("code")
    user_id = str(user.id)
    if not state:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Missing state parameter")

    flow = (
        mcp_oauth_attempt_store()
        .consume(
            owner_id=user_id,
            state=state,
        )
        .payload
    )
    logger.info(
        "OAuth callback: claimed flow for user_id=%s tenant=%s server_id=%s",
        user_id,
        get_current_tenant_id(),
        flow.server_id,
    )
    if callback_data.get("error"):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "MCP OAuth authorization was denied or failed.",
        )
    if not code:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Missing code parameter")
    try:
        mcp_server = get_mcp_server_by_id(flow.server_id, db_session)
    except ValueError as error:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "MCP server not found") from error

    if not user_can_access_mcp_server(
        user, mcp_server.id, db_session
    ) and not can_manage_mcp_server(user, mcp_server):
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "You no longer have access to or management authority for this MCP server.",
        )

    user_config = get_user_connection_config(mcp_server.id, user.email, db_session)
    if user_config is None or user_config.id != flow.connection_config_id:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "MCP OAuth connection changed while authorization was pending.",
        )

    user_config_data = extract_connection_data(user_config, apply_mask=False)
    validate_mcp_oauth_flow_configuration(
        flow,
        mcp_server,
        user_config_data.get("headers", {}),
    )

    client_info_raw = user_config_data.get(MCPOAuthKeys.CLIENT_INFO.value)
    if not client_info_raw:
        raise OnyxError(
            OnyxErrorCode.MISSING_REQUIRED_FIELD,
            "MCP OAuth callback is missing client registration information. "
            "Restart authorization and try again.",
        )
    client_info = OAuthClientInformationFull.model_validate(client_info_raw)
    current_client_fingerprint = mcp_oauth_client_information_fingerprint(client_info)
    if not secrets.compare_digest(
        current_client_fingerprint,
        flow.client_information_fingerprint,
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "MCP OAuth client registration changed while authorization was pending.",
        )

    await complete_mcp_oauth_authorization(
        flow,
        mcp_server,
        client_info,
        code,
    )

    db_session.commit()

    # OAuth connect unblocks tool discovery for this user's craft session;
    # reload it (single sandbox — this user only).
    _hot_reload_craft_sessions({user.id}, db_session)
    logger.info(
        "server_id=%s server_name=%s return_path=%s",
        str(mcp_server.id),
        mcp_server.name,
        flow.return_path,
    )

    return MCPOAuthCallbackResponse(
        success=True,
        server_id=mcp_server.id,
        server_name=mcp_server.name,
        message=f"OAuth authorization completed successfully for {mcp_server.name}",
        redirect_url=flow.return_path,
    )


@router.post("/user-credentials", response_model=MCPApiKeyResponse)
def save_user_credentials(
    request: MCPUserCredentialsRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPApiKeyResponse:
    try:
        mcp_server = get_mcp_server_by_id(request.server_id, db_session)
    except ValueError:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "MCP server not found")

    server_id = mcp_server.id
    email = user.email
    template = get_mcp_auth_template(mcp_server)
    if template is None:
        if (
            mcp_server.auth_type != MCPAuthenticationType.API_TOKEN
            or "api_key" not in request.credentials
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "This MCP server has no user-configurable header template.",
            )
        config_data = MCPConnectionData(
            headers={"Authorization": f"Bearer {request.credentials['api_key']}"},
            header_substitutions=request.credentials,
        )
    else:
        try:
            config_data = MCPConnectionData(
                headers=template.render(request.credentials, user_email=email),
                header_substitutions=request.credentials,
            )
        except ValueError as error:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                str(error),
            )

    if mcp_server.auth_type == MCPAuthenticationType.OAUTH:
        existing_config = get_user_connection_config(server_id, email, db_session)
        source_config = existing_config or mcp_server.admin_connection_config
        source_data = extract_connection_data(source_config, apply_mask=False)
        for oauth_key in MCPOAuthKeys:
            field_key: Literal[
                "client_info", "tokens", "metadata", "token_expires_at"
            ] = oauth_key.value
            if field_value := source_data.get(field_key):
                config_data[field_key] = field_value

    validation_tested = False
    validation_message = "Credentials saved successfully"
    if mcp_server.auth_type != MCPAuthenticationType.OAUTH:
        validation_headers = config_data["headers"]
        if mcp_server.auth_type == MCPAuthenticationType.PT_OAUTH:
            if not user.oauth_accounts:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "Pass-through OAuth requires an OAuth login.",
                )
            validation_headers = merge_mcp_headers(
                validation_headers,
                {"Authorization": f"Bearer {user.oauth_accounts[0].access_token}"},
            )
        is_valid, test_message = test_mcp_server_credentials(
            mcp_server.server_url,
            validation_headers,
            transport=MCPTransport(request.transport.replace("-", "_").upper()),
            auth=None,
        )
        validation_tested = True
        if not is_valid:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Credentials validation failed: {test_message}",
            )
        validation_message = (
            f"Credentials saved and validated successfully. {test_message}"
        )

    upsert_user_connection_config(
        server_id=server_id,
        user_email=email,
        config_data=config_data,
        db_session=db_session,
    )
    db_session.commit()
    _hot_reload_craft_sessions({user.id}, db_session)

    resolved = resolve_mcp_credentials(mcp_server, user, db_session)
    return MCPApiKeyResponse(
        success=True,
        message=validation_message,
        server_id=request.server_id,
        server_name=mcp_server.name,
        authenticated=resolved.can_authenticate(),
        validation_tested=validation_tested,
    )


@router.delete("/user-credentials/{server_id}")
def delete_user_credentials(
    server_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPApiKeyResponse:
    """Disconnect the caller from an MCP server: remove their own connection
    configs (OAuth tokens / API keys). Admin template rows are untouched."""
    try:
        mcp_server = get_mcp_server_by_id(server_id, db_session)
    except ValueError:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "MCP server not found")

    # The helper commits internally.
    delete_user_connection_configs_for_server(server_id, user.email, db_session)

    # Disconnecting revokes tool discovery for this user; reload their craft
    # session (single sandbox — this user only) so the next turn drops it.
    _hot_reload_craft_sessions({user.id}, db_session)

    return MCPApiKeyResponse(
        success=True,
        message="Disconnected",
        server_id=server_id,
        server_name=mcp_server.name,
        authenticated=False,
    )


class MCPToolDescription(BaseModel):
    id: int
    name: str
    display_name: str
    description: str


class ServerToolsResponse(BaseModel):
    server_id: int
    server_name: str
    server_url: str
    tools: list[MCPToolDescription]


def _ensure_mcp_server_owner_or_admin(server: DbMCPServer, user: User) -> None:
    """GATE 2 for every MCP server mutation. Delegates to the predicate the projection
    stamps, so the UI can't offer a control this rejects. A FULL_ADMIN check here would
    be stricter than the read gate below, which counts global MANAGE_ACTIONS."""
    if can_manage_mcp_server(user, server):
        return
    logger.warning(
        "Denied MCP server management: user=%s server=%s owner=%s",
        user.email,
        server.name,
        server.owner,
    )
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "Only the server owner can modify MCP servers they have created.",
    )


def _ensure_mcp_server_viewable(
    server: DbMCPServer, user: User, db_session: Session
) -> None:
    """Read gate for a single MCP server: a global MANAGE_ACTIONS holder (incl. admins) views
    any; an owner views their own; a scoped manager views a server connected to their groups
    via an agent. Managers may view connected servers without managing them; managing is
    owner-or-admin (``_ensure_mcp_server_owner_or_admin``)."""
    authority = has_permission(user, Permission.MANAGE_ACTIONS)
    if authority is PermissionAuthority.GLOBAL:
        return
    if server.owner == user.email:
        return
    if authority is PermissionAuthority.SCOPED:
        managed = get_scoped_groups(user, db_session, Permission.MANAGE_ACTIONS)
        if server.id in get_mcp_server_ids_connected_to_groups(managed, db_session):
            return
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "You can only view MCP servers you own or that are connected to your groups.",
    )


def _db_mcp_server_to_api_mcp_server(
    db_server: DbMCPServer,
    db: Session,
    request_user: User | None,
    include_auth_config: bool = False,
    permissions: dict[str, bool] | None = None,
    craft_connected: bool | None = None,
    user_configs: Mapping[int, MCPConnectionConfig] | None = None,
) -> MCPServer:
    """Convert database MCP server to API model.

    `user_configs` lets a caller converting many servers pre-load the per-user
    credential rows in one query (see `get_user_connection_configs`) instead of
    one per server. It must cover every server the caller converts — a miss reads
    as no stored credential, not as unknown.
    """

    email = request_user.email if request_user else ""

    # Check if user has authentication configured and extract credentials
    auth_performer = db_server.auth_performer
    can_authenticate: bool | None = None
    user_credentials = None
    admin_credentials = None
    is_owner_or_admin = request_user is not None and (
        Permission.FULL_ADMIN_PANEL_ACCESS in get_effective_permissions(request_user)
        or (request_user.email and request_user.email == db_server.owner)
    )
    can_view_admin_credentials = bool(include_auth_config) and is_owner_or_admin
    # The internal server_url and the owner email are sensitive: expose them only
    # to the server's owner or an admin. Basic users attaching MCP actions to an
    # assistant don't need either (the connect/OAuth flow is brokered server-side).
    can_view_server_details = is_owner_or_admin
    user_config = (
        user_configs.get(db_server.id)
        if user_configs is not None
        else get_user_connection_config(db_server.id, email, db)
    )
    if request_user is not None:
        can_authenticate = user_can_authenticate(
            db_server,
            request_user,
            db,
            user_configs=({db_server.id: user_config} if user_config else {}),
        )

    if include_auth_config and user_config is not None:
        user_config_dict = extract_connection_data(user_config, apply_mask=True)
        user_credentials = user_config_dict.get(HEADER_SUBSTITUTIONS, {})

    if can_view_admin_credentials and db_server.admin_connection_config is not None:
        admin_config_dict = extract_connection_data(
            db_server.admin_connection_config, apply_mask=False
        )
        if (
            db_server.auth_type == MCPAuthenticationType.API_TOKEN
            and auth_performer == MCPAuthenticationPerformer.ADMIN
        ):
            admin_credentials = {
                key: mask_string(value)
                for key, value in admin_config_dict.get(
                    HEADER_SUBSTITUTIONS, {}
                ).items()
            }
            admin_credentials.update(
                {"api_key": mask_string(_extract_shared_api_token(admin_config_dict))}
            )
        elif db_server.auth_type == MCPAuthenticationType.OAUTH:
            client_info_raw = admin_config_dict.get(MCPOAuthKeys.CLIENT_INFO.value)
            client_info = (
                OAuthClientInformationFull.model_validate(client_info_raw)
                if client_info_raw
                else None
            )
            admin_credentials = {}
            if client_info is not None:
                if not client_info.client_id:
                    raise ValueError("Stored client info had empty client ID")
                admin_credentials["client_id"] = mask_string(client_info.client_id)
                if client_info.client_secret:
                    admin_credentials["client_secret"] = mask_string(
                        client_info.client_secret
                    )

    stored_template = get_mcp_auth_template(db_server)
    auth_template = None
    if stored_template is not None:
        shared_api_token = (
            db_server.auth_type == MCPAuthenticationType.API_TOKEN
            and auth_performer == MCPAuthenticationPerformer.ADMIN
        )
        if can_view_admin_credentials:
            auth_template = _mask_auth_template(stored_template)
        elif not shared_api_token:
            auth_template = MCPAuthTemplate(
                headers={},
                required_fields=stored_template.required_fields,
            )

    # Calculate tool count from the relationship
    tool_count = len(db_server.current_actions) if db_server.current_actions else 0

    return MCPServer(
        id=db_server.id,
        name=db_server.name,
        description=db_server.description,
        server_url=db_server.server_url if can_view_server_details else "",
        owner=db_server.owner if can_view_server_details else "",
        transport=db_server.transport,
        auth_type=db_server.auth_type,
        auth_performer=auth_performer,
        oauth_provider_mode=db_server.oauth_provider_mode,
        oauth_authorization_endpoint=db_server.oauth_authorization_endpoint,
        oauth_token_endpoint=db_server.oauth_token_endpoint,
        oauth_scopes_override=db_server.oauth_scopes_override,
        oauth_additional_auth_params=db_server.oauth_additional_auth_params,
        user_can_authenticate=can_authenticate,
        craft_connected=craft_connected,
        status=db_server.status,
        is_public=db_server.is_public,
        groups=[group.id for group in db_server.user_groups],
        users=[user.id for user in db_server.users],
        available_in_craft=db_server.available_in_craft,
        tool_policies=(
            get_action_policies(db, GatedAppKind.MCP_SERVER, db_server.id)
            if can_view_server_details
            else None
        ),
        last_refreshed_at=db_server.last_refreshed_at,
        tool_count=tool_count,
        auth_template=auth_template,
        user_credentials=user_credentials,
        admin_credentials=admin_credentials,
        permissions=permissions or {},
    )


@router.get("/servers/persona/{assistant_id}", response_model=MCPServersResponse)
def get_mcp_servers_for_assistant(
    assistant_id: str,
    db: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPServersResponse:
    """Get MCP servers for an assistant"""

    logger.info("Fetching MCP servers for assistant: %s", assistant_id)

    try:
        persona_id = int(assistant_id)
        db_mcp_servers = get_mcp_servers_for_persona(persona_id, db, user)

        # Convert to API model format with opportunistic token refresh for OAuth
        mcp_servers = [
            _db_mcp_server_to_api_mcp_server(db_server, db, request_user=user)
            for db_server in db_mcp_servers
        ]

        return MCPServersResponse(assistant_id=assistant_id, mcp_servers=mcp_servers)

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid assistant ID")
    except Exception as e:
        logger.error("Failed to fetch MCP servers: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch MCP servers")


@router.get("/servers", response_model=MCPServersResponse)
def get_mcp_servers_for_user(
    db: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPServersResponse:
    """Attach catalog: servers this user may put on a persona (public / direct / group).

    Chat uses ``/servers/persona/{id}`` for servers already on a persona.
    """
    db_mcp_servers = get_mcp_servers_accessible_to_user(user, db)
    mcp_servers = [
        _db_mcp_server_to_api_mcp_server(db_server, db, request_user=user)
        for db_server in db_mcp_servers
    ]
    return MCPServersResponse(mcp_servers=mcp_servers)


@router.get("/servers/craft", response_model=MCPServersResponse)
def get_craft_mcp_servers_for_user(
    db: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPServersResponse:
    """List MCP servers an admin has made available to the Craft agent, with
    the current user's connection/auth state. Craft reads the same credential
    rows as chat, so a server connected in either surface shows as
    authenticated here.

    `craft_connected` is the only field here that answers "will this server
    actually reach the user's sessions" — see `resolve_craft_mcp_servers`, which
    filters emission on the same predicate.
    """
    db_mcp_servers = get_craft_enabled_mcp_servers(db, user)
    user_configs = get_user_connection_configs(
        [s.id for s in db_mcp_servers], user.email, db
    )
    mcp_servers = [
        _db_mcp_server_to_api_mcp_server(
            db_server,
            db,
            request_user=user,
            craft_connected=user_can_authenticate(
                db_server, user, db, user_configs=user_configs
            ),
            user_configs=user_configs,
        )
        for db_server in db_mcp_servers
    ]
    return MCPServersResponse(mcp_servers=mcp_servers)


@admin_router.get("/server/{server_id}/tools")
def admin_list_mcp_tools_by_id(
    server_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> MCPToolListResponse:
    return _list_mcp_tools_by_id(server_id, db, True, user)


class ToolSnapshotSource(str, Enum):
    DB = "db"
    MCP = "mcp"


@admin_router.get("/server/{server_id}/tools/snapshots")
def get_mcp_server_tools_snapshots(
    server_id: int,
    source: ToolSnapshotSource = ToolSnapshotSource.DB,
    db: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> list[ToolSnapshot]:
    """
    Get tools for an MCP server as ToolSnapshot objects.

    Query Parameters:
    - source: "db" (default) - fetch from database only, "mcp" - discover from MCP server and sync to DB

    Returns: List of ToolSnapshot objects
    """
    from onyx.db.tools import get_tools_by_mcp_server_id

    try:
        # Verify the server exists
        mcp_server = get_mcp_server_by_id(server_id, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    if source == ToolSnapshotSource.MCP:
        _ensure_mcp_server_owner_or_admin(mcp_server, user)
        try:
            # Discover tools from MCP server and sync to DB
            _list_mcp_tools_by_id(server_id, db, True, user)

            # Successfully discovered tools, update status to CONNECTED
            update_mcp_server__no_commit(
                server_id=server_id,
                db_session=db,
                status=MCPServerStatus.CONNECTED,
                last_refreshed_at=datetime.datetime.now(datetime.timezone.utc),
            )
            db.commit()
        except Exception as e:
            update_mcp_server__no_commit(
                server_id=server_id,
                db_session=db,
                status=MCPServerStatus.AWAITING_AUTH,
            )
            db.commit()

            if isinstance(e, (HTTPException, OnyxError)):
                # Preserve structured client errors after updating the server status.
                raise

            logger.error("Failed to discover tools for MCP server: %s", e)
            raise HTTPException(status_code=500, detail="Failed to discover tools")
    else:
        _ensure_mcp_server_viewable(mcp_server, user, db)

    # Same predicate the status route enforces, so the UI can't offer a toggle that 403s.
    mcp_tools = get_tools_by_mcp_server_id(server_id, db, order_by_id=True)
    return [
        ToolSnapshot.from_model(
            tool,
            permissions=tool_permissions(can_manage=can_manage_tool(user, tool)),
        )
        for tool in mcp_tools
    ]


@router.get("/server/{server_id}/tools")
def user_list_mcp_tools_by_id(
    server_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPToolListResponse:
    return _list_mcp_tools_by_id(server_id, db, False, user)


def _upsert_db_tools(
    discovered_tools: list[MCPLibTool],
    existing_by_name: dict[str, Tool],
    processed_names: set[str],
    mcp_server_id: int,
    db: Session,
) -> bool:
    db_dirty = False

    for tool in discovered_tools:
        tool_name = tool.name
        if not tool_name:
            continue

        processed_names.add(tool_name)
        description = tool.description or ""
        annotations_title = tool.annotations.title if tool.annotations else None
        display_name = tool.title or annotations_title or tool_name
        input_schema = tool.inputSchema

        if existing_tool := existing_by_name.get(tool_name):
            if existing_tool.description != description:
                existing_tool.description = description
                db_dirty = True
            if existing_tool.display_name != display_name:
                existing_tool.display_name = display_name
                db_dirty = True
            if existing_tool.mcp_input_schema != input_schema:
                existing_tool.mcp_input_schema = input_schema
                db_dirty = True
            continue

        new_tool = create_tool__no_commit(
            name=tool_name,
            description=description,
            openapi_schema=None,
            custom_headers=None,
            user_id=None,
            db_session=db,
            passthrough_auth=False,
            mcp_server_id=mcp_server_id,
            enabled=True,
        )
        new_tool.display_name = display_name
        new_tool.mcp_input_schema = input_schema
        db_dirty = True
    return db_dirty


def _list_mcp_tools_by_id(
    server_id: int,
    db: Session,
    is_admin: bool,
    user: User,
) -> MCPToolListResponse:
    """List available tools from an existing MCP server"""
    logger.info("Listing tools for MCP server: %s", server_id)

    try:
        # Get the MCP server
        mcp_server = get_mcp_server_by_id(server_id, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    if is_admin:
        _ensure_mcp_server_owner_or_admin(mcp_server, user)
    elif not user_can_access_mcp_server(user, server_id, db):
        # Attach-catalog only: don't IDOR private servers / outbound-connect.
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "You do not have access to this MCP server.",
        )

    credentials = resolve_mcp_credentials(mcp_server, user, db)
    if not credentials.can_authenticate():
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED,
            "This MCP server is not configured for the current user.",
        )
    auth = None
    if mcp_server.auth_type == MCPAuthenticationType.OAUTH:
        connection_config = credentials.connection_config
        if connection_config is None:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "OAuth MCP credentials are missing their connection config.",
            )
        auth = make_oauth_provider(
            mcp_server,
            connection_config.id,
            None,
        )

    t1 = time.time()
    logger.info("Discovering tools for MCP server: %s: %s", mcp_server.name, t1)
    server_url = mcp_server.server_url

    if mcp_server.transport is None:
        raise HTTPException(
            status_code=400,
            detail="MCP server transport is not configured",
        )

    try:
        discovered_tools = discover_mcp_tools(
            server_url,
            credentials.build_headers(),
            transport=mcp_server.transport,
            auth=auth,
        )
    except MCPReauthenticationRequired as error:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED, str(error)) from error
    logger.info(
        "Discovered %s tools for MCP server: %s: %s",
        len(discovered_tools),
        mcp_server.name,
        time.time() - t1,
    )
    update_mcp_server__no_commit(
        server_id=server_id,
        db_session=db,
        status=MCPServerStatus.CONNECTED,
    )
    db.commit()

    if is_admin:
        existing_tools = get_tools_by_mcp_server_id(mcp_server.id, db)
        existing_by_name = {db_tool.name: db_tool for db_tool in existing_tools}
        processed_names: set[str] = set()

        db_dirty = _upsert_db_tools(
            discovered_tools, existing_by_name, processed_names, mcp_server.id, db
        )

        for name, db_tool in existing_by_name.items():
            if name not in processed_names:
                delete_tool__no_commit(db_tool.id, db)
                db_dirty = True

        if db_dirty:
            db.commit()

    # Truncate tool descriptions to prevent overly long responses
    for tool in discovered_tools:
        if tool.description:
            tool.description = _truncate_description(tool.description)

    # TODO: Also list resources from the MCP server
    # resources = discover_mcp_resources(mcp_server, connection_config)

    return MCPToolListResponse(
        server_id=server_id,
        server_name=mcp_server.name,
        server_url=mcp_server.server_url,
        tools=discovered_tools,
    )


def _apply_mcp_server_access(
    *,
    mcp_server: DbMCPServer,
    acting_user: User,
    is_public: bool | None,
    user_ids: list[UUID] | None,
    group_ids: list[int] | None,
    is_new: bool,
    db_session: Session,
) -> None:
    """Validate the acting user may assign these groups (EE; no-op in MIT), set
    the public flag, and reconcile the user/group access rows (EE write). Public
    servers clear any existing grants."""
    is_public = mcp_server.is_public if is_public is None else is_public
    if not is_public and not global_version.is_ee_version():
        raise OnyxError(
            OnyxErrorCode.EE_REQUIRED,
            "Restricting MCP servers to specific users or groups requires "
            "Enterprise Edition.",
        )

    # GATE 2 — reaching here only proves the caller may manage this server, and the
    # creator is its owner, so nothing else stops a scoped manager attaching a group
    # they do not manage (or publishing it org-wide). Current groups come from the DB,
    # never the request.
    assert_within_scope(
        acting_user,
        db_session,
        permission=Permission.MANAGE_ACTIONS,
        current_group_ids=[] if is_new else [g.id for g in mcp_server.user_groups],
        requested_group_ids=group_ids or [],
        is_non_public=not is_public,
    )
    mcp_server.is_public = is_public
    fetch_versioned_implementation("onyx.db.mcp", "make_mcp_server_private")(
        server_id=mcp_server.id,
        user_ids=[] if is_public else user_ids,
        group_ids=[] if is_public else group_ids,
        db_session=db_session,
    )


def _invalidate_mcp_user_credentials(
    mcp_server: DbMCPServer, db_session: Session
) -> set[UUID]:
    affected_users = affected_user_ids_for_mcp_server(mcp_server, db_session)
    delete_all_user_connection_configs_for_server_no_commit(mcp_server.id, db_session)
    return affected_users


def _upsert_mcp_server(
    request: MCPToolCreateRequest,
    db_session: Session,
    user: User,
) -> DbMCPServer:
    """
    Creates a new or edits an existing MCP server. Returns the DB model
    """
    _validate_mcp_server_url(request.server_url, "server_url", require_https=False)
    _validate_mcp_server_url(
        request.oauth_authorization_endpoint,
        "oauth_authorization_endpoint",
        require_https=True,
    )
    _validate_mcp_server_url(
        request.oauth_token_endpoint, "oauth_token_endpoint", require_https=True
    )

    mcp_server = None
    admin_config = None
    client_info: OAuthClientInformationFull | None = None
    oauth_client_id = request.oauth_client_id
    oauth_client_secret = request.oauth_client_secret
    auth_template = request.auth_template
    admin_credentials = request.admin_credentials
    api_token = request.api_token

    changing_connection_config = True
    users_to_reload: set[UUID] = set()

    # Handle existing server update
    if request.existing_server_id:
        try:
            mcp_server = get_mcp_server_by_id(request.existing_server_id, db_session)
        except ValueError:
            raise HTTPException(
                status_code=404,
                detail=f"MCP server with ID {request.existing_server_id} not found",
            )
        _ensure_mcp_server_owner_or_admin(mcp_server, user)
        existing_admin_config_dict: MCPConnectionData = MCPConnectionData(headers={})
        if mcp_server.admin_connection_config:
            existing_admin_config_dict = extract_connection_data(
                mcp_server.admin_connection_config, apply_mask=False
            )
            client_info_raw = existing_admin_config_dict.get(
                MCPOAuthKeys.CLIENT_INFO.value
            )
            if client_info_raw:
                client_info = OAuthClientInformationFull.model_validate(client_info_raw)

        # Resolve the effective OAuth credentials, falling back to the stored
        # values for any field the frontend marked as unchanged. This protects
        # the change-detection comparison below from spurious diffs caused by
        # masked placeholders being replayed.
        if client_info and request.auth_type == MCPAuthenticationType.OAUTH:
            oauth_client_id, oauth_client_secret = _resolve_oauth_credentials(
                request_client_id=request.oauth_client_id,
                request_client_id_changed=request.oauth_client_id_changed,
                request_client_secret=request.oauth_client_secret,
                request_client_secret_changed=request.oauth_client_secret_changed,
                existing_client=client_info,
            )

        # Resolve the editing admin's own template values per field.
        existing_admin_per_user_creds: dict[str, str] = {}
        existing_template_headers: dict[str, str] = {}
        existing_shared_template_headers: dict[str, str] = {}
        existing_template: MCPAuthTemplate | None = None
        if mcp_server.admin_connection_config:
            existing_template = get_mcp_auth_template(mcp_server)
            existing_template_headers = (
                existing_template.headers if existing_template else {}
            )
            existing_shared_template_headers = (
                existing_admin_config_dict.get("header_template")
                or _default_shared_api_token_template().headers
            )
            if auth_template is not None:
                auth_template = _resolve_auth_template(
                    auth_template,
                    request.auth_template_headers_changed,
                    existing_template,
                )
            elif existing_template is not None:
                auth_template = existing_template

        if (
            request.auth_type == MCPAuthenticationType.API_TOKEN
            and request.auth_performer == MCPAuthenticationPerformer.ADMIN
        ):
            if admin_credentials is not None:
                admin_credentials = _resolve_admin_credentials(
                    request_credentials=admin_credentials,
                    request_credentials_changed=request.admin_credentials_changed,
                    existing_user_credentials=existing_admin_config_dict.get(
                        HEADER_SUBSTITUTIONS, {}
                    ),
                )
            auth_template = _resolve_shared_api_token_template(
                request_template=auth_template,
                existing_config=(
                    existing_admin_config_dict
                    if mcp_server.admin_connection_config
                    else None
                ),
            )
            api_token = _resolve_shared_api_token(
                request_api_token=api_token,
                request_api_token_changed=request.api_token_changed,
                existing_config=(
                    existing_admin_config_dict
                    if mcp_server.admin_connection_config
                    else None
                ),
            )
            # The validator allows an omitted token on update so the stored
            # one can be reused; enforce that a token actually resolved.
            if not api_token:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "A shared API token is required for admin-managed API-token servers.",
                )
        if (
            not (
                request.auth_type == MCPAuthenticationType.API_TOKEN
                and request.auth_performer == MCPAuthenticationPerformer.ADMIN
            )
            and user.email
        ):
            existing_admin_per_user_config = get_user_connection_config(
                mcp_server.id, user.email, db_session
            )
            if existing_admin_per_user_config:
                existing_admin_per_user_dict = extract_connection_data(
                    existing_admin_per_user_config, apply_mask=False
                )
                existing_admin_per_user_creds = (
                    existing_admin_per_user_dict.get(HEADER_SUBSTITUTIONS) or {}
                )
            if admin_credentials is not None:
                admin_credentials = _resolve_admin_credentials(
                    request_credentials=admin_credentials,
                    request_credentials_changed=request.admin_credentials_changed,
                    existing_user_credentials=existing_admin_per_user_creds,
                )

        api_token_creds_changed = (
            request.auth_type == MCPAuthenticationType.API_TOKEN
            and request.auth_performer == MCPAuthenticationPerformer.PER_USER
            and existing_admin_per_user_creds != (admin_credentials or {})
        )
        header_template_changed = (
            not (
                request.auth_type == MCPAuthenticationType.API_TOKEN
                and request.auth_performer == MCPAuthenticationPerformer.ADMIN
            )
            and auth_template is not None
            and auth_template.headers != existing_template_headers
        )
        shared_api_token_template_changed = (
            request.auth_type == MCPAuthenticationType.API_TOKEN
            and request.auth_performer == MCPAuthenticationPerformer.ADMIN
            and auth_template is not None
            and auth_template.headers != existing_shared_template_headers
        )
        shared_api_token_credentials_changed = (
            request.auth_type == MCPAuthenticationType.API_TOKEN
            and request.auth_performer == MCPAuthenticationPerformer.ADMIN
            and admin_credentials is not None
            and admin_credentials
            != existing_admin_config_dict.get(HEADER_SUBSTITUTIONS, {})
        )
        api_token_scheme_changed = (
            request.auth_type == MCPAuthenticationType.API_TOKEN
            and (
                request.auth_type != mcp_server.auth_type
                or request.auth_performer != mcp_server.auth_performer
            )
        )
        auth_scheme_changed = (
            request.auth_type != mcp_server.auth_type
            or request.auth_performer != mcp_server.auth_performer
        )
        server_url_changed = request.server_url != mcp_server.server_url
        # Known-provider OAuth settings (endpoints/mode/scopes/extra params)
        # determine where and with what scope user tokens are minted. A change
        # to any of them invalidates existing user tokens, so it must trigger
        # the same re-handshake wipe as a client_id/secret change.
        oauth_provider_config_changed = (
            request.auth_type == MCPAuthenticationType.OAUTH
            and (
                request.oauth_provider_mode != mcp_server.oauth_provider_mode
                or request.oauth_authorization_endpoint
                != mcp_server.oauth_authorization_endpoint
                or request.oauth_token_endpoint != mcp_server.oauth_token_endpoint
                or request.oauth_scopes_override != mcp_server.oauth_scopes_override
                or request.oauth_additional_auth_params
                != mcp_server.oauth_additional_auth_params
            )
        )

        changing_connection_config = (
            not mcp_server.admin_connection_config
            or (
                request.auth_type == MCPAuthenticationType.OAUTH
                and (
                    client_info is None
                    or oauth_client_id != client_info.client_id
                    or oauth_client_secret != (client_info.client_secret or "")
                    or oauth_provider_config_changed
                )
            )
            or (
                request.auth_type == MCPAuthenticationType.API_TOKEN
                and (
                    api_token_creds_changed
                    or header_template_changed
                    or shared_api_token_template_changed
                    or shared_api_token_credentials_changed
                    or (
                        request.auth_performer == MCPAuthenticationPerformer.ADMIN
                        and request.api_token_changed
                    )
                    or api_token_scheme_changed
                )
            )
            or header_template_changed
            or auth_scheme_changed
            or server_url_changed
            or (request.transport != mcp_server.transport)
        )

        if header_template_changed or auth_scheme_changed or server_url_changed:
            users_to_reload.update(
                _invalidate_mcp_user_credentials(mcp_server, db_session)
            )

        if server_url_changed and mcp_server.admin_connection_config_id:
            previous_admin_config_id = mcp_server.admin_connection_config_id
            mcp_server.admin_connection_config_id = None
            delete_connection_config(previous_admin_config_id, db_session)
            if (
                request.auth_type == MCPAuthenticationType.OAUTH
                and request.oauth_provider_mode is MCPOAuthProviderMode.AUTO_DISCOVERY
            ):
                client_info = None
                if not request.oauth_client_id_changed:
                    oauth_client_id = None
                if not request.oauth_client_secret_changed:
                    oauth_client_secret = None
        elif (
            changing_connection_config
            and mcp_server.admin_connection_config_id
            and request.auth_type == MCPAuthenticationType.OAUTH
            and not header_template_changed
            and not auth_scheme_changed
        ):
            users_to_reload.update(
                _invalidate_mcp_user_credentials(mcp_server, db_session)
            )
        elif (
            changing_connection_config
            and mcp_server.admin_connection_config_id
            and request.auth_type == MCPAuthenticationType.API_TOKEN
        ):
            delete_connection_config(mcp_server.admin_connection_config_id, db_session)

        # Update the server with new values
        mcp_server = update_mcp_server__no_commit(
            server_id=request.existing_server_id,
            db_session=db_session,
            name=request.name,
            description=request.description,
            server_url=request.server_url,
            auth_type=request.auth_type,
            auth_performer=request.auth_performer,
            oauth_provider_mode=request.oauth_provider_mode,
            oauth_authorization_endpoint=request.oauth_authorization_endpoint,
            oauth_token_endpoint=request.oauth_token_endpoint,
            oauth_scopes_override=request.oauth_scopes_override,
            oauth_additional_auth_params=request.oauth_additional_auth_params,
            transport=request.transport,
        )

        logger.info(
            "Updated existing MCP server '%s' with ID %s", request.name, mcp_server.id
        )

    else:
        # Handle new server creation
        if auth_template is not None:
            auth_template = _resolve_auth_template(
                auth_template,
                request.auth_template_headers_changed,
                None,
            )
        # Prevent duplicate server creation with same URL
        normalized_url = (request.server_url or "").strip()
        if not normalized_url:
            raise HTTPException(status_code=400, detail="server_url is required")

        if not user.email:
            raise HTTPException(
                status_code=400,
                detail="Authenticated user email required to create MCP servers",
            )

        mcp_server = create_mcp_server__no_commit(
            owner_email=user.email,
            name=request.name,
            description=request.description,
            server_url=request.server_url,
            auth_type=request.auth_type,
            auth_performer=request.auth_performer,
            oauth_provider_mode=request.oauth_provider_mode,
            oauth_authorization_endpoint=request.oauth_authorization_endpoint,
            oauth_token_endpoint=request.oauth_token_endpoint,
            oauth_scopes_override=request.oauth_scopes_override,
            oauth_additional_auth_params=request.oauth_additional_auth_params,
            transport=request.transport or MCPTransport.STREAMABLE_HTTP,
            db_session=db_session,
        )

        logger.info(
            "Created new MCP server '%s' with ID %s", request.name, mcp_server.id
        )

    # A new server defaults to public (create_mcp_server__no_commit), so always run the
    # access gate on create — otherwise a scoped manager could publish one org-wide by
    # omitting is_public/users/groups. On update, only touch access when the caller sent it.
    is_new_server = request.existing_server_id is None
    if is_new_server or any(
        value is not None
        for value in (request.is_public, request.users, request.groups)
    ):
        _apply_mcp_server_access(
            mcp_server=mcp_server,
            acting_user=user,
            is_public=request.is_public,
            user_ids=request.users,
            group_ids=request.groups,
            is_new=is_new_server,
            db_session=db_session,
        )

    if (
        auth_template is not None
        and admin_credentials is not None
        and not (
            request.auth_type == MCPAuthenticationType.API_TOKEN
            and request.auth_performer == MCPAuthenticationPerformer.ADMIN
        )
    ):
        _upsert_user_template_config(
            mcp_server=mcp_server,
            template=auth_template,
            substitutions=admin_credentials,
            user_email=user.email,
            db_session=db_session,
        )
        users_to_reload.add(user.id)

    if not changing_connection_config:
        db_session.commit()
        _hot_reload_craft_sessions(users_to_reload, db_session)
        return mcp_server

    admin_connection_config_id: int | None = None
    if (
        request.auth_type == MCPAuthenticationType.API_TOKEN
        and request.auth_performer == MCPAuthenticationPerformer.ADMIN
        and api_token
    ):
        admin_config = create_connection_config(
            config_data=_build_shared_api_token_config_data(
                api_token=api_token,
                auth_template=auth_template,
                header_substitutions=admin_credentials,
                user_email=user.email,
            ),
            mcp_server_id=mcp_server.id,
            db_session=db_session,
        )
        admin_connection_config_id = admin_config.id

    elif request.auth_type == MCPAuthenticationType.API_TOKEN:
        if auth_template is None:
            raise OnyxError(
                OnyxErrorCode.MISSING_REQUIRED_FIELD,
                "Per-user API-token servers require a header template.",
            )
        admin_connection_config_id = create_connection_config(
            config_data=_build_template_config_data(auth_template),
            mcp_server_id=mcp_server.id,
            db_session=db_session,
        ).id

    elif request.auth_type == MCPAuthenticationType.OAUTH:
        config_data = (
            _build_oauth_admin_config_data_for_update(
                client_id=oauth_client_id,
                client_secret=oauth_client_secret,
                existing_client=client_info,
                auth_template=auth_template,
            )
            if client_info is not None
            else _build_oauth_admin_config_data(
                client_id=oauth_client_id,
                client_secret=oauth_client_secret,
                auth_template=auth_template,
            )
        )
        admin_connection_config_id = _persist_admin_connection_config(
            mcp_server, config_data, db_session
        )

    else:
        config_data = _build_template_config_data(auth_template)
        admin_connection_config_id = _persist_admin_connection_config(
            mcp_server, config_data, db_session
        )
    if admin_connection_config_id is not None:
        mcp_server = update_mcp_server__no_commit(
            server_id=mcp_server.id,
            db_session=db_session,
            admin_connection_config_id=admin_connection_config_id,
        )

    db_session.commit()
    _hot_reload_craft_sessions(users_to_reload, db_session)
    return mcp_server


def _sync_tools_for_server(
    mcp_server: DbMCPServer,
    selected_tools: set[str],
    db_session: Session,
) -> int:
    """Toggle enabled state for MCP tools that exist for the server.
    Updates to the db model of a tool all happen when the user Lists Tools.
    This ensures that the the tools added to the db match what the user sees in the UI,
    even if the underlying tool has changed on the server after list tools is called.
    That's a corner case anyways; the admin should go back and update the server by re-listing tools.
    """

    updated_tools = 0

    existing_tools = get_tools_by_mcp_server_id(mcp_server.id, db_session)
    existing_by_name = {tool.name: tool for tool in existing_tools}

    # Disable any existing tools that were not processed above
    for tool_name, db_tool in existing_by_name.items():
        should_enable = tool_name in selected_tools
        if db_tool.enabled != should_enable:
            db_tool.enabled = should_enable
            updated_tools += 1

    return updated_tools


@admin_router.get("/servers/{server_id}", response_model=MCPServer)
def get_mcp_server_detail(
    server_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> MCPServer:
    """Return details for one MCP server if user has access"""
    try:
        server = get_mcp_server_by_id(server_id, db_session)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    # Read gate: owner, admin, or a manager of a group the server is connected to.
    _ensure_mcp_server_viewable(server, user, db_session)
    # TODO: user permissions per mcp server not yet implemented, for now
    # permissions are based on access to assistants
    # # Quick permission check – admin or user has access
    # if user and server not in user.accessible_mcp_servers and not user.is_superuser:
    #     raise HTTPException(status_code=403, detail="Forbidden")
    return _db_mcp_server_to_api_mcp_server(
        server,
        db_session,
        include_auth_config=True,
        request_user=user,
        permissions=mcp_server_permissions(
            can_manage=can_manage_mcp_server(user, server),
        ),
    )


@admin_router.get("/tools")
def get_all_mcp_tools(
    db: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> list:
    """Get all tools associated with MCP servers, including both enabled and disabled tools"""
    from sqlalchemy import select

    # Query MCP tools ordered by ID to maintain consistent ordering
    stmt = select(Tool).where(Tool.mcp_server_id.is_not(None)).order_by(Tool.id)

    # Scope-match the /servers list: a scoped manager only sees tools on servers they own or
    # that a group they manage is connected to; a global holder sees every server's tools.
    if (
        has_permission(user, Permission.MANAGE_ACTIONS)
        is not PermissionAuthority.GLOBAL
    ):
        connected = get_mcp_server_ids_connected_to_groups(
            get_scoped_groups(user, db, Permission.MANAGE_ACTIONS), db
        )
        visible_server_ids = {
            server.id
            for server in get_all_mcp_servers(db)
            if server.owner == user.email or server.id in connected
        }
        stmt = stmt.where(Tool.mcp_server_id.in_(visible_server_ids))

    mcp_tools = db.scalars(stmt).all()

    # Convert to ToolSnapshot format
    return [ToolSnapshot.from_model(tool) for tool in mcp_tools]


@admin_router.patch("/server/{server_id}/status")
def update_mcp_server_status(
    server_id: int,
    status: MCPServerStatus,
    db: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> dict[str, str]:
    """Update the status of an MCP server"""
    logger.info("Updating MCP server %s status to %s", server_id, status)

    try:
        mcp_server = get_mcp_server_by_id(server_id, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(mcp_server, user)

    update_mcp_server__no_commit(
        server_id=server_id,
        db_session=db,
        status=status,
    )
    db.commit()

    logger.info("Successfully updated MCP server %s status to %s", server_id, status)
    return {"message": f"Server status updated to {status.value}"}


@admin_router.get("/servers", response_model=MCPServersResponse)
def get_mcp_servers_for_admin(
    db: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> MCPServersResponse:
    """Get all MCP servers for admin display"""

    logger.info("Fetching all MCP servers for admin display")

    try:
        db_mcp_servers = get_all_mcp_servers(db)

        # A global MANAGE_ACTIONS holder (incl. admins) sees every server; a scoped manager
        # sees only those they own or that are connected to a group they manage (one query for
        # the connected set). Managing is owner-or-admin either way (can_manage_mcp_server).
        if (
            has_permission(user, Permission.MANAGE_ACTIONS)
            is PermissionAuthority.GLOBAL
        ):
            visible_servers = db_mcp_servers
        else:
            connected = get_mcp_server_ids_connected_to_groups(
                get_scoped_groups(user, db, Permission.MANAGE_ACTIONS), db
            )
            visible_servers = [
                server
                for server in db_mcp_servers
                if server.owner == user.email or server.id in connected
            ]

        mcp_servers = [
            _db_mcp_server_to_api_mcp_server(
                db_server,
                db,
                request_user=user,
                permissions=mcp_server_permissions(
                    can_manage=can_manage_mcp_server(user, db_server),
                ),
            )
            for db_server in visible_servers
        ]

        return MCPServersResponse(mcp_servers=mcp_servers)

    except Exception as e:
        logger.error("Failed to fetch MCP servers for admin: %s:%s", type(e), e)
        raise HTTPException(status_code=500, detail="Failed to fetch MCP servers")


@admin_router.get("/server/{server_id}/db-tools")
def get_mcp_server_db_tools(
    server_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> ServerToolsResponse:
    """Get existing database tools created for an MCP server"""
    logger.info("Getting database tools for MCP server: %s", server_id)

    try:
        # Verify the server exists
        mcp_server = get_mcp_server_by_id(server_id, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(mcp_server, user)

    # Get all tools associated with this MCP server
    mcp_tools = get_tools_by_mcp_server_id(server_id, db)

    # Convert to response format
    tools_data = []
    for tool in mcp_tools:
        # Extract the tool name from the full name (remove server prefix)
        tool_name = tool.name
        if tool.mcp_server and tool_name.startswith(f"{tool.mcp_server.name}_"):
            tool_name = tool_name[len(f"{tool.mcp_server.name}_") :]

        tools_data.append(
            MCPToolDescription(
                id=tool.id,
                name=tool_name,
                display_name=tool.display_name or tool_name,
                description=_truncate_description(tool.description),
            )
        )

    return ServerToolsResponse(
        server_id=server_id,
        server_name=mcp_server.name,
        server_url=mcp_server.server_url,
        tools=tools_data,
    )


@admin_router.post("/servers/create", response_model=MCPServerCreateResponse)
def upsert_mcp_server(
    request: MCPToolCreateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> MCPServerCreateResponse:
    """Create or update an MCP server (no tools yet)"""

    # Validate auth_performer for non-none auth types
    if request.auth_type != MCPAuthenticationType.NONE and not request.auth_performer:
        raise HTTPException(
            status_code=400, detail="auth_performer is required for non-none auth types"
        )

    try:
        mcp_server = _upsert_mcp_server(request, db_session, user)

        if (
            request.auth_type
            not in (MCPAuthenticationType.NONE, MCPAuthenticationType.PT_OAUTH)
            and mcp_server.admin_connection_config_id is None
        ):
            raise HTTPException(
                status_code=500, detail="Failed to set admin connection config"
            )
        db_session.commit()

        action_verb = "Updated" if request.existing_server_id else "Created"
        logger.info(
            "%s MCP server '%s' with ID %s", action_verb, request.name, mcp_server.id
        )

        if mcp_server.auth_type is None:
            raise HTTPException(
                status_code=500, detail="MCP server auth_type not configured"
            )
        auth_type_str = mcp_server.auth_type.value

        return MCPServerCreateResponse(
            server_id=mcp_server.id,
            server_name=mcp_server.name,
            server_url=mcp_server.server_url,
            auth_type=auth_type_str,
            auth_performer=(
                request.auth_performer.value if request.auth_performer else None
            ),
            oauth_provider_mode=mcp_server.oauth_provider_mode,
            oauth_authorization_endpoint=mcp_server.oauth_authorization_endpoint,
            oauth_token_endpoint=mcp_server.oauth_token_endpoint,
            oauth_scopes_override=mcp_server.oauth_scopes_override,
            oauth_additional_auth_params=mcp_server.oauth_additional_auth_params,
            no_user_authentication_required=not requires_user_authentication(
                mcp_server.auth_type, request.auth_performer
            ),
        )

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except OnyxError:
        raise
    except Exception as e:
        logger.exception("Failed to create/update MCP tool")
        raise HTTPException(
            status_code=500, detail=f"Failed to create/update MCP tool: {str(e)}"
        )


@admin_router.post("/servers/update", response_model=MCPServerUpdateResponse)
def update_mcp_server_with_tools(
    request: MCPToolUpdateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> MCPServerUpdateResponse:
    """Update an MCP server and associated tools"""

    try:
        mcp_server = get_mcp_server_by_id(request.server_id, db_session)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(mcp_server, user)

    if mcp_server.admin_connection_config_id is None and mcp_server.auth_type not in (
        MCPAuthenticationType.NONE,
        MCPAuthenticationType.PT_OAUTH,
    ):
        raise HTTPException(
            status_code=400, detail="MCP server has no admin connection config"
        )

    name_changed = request.name is not None and request.name != mcp_server.name
    description_changed = (
        request.description is not None
        and request.description != mcp_server.description
    )
    if name_changed or description_changed:
        mcp_server = update_mcp_server__no_commit(
            server_id=mcp_server.id,
            db_session=db_session,
            name=request.name if name_changed else None,
            description=request.description if description_changed else None,
        )

    selected_names = set(request.selected_tools or [])
    updated_tools = _sync_tools_for_server(
        mcp_server,
        selected_names,
        db_session,
    )

    db_session.commit()

    return MCPServerUpdateResponse(
        server_id=mcp_server.id,
        server_name=mcp_server.name,
        updated_tools=updated_tools,
    )


@admin_router.post("/server", response_model=MCPServer)
def create_mcp_server_simple(
    request: MCPServerSimpleCreateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> MCPServer:
    """Create MCP server with minimal information - auth to be configured later"""

    _validate_mcp_server_url(request.server_url, "server_url", require_https=False)

    mcp_server = create_mcp_server__no_commit(
        owner_email=user.email,
        name=request.name,
        description=request.description,
        server_url=request.server_url,
        auth_type=None,  # To be configured later
        transport=None,  # To be configured later
        auth_performer=None,  # To be configured later
        db_session=db_session,
    )

    _apply_mcp_server_access(
        mcp_server=mcp_server,
        acting_user=user,
        is_public=request.is_public,
        user_ids=request.users,
        group_ids=request.groups,
        is_new=True,
        db_session=db_session,
    )

    db_session.commit()

    return MCPServer(
        id=mcp_server.id,
        name=mcp_server.name,
        description=mcp_server.description,
        server_url=mcp_server.server_url,
        owner=mcp_server.owner,
        transport=mcp_server.transport,
        auth_type=mcp_server.auth_type,
        auth_performer=mcp_server.auth_performer,
        oauth_provider_mode=mcp_server.oauth_provider_mode,
        oauth_authorization_endpoint=mcp_server.oauth_authorization_endpoint,
        oauth_token_endpoint=mcp_server.oauth_token_endpoint,
        oauth_scopes_override=mcp_server.oauth_scopes_override,
        oauth_additional_auth_params=mcp_server.oauth_additional_auth_params,
        user_can_authenticate=False,  # No credentials resolved yet
        status=mcp_server.status,
        is_public=mcp_server.is_public,
        groups=[group.id for group in mcp_server.user_groups],
        users=[user.id for user in mcp_server.users],
        available_in_craft=mcp_server.available_in_craft,
        tool_count=0,  # New server, no tools yet
        auth_template=None,
        user_credentials=None,
        admin_credentials=None,
    )


@admin_router.patch("/server/{server_id}", response_model=MCPServer)
def update_mcp_server_simple(
    server_id: int,
    request: MCPServerSimpleUpdateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> MCPServer:
    """Update MCP server basic information (name, description, URL)"""
    try:
        mcp_server = get_mcp_server_by_id(server_id, db_session)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(mcp_server, user)

    _validate_mcp_server_url(request.server_url, "server_url", require_https=False)

    # Update only provided fields
    updated_server = update_mcp_server__no_commit(
        server_id=server_id,
        db_session=db_session,
        name=request.name,
        description=request.description,
        server_url=request.server_url,
        available_in_craft=request.available_in_craft,
    )

    acl_changing = any(
        value is not None
        for value in (request.is_public, request.users, request.groups)
    )
    # Only an ACL change can drop a user's access; snapshot the pre-change
    # recipients in that case so they're reloaded to lose the server (the
    # post-update query wouldn't include them).
    reload_user_ids: set[UUID] = (
        affected_user_ids_for_mcp_server(updated_server, db_session)
        if acl_changing
        else set()
    )

    if acl_changing:
        _apply_mcp_server_access(
            mcp_server=updated_server,
            acting_user=user,
            is_public=request.is_public,
            user_ids=request.users,
            group_ids=request.groups,
            is_new=False,
            db_session=db_session,
        )

    if request.tool_policies is not None:
        known = {t.name for t in get_all_mcp_tools_for_server(server_id, db_session)}
        unknown = sorted(set(request.tool_policies) - known)
        if unknown:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"unknown tool names for this server: {unknown}",
            )
        # Canonicalize at the input boundary so the stored set stays sparse
        # regardless of which client wrote it: a default (ASK) choice is
        # equivalent to leaving the tool unlisted.
        sparse_policies = {
            tool: policy
            for tool, policy in request.tool_policies.items()
            if policy != MCP_TOOL_DEFAULT_POLICY
        }
        gated_app_id = get_or_create_gated_app_id(
            db_session, GatedAppKind.MCP_SERVER, server_id
        )
        replace_action_policies__no_commit(db_session, gated_app_id, sparse_policies)

    db_session.commit()

    # Craft availability / URL live in each session's baked opencode.json;
    # reload affected users so the change reaches running sandboxes. Union the
    # pre-update recipients so newly-removed users are reloaded to drop the
    # server. (Tool policies are enforced live by the proxy and need no reload.)
    reload_user_ids |= affected_user_ids_for_mcp_server(updated_server, db_session)
    _hot_reload_craft_sessions(reload_user_ids, db_session)

    # Return the updated server in API format
    return _db_mcp_server_to_api_mcp_server(
        updated_server,
        db_session,
        request_user=user,
        permissions=mcp_server_permissions(
            can_manage=can_manage_mcp_server(user, updated_server),
        ),
    )


@admin_router.delete("/server/{server_id}")
def delete_mcp_server_admin(
    server_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> dict:
    """Delete an MCP server and cascading related objects (tools, configs)."""
    # GATE 2 above the try: the broad `except Exception` below would re-wrap its 403 as a
    # 500, hiding an authorization failure behind a server error.
    try:
        server = get_mcp_server_by_id(server_id, db_session)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")
    _ensure_mcp_server_owner_or_admin(server, user)

    try:
        # Snapshot recipients before deletion: once the server (and its ACL
        # rows) are gone, the affected-user query returns nothing, so they'd
        # never be reloaded to drop the now-deleted server from their config.
        reload_user_ids = affected_user_ids_for_mcp_server(server, db_session)

        # Log tools that will be deleted for debugging
        tools_to_delete = get_tools_by_mcp_server_id(server_id, db_session)
        logger.info(
            "Deleting MCP server %s (%s) with %s tools",
            server_id,
            server.name,
            len(tools_to_delete),
        )
        for tool in tools_to_delete:
            logger.debug("  - Tool to delete: %s (ID: %s)", tool.name, tool.id)

        # Cascade behavior handled by FK ondelete in DB
        delete_mcp_server(server_id, db_session)

        # Verify tools were deleted
        remaining_tools = get_tools_by_mcp_server_id(server_id, db_session)
        if remaining_tools:
            logger.error(
                "WARNING: %s tools still exist after deleting MCP server %s",
                len(remaining_tools),
                server_id,
            )
            # Manually delete them as a fallback
            for tool in remaining_tools:
                logger.info(
                    "Manually deleting orphaned tool: %s (ID: %s)", tool.name, tool.id
                )
                delete_tool__no_commit(tool.id, db_session)
        db_session.commit()

        # Restamp affected users so their running craft session drops the
        # deleted server on its next turn.
        _hot_reload_craft_sessions(reload_user_ids, db_session)

        return {"success": True}
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")
    except Exception as e:
        logger.error("Failed to delete MCP server %s: %s", server_id, e)
        raise HTTPException(status_code=500, detail="Failed to delete MCP server")
