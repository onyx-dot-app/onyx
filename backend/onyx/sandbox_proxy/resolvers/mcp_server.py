"""Craft MCP-server credential resolver.

Claims sandbox egress to a craft-enabled `MCPServer`'s `server_url` and injects
the sandbox owner's credentials from the same `mcp_connection_config` rows chat
writes, so authenticating on either surface authenticates both. Attribution is
an exact scheme + host + port + path-prefix match; a request to a claimed host
outside every configured prefix fails closed. `claims()` serves from a
short-TTL per-tenant cache — the one deliberate DB touch on the claims path.
"""

from __future__ import annotations

import threading
from uuid import UUID

from cachetools import TTLCache
from mitmproxy import http

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import (
    GatedAppKind,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
)
from onyx.db.mcp import (
    MCPCredentialsError,
    extract_connection_data,
    get_craft_enabled_mcp_servers,
    get_mcp_server_by_id,
    resolve_mcp_credentials,
    user_can_access_mcp_server,
)
from onyx.db.models import MCPServer
from onyx.db.users import fetch_user_by_id
from onyx.sandbox_proxy.credential_injection import (
    CredentialResolver,
    CredentialUnavailableError,
    InjectionContext,
)
from onyx.sandbox_proxy.logging_utils import short_log_id
from onyx.sandbox_proxy.resolvers.mcp_matching import (
    AmbiguousMCPTargetError,
    CraftMCPTarget,
    host_targets,
    match_request,
    normalized_request_path,
    parse_target,
)
from onyx.server.features.mcp.oauth import (
    mcp_token_expired,
    refresh_mcp_oauth_token_if_expired,
)
from onyx.utils.credential_audit import emit_credential_access
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

_TARGET_CACHE_TTL_S = 30.0


class MCPServerResolver(CredentialResolver):
    """Injects stored MCP credentials on craft-enabled servers' URLs."""

    def __init__(self, cache_ttl_s: float = _TARGET_CACHE_TTL_S) -> None:
        self._cache_lock = threading.Lock()
        self._targets_by_tenant: TTLCache[str, tuple[CraftMCPTarget, ...]] = TTLCache(
            maxsize=10_000, ttl=cache_ttl_s
        )

    def claims(self, request: http.Request, ctx: InjectionContext) -> bool:
        # A request the external-app matcher attributed belongs to that resolver
        # on a shared host (MCP servers aren't in that catalog) — defer. An MCP
        # `tools/call` the evaluator gated is still ours to inject onto.
        actions = ctx.matched_actions
        if actions is not None and actions.target.kind is not GatedAppKind.MCP_SERVER:
            return False
        return bool(self._host_targets(request, ctx.sandbox.tenant_id))

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        actions = ctx.matched_actions
        if actions is not None and actions.target.kind is GatedAppKind.MCP_SERVER:
            # Gated request: inject for the exact server the gate evaluated
            # (fresh attribution), never a re-match against this resolver's
            # 30s target cache — a stale cache could pick a different server.
            return self._resolve_for_server(actions.target.id, ctx)
        try:
            target = match_request(self._targets(ctx.sandbox.tenant_id), request)
        except AmbiguousMCPTargetError as e:
            raise CredentialUnavailableError(
                str(e),
                sandbox_detail=(
                    "Multiple MCP servers in Onyx are configured with the same "
                    "URL, so Craft cannot tell which one's credentials to use. "
                    "Ask a workspace admin to remove the duplicate MCP server "
                    "configuration."
                ),
            ) from e
        if target is None:
            path = normalized_request_path(request.path or "")
            raise CredentialUnavailableError(
                f"request path {path!r} on MCP host {request.host} matches no "
                "configured server_url prefix",
                sandbox_detail=(
                    "This host belongs to an MCP server configured in Onyx, but "
                    "the request path is outside the server's MCP endpoint, so "
                    "it was blocked. Only the configured MCP endpoint is "
                    "reachable on this host."
                ),
            )
        return self._resolve_for_server(target.server_id, ctx)

    def _resolve_for_server(
        self, server_id: int, ctx: InjectionContext
    ) -> dict[str, str]:
        tenant_id = ctx.sandbox.tenant_id
        user_id = ctx.sandbox.user_id
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            server = get_mcp_server_by_id(server_id, db)
            admin_managed = server.auth_performer == MCPAuthenticationPerformer.ADMIN
            if not server.available_in_craft:
                # Flag flipped since the cache entry was built.
                raise CredentialUnavailableError(
                    f"MCP server {server.id} is no longer craft-enabled",
                    sandbox_detail=_connect_detail(server.name, admin_managed),
                )
            user = fetch_user_by_id(db, user_id)
            if user is None:
                raise CredentialUnavailableError(
                    f"sandbox user {short_log_id(user_id)} not found"
                )
            if not user_can_access_mcp_server(user, server.id, db):
                # Not shared with this user — never inject admin creds for them.
                raise CredentialUnavailableError(
                    f"user {short_log_id(user_id)} lacks access to MCP server "
                    f"{server.id}"
                )
            try:
                creds = resolve_mcp_credentials(server, user, db)
            except MCPCredentialsError as e:
                raise CredentialUnavailableError(
                    str(e), sandbox_detail=_connect_detail(server.name, admin_managed)
                ) from e
            headers = creds.build_headers()
            expired_oauth_config_id: int | None = None
            if (
                server.auth_type == MCPAuthenticationType.OAUTH
                and creds.connection_config is not None
                and mcp_token_expired(extract_connection_data(creds.connection_config))
            ):
                expired_oauth_config_id = creds.connection_config.id

        # Refresh after the session closes — the primitive opens its own.
        if expired_oauth_config_id is not None:
            headers = _refresh_oauth_headers(
                tenant_id, server, str(user_id), expired_oauth_config_id
            )
            if not headers:
                raise CredentialUnavailableError(
                    f"OAuth token for MCP server {server.id} is expired and "
                    "could not be refreshed",
                    sandbox_detail=_reconnect_detail(server.name, admin_managed),
                )

        requires_auth = server.auth_type not in (None, MCPAuthenticationType.NONE)
        if requires_auth and not headers:
            raise CredentialUnavailableError(
                f"no stored credentials for user {short_log_id(user_id)} on "
                f"server {server.id}",
                sandbox_detail=_connect_detail(server.name, admin_managed),
            )
        if headers:
            self._audit(server, user_id)
        return headers

    def _audit(self, server: MCPServer, user_id: UUID) -> None:
        emit_credential_access(
            credential_type="mcp_server",
            provider=server.name,
            row_id=server.id,
            user_id=str(user_id),
            auth_type=server.auth_type.value if server.auth_type else None,
        )

    def _host_targets(
        self, request: http.Request, tenant_id: str
    ) -> list[CraftMCPTarget]:
        return host_targets(
            self._targets(tenant_id), request.scheme, request.host, request.port
        )

    def _targets(self, tenant_id: str) -> tuple[CraftMCPTarget, ...]:
        with self._cache_lock:
            cached = self._targets_by_tenant.get(tenant_id)
        if cached is not None:
            return cached
        # Loaded outside the lock so a slow query can't stall other tenants'
        # claims; a concurrent duplicate load is harmless.
        targets = self._load_targets(tenant_id)
        with self._cache_lock:
            self._targets_by_tenant[tenant_id] = targets
        return targets

    def _load_targets(self, tenant_id: str) -> tuple[CraftMCPTarget, ...]:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            # No user at claim time; access is enforced in resolve().
            servers = get_craft_enabled_mcp_servers(db, None)
            parsed = [parse_target(s.id, s.server_url) for s in servers]
        return tuple(t for t in parsed if t is not None)


def _refresh_oauth_headers(
    tenant_id: str, server: MCPServer, user_id: str, connection_config_id: int
) -> dict[str, str] | None:
    """Fresh auth headers after refreshing the expired OAuth token, or None if
    it couldn't be refreshed. Sets the tenant contextvar the shared refresh
    primitive reads."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        auth_header = refresh_mcp_oauth_token_if_expired(
            server, connection_config_id, user_id
        )
    except Exception:
        logger.exception("mcp_token_refresh.failed config_id=%s", connection_config_id)
        return None
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    return {"Authorization": auth_header} if auth_header else None


def _fix_instruction(admin_managed: bool, *, reconnect: bool) -> str:
    verb = "reconnect" if reconnect else "connect"
    if admin_managed:
        return f"Ask a workspace admin to {verb} it on the MCP actions page in Onyx."
    return f"Ask the user to {verb} it from the Apps page in Craft, then retry."


def _connect_detail(server_name: str, admin_managed: bool) -> str:
    return (
        f'The MCP server "{server_name}" is not connected. '
        f"{_fix_instruction(admin_managed, reconnect=False)}"
    )


def _reconnect_detail(server_name: str, admin_managed: bool) -> str:
    return (
        f'The saved credentials for the MCP server "{server_name}" are expired and '
        "could not be refreshed right now — another request may be refreshing them. "
        f"Retry shortly. If it keeps failing: {_fix_instruction(admin_managed, reconnect=True)}"
    )
