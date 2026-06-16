"""Proactive, single-flighted OAuth refresh for MCP servers.

The MCP SDK's OAuthClientProvider is rebuilt per tool call and never restores token
expiry, so it never refreshes proactively and an expired token escalates to a full
re-auth ("Please Reconnect to the server"). Onyx drives refresh itself instead:
the storage and dead-grant policy live in :class:`_MCPTokenRefresher`, and the
single-flight skeleton (lock, stale pre-check, terminal/transient/contention/infra
routing) is the shared :class:`onyx.oauth.single_flight.SingleFlightTokenRefresher`
— the same one Craft external apps use. Never raises for a refresh outcome.
"""

from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests
from mcp.shared.auth import OAuthToken

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPServerStatus
from onyx.db.mcp import extract_connection_data
from onyx.db.mcp import get_connection_config_by_id
from onyx.db.mcp import update_connection_config
from onyx.db.mcp import update_mcp_server__no_commit
from onyx.db.models import MCPServer
from onyx.oauth.errors import TokenRefreshTerminalError
from onyx.oauth.exchange import exchange_refresh_token
from onyx.oauth.exchange import OAuthFlowParams
from onyx.oauth.exchange import validate_oauth_endpoint_url
from onyx.oauth.expiry import needs_refresh
from onyx.oauth.single_flight import SingleFlightTokenRefresher
from onyx.server.features.mcp.models import MCPConnectionData
from onyx.server.features.mcp.models import MCPOAuthKeys
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException

logger = setup_logger()

_DISCOVERY_PATHS = (
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
)
_DISCOVERY_TIMEOUT_S = 10


class _MCPTokenRefresher(SingleFlightTokenRefresher[dict[str, str]]):
    """Refresh the OAuth access token on one MCP connection config.

    Storage is ``MCPConnectionConfig``; on success returns the fresh ``headers``
    dict (new ``Authorization``) for the caller to apply. A dead grant flips an
    admin-owned server to ``AWAITING_AUTH``; per-user grants are left alone.
    """

    log_prefix = "mcp_token_refresh"

    def __init__(
        self, tenant_id: str, mcp_server: MCPServer, connection_config_id: int
    ):
        self.tenant_id = tenant_id
        self.mcp_server = mcp_server
        self.connection_config_id = connection_config_id

    def lock_name(self) -> str:
        return f"mcp_token_refresh:{self.tenant_id}:{self.connection_config_id}"

    def is_stale(self) -> bool:
        if self.mcp_server.auth_type != MCPAuthenticationType.OAUTH:
            return False
        # Cheap pre-check before taking the lock; resolution only happens when stale.
        with get_session_with_tenant(tenant_id=self.tenant_id) as db:
            config = get_connection_config_by_id(self.connection_config_id, db)
            config_data = extract_connection_data(config, apply_mask=False)
        return _needs_refresh(config_data, datetime.now(timezone.utc))

    def refresh_under_lock(self) -> dict[str, str] | None:
        # Re-read after the lock wait: a concurrent winner may have already refreshed.
        with get_session_with_tenant(tenant_id=self.tenant_id) as db:
            config = get_connection_config_by_id(self.connection_config_id, db)
            config_data = extract_connection_data(config, apply_mask=False)

        if not _needs_refresh(config_data, datetime.now(timezone.utc)):
            # Already refreshed by the lock winner — hand back the fresh headers.
            return config_data.get("headers")

        tokens = config_data.get(MCPOAuthKeys.TOKENS.value) or {}
        refresh_token = tokens.get("refresh_token")
        client = _client_credentials(config_data)
        if not refresh_token or client is None:
            return None
        client_id, client_secret = client

        token_endpoint = _resolve_token_endpoint(self.mcp_server, config_data)
        if token_endpoint is None:
            logger.warning(
                "mcp_token_refresh.no_token_endpoint server_id=%s config_id=%s",
                self.mcp_server.id,
                self.connection_config_id,
            )
            return None

        params = OAuthFlowParams(
            # authorization_url is unused by refresh; token_url drives the grant.
            authorization_url=token_endpoint,
            token_url=token_endpoint,
            client_id=client_id,
            client_secret=client_secret,
        )
        # Raises Terminal/Transient, routed by the base class.
        new_token_data = exchange_refresh_token(params, refresh_token)

        new_token_data.setdefault("token_type", "Bearer")
        if not new_token_data.get("access_token"):
            logger.warning(
                "mcp_token_refresh.no_access_token server_id=%s", self.mcp_server.id
            )
            return None

        return _persist_refreshed(
            self.tenant_id, self.connection_config_id, new_token_data, token_endpoint
        )

    def on_terminal(self, error: TokenRefreshTerminalError) -> dict[str, str] | None:
        # Dead grant — an admin-owned server needs a manual reconnect.
        logger.warning(
            "mcp_token_refresh.terminal server_id=%s config_id=%s error=%s",
            self.mcp_server.id,
            self.connection_config_id,
            error,
        )
        _mark_awaiting_auth_if_admin(
            self.tenant_id, self.mcp_server, self.connection_config_id
        )
        return None


def ensure_fresh_mcp_token(
    tenant_id: str,
    mcp_server: MCPServer,
    connection_config_id: int,
) -> dict[str, str] | None:
    """Refresh the OAuth access token on `connection_config_id` if it's expired or
    expiring, returning the fresh ``headers`` dict (with the new ``Authorization``)
    for the caller to apply. Returns None when no refresh was needed or possible —
    the caller then proceeds with the currently-stored credentials.
    """
    return _MCPTokenRefresher(tenant_id, mcp_server, connection_config_id).run()


def _persist_refreshed(
    tenant_id: str,
    connection_config_id: int,
    new_token_data: dict[str, Any],
    token_endpoint: str,
) -> dict[str, str] | None:
    oauth_token = OAuthToken.model_validate(new_token_data)
    headers = {"Authorization": f"{oauth_token.token_type} {oauth_token.access_token}"}
    with get_session_with_tenant(tenant_id=tenant_id) as db:
        config = get_connection_config_by_id(connection_config_id, db)
        config_data = extract_connection_data(config, apply_mask=False)
        config_data[MCPOAuthKeys.TOKENS.value] = oauth_token.model_dump(mode="json")
        config_data["headers"] = headers
        expires_at = new_token_data.get("expires_at")
        if expires_at is not None:
            config_data[MCPOAuthKeys.EXPIRES_AT.value] = datetime.fromtimestamp(
                int(expires_at), tz=timezone.utc
            ).isoformat()
        # Persist the resolved endpoint so auto-discovery configs skip discovery next time.
        config_data[MCPOAuthKeys.TOKEN_ENDPOINT.value] = token_endpoint
        update_connection_config(config.id, db, config_data)

    logger.info("mcp_token_refresh.refreshed config_id=%s", connection_config_id)
    return headers


def _needs_refresh(config_data: MCPConnectionData, now: datetime) -> bool:
    """True iff we hold a refresh token and the access token is expired/expiring.

    A config with a refresh token but no persisted ``token_expires_at`` predates the
    expiry-persistence fix; we can't tell when it lapses, so refresh once to heal it
    (after which ``token_expires_at`` is always stored)."""
    tokens = config_data.get(MCPOAuthKeys.TOKENS.value) or {}
    if not tokens.get("refresh_token"):
        # No refresh token: can't refresh. Leave first-auth to the SDK provider.
        return False
    expires_at = config_data.get(MCPOAuthKeys.EXPIRES_AT.value)
    if not expires_at:
        return True
    return needs_refresh({"expires_at": expires_at}, now)


def _client_credentials(
    config_data: MCPConnectionData,
) -> tuple[str, str | None] | None:
    client_info = config_data.get(MCPOAuthKeys.CLIENT_INFO.value) or {}
    client_id = client_info.get("client_id")
    if not client_id:
        return None
    return client_id, client_info.get("client_secret")


def _resolve_token_endpoint(
    mcp_server: MCPServer, config_data: MCPConnectionData
) -> str | None:
    """The OAuth token endpoint: a previously-persisted value, then the server row
    (known-provider mode), then a one-shot RFC 8414 discovery (auto-discovery mode)."""
    persisted = config_data.get(MCPOAuthKeys.TOKEN_ENDPOINT.value)
    if persisted:
        return persisted
    if mcp_server.oauth_token_endpoint:
        return mcp_server.oauth_token_endpoint
    return _discover_token_endpoint(mcp_server.server_url)


def _discover_token_endpoint(server_url: str) -> str | None:
    """Fetch the authorization-server metadata and return its ``token_endpoint``.

    Best-effort: probes the standard well-known locations at the server origin and
    returns None if none resolve. SSRF-guarded via the shared OAuth endpoint policy."""
    parsed = urlparse(server_url)
    if not parsed.scheme or not parsed.netloc:
        return None
    origin = f"{parsed.scheme}://{parsed.netloc}"
    for path in _DISCOVERY_PATHS:
        url = urljoin(origin, path)
        try:
            validate_oauth_endpoint_url(url)
            response = requests.get(
                url,
                headers={"Accept": "application/json"},
                timeout=_DISCOVERY_TIMEOUT_S,
                # Don't follow redirects: the pre-request SSRF check validated this
                # URL, but a 3xx could send the follow-up to an unvalidated internal
                # target. Treat a redirect as a discovery miss.
                allow_redirects=False,
            )
            if response.is_redirect or response.is_permanent_redirect:
                logger.debug("mcp_token_refresh.discovery_redirect url=%s", url)
                continue
            response.raise_for_status()
            token_endpoint = response.json().get("token_endpoint")
            if token_endpoint:
                return str(token_endpoint)
        except (requests.RequestException, SSRFException, ValueError) as exc:
            logger.debug("mcp_token_refresh.discovery_miss url=%s error=%s", url, exc)
            continue
    return None


def _mark_awaiting_auth_if_admin(
    tenant_id: str,
    mcp_server: MCPServer,
    connection_config_id: int,
) -> None:
    """Surface a reconnect in the Admin Panel for a dead admin grant. Per-user
    configs are left alone — one dead grant shouldn't disconnect the server for
    everyone; that user's next call surfaces the normal auth error instead."""
    if mcp_server.admin_connection_config_id != connection_config_id:
        return
    with get_session_with_tenant(tenant_id=tenant_id) as db:
        update_mcp_server__no_commit(
            server_id=mcp_server.id,
            db_session=db,
            status=MCPServerStatus.AWAITING_AUTH,
        )
        db.commit()
