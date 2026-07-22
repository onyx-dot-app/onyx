"""Craft MCP-server credential resolver.

Claims sandbox egress to a craft-enabled `MCPServer`'s `server_url` and injects
the sandbox owner's credentials from the same `mcp_connection_config` rows chat
writes, so authenticating on either surface authenticates both. Attribution is
an exact scheme + host + port + path-prefix match; a request to a claimed host
outside every configured prefix fails closed. `claims()` serves from a
short-TTL per-tenant cache — the one deliberate DB touch on the claims path.
"""

from __future__ import annotations

import posixpath
import threading
from urllib.parse import unquote, urlparse
from uuid import UUID

from cachetools import TTLCache
from mitmproxy import http
from pydantic import BaseModel

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import MCPAuthenticationPerformer, MCPAuthenticationType
from onyx.db.mcp import (
    MCPCredentialsError,
    extract_connection_data,
    get_craft_enabled_mcp_servers,
    get_mcp_server_by_id,
    resolve_mcp_credentials,
)
from onyx.db.models import MCPServer
from onyx.db.users import fetch_user_by_id
from onyx.sandbox_proxy.credential_injection import (
    CredentialResolver,
    CredentialUnavailableError,
    InjectionContext,
)
from onyx.sandbox_proxy.logging_utils import short_log_id
from onyx.server.features.mcp.oauth import (
    mcp_token_expired,
    refresh_mcp_oauth_token_if_expired,
)
from onyx.utils.credential_audit import emit_credential_access
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

_TARGET_CACHE_TTL_S = 30.0
_SCHEME_DEFAULT_PORTS = {"http": 80, "https": 443}


class _CraftMCPTarget(BaseModel):
    """One craft-enabled server's parsed `server_url`, ready for matching."""

    model_config = {"frozen": True}

    server_id: int
    scheme: str
    host: str
    port: int
    path_prefix: str  # no trailing slash; "" claims the whole host


def _parse_target(server_id: int, server_url: str) -> _CraftMCPTarget | None:
    parsed = urlparse(server_url)
    scheme = (parsed.scheme or "").lower()
    port = parsed.port or _SCHEME_DEFAULT_PORTS.get(scheme)
    if not scheme or not parsed.hostname or port is None:
        logger.warning(
            "craft MCP server %s has an unusable server_url; "
            "it will not be reachable from Craft",
            server_id,
        )
        return None
    return _CraftMCPTarget(
        server_id=server_id,
        scheme=scheme,
        host=parsed.hostname.lower(),
        port=port,
        path_prefix=parsed.path.rstrip("/"),
    )


def _normalized_request_path(raw_path: str) -> str:
    """Percent-decode and collapse `.`/`..` so prefix matching can't be escaped
    by traversal (`/mcp/../admin`) the upstream would resolve to another path."""
    path = unquote(raw_path.split("?", 1)[0].split("#", 1)[0])
    return posixpath.normpath(path)


def _path_matches(request_path: str, path_prefix: str) -> bool:
    if not path_prefix:
        return True
    return request_path == path_prefix or request_path.startswith(path_prefix + "/")


class MCPServerResolver(CredentialResolver):
    """Injects stored MCP credentials on craft-enabled servers' URLs."""

    def __init__(self, cache_ttl_s: float = _TARGET_CACHE_TTL_S) -> None:
        self._cache_lock = threading.Lock()
        self._targets_by_tenant: TTLCache[str, tuple[_CraftMCPTarget, ...]] = TTLCache(
            maxsize=10_000, ttl=cache_ttl_s
        )

    def claims(self, request: http.Request, ctx: InjectionContext) -> bool:
        # A matched request belongs to an external app on a shared host (MCP
        # servers aren't in that catalog) — defer to ExternalAppResolver.
        if ctx.matched_actions is not None:
            return False
        return bool(self._host_targets(request, ctx.sandbox.tenant_id))

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        tenant_id = ctx.sandbox.tenant_id
        user_id = ctx.sandbox.user_id
        path = _normalized_request_path(request.path)
        candidates = [
            t
            for t in self._host_targets(request, tenant_id)
            if _path_matches(path, t.path_prefix)
        ]
        if not candidates:
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
        # Longest prefix wins when servers share a host. A tie at the longest
        # prefix means two configs claim the same endpoint with no way to tell
        # which owns the request — fail closed rather than inject an arbitrary
        # config's credentials.
        longest = max(len(t.path_prefix) for t in candidates)
        winners = [t for t in candidates if len(t.path_prefix) == longest]
        if len(winners) > 1:
            raise CredentialUnavailableError(
                f"request path {path!r} on MCP host {request.host} matches "
                f"{len(winners)} MCP servers ({sorted(w.server_id for w in winners)}) "
                "at the same endpoint; credential attribution is ambiguous",
                sandbox_detail=(
                    "Multiple MCP servers in Onyx are configured with the same "
                    "URL, so Craft cannot tell which one's credentials to use. "
                    "Ask a workspace admin to remove the duplicate MCP server "
                    "configuration."
                ),
            )
        target = winners[0]

        with get_session_with_tenant(tenant_id=tenant_id) as db:
            server = get_mcp_server_by_id(target.server_id, db)
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
    ) -> list[_CraftMCPTarget]:
        # Scheme must match so an HTTPS server's bearer is never injected onto a
        # plaintext request to the same host:port.
        scheme = request.scheme.lower()
        host = request.host.lower()
        port = request.port
        return [
            t
            for t in self._targets(tenant_id)
            if t.scheme == scheme and t.host == host and t.port == port
        ]

    def _targets(self, tenant_id: str) -> tuple[_CraftMCPTarget, ...]:
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

    def _load_targets(self, tenant_id: str) -> tuple[_CraftMCPTarget, ...]:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            servers = get_craft_enabled_mcp_servers(db)
            parsed = [_parse_target(s.id, s.server_url) for s in servers]
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
