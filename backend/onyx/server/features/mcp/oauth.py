"""Shared MCP OAuth machinery: the SDK token storage/provider and their helpers.

Used by chat tool calls (`MCPTool.run`), the admin/user MCP API routes, and the
Craft sandbox proxy's token refresh — anything that authenticates against an
MCP server with the credentials persisted on `mcp_connection_config` rows.
Route orchestration lives in `oauth_flow.py`.
"""

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from uuid import uuid4

import httpx
from mcp.client.auth import OAuthClientProvider, PKCEParameters, TokenStorage
from mcp.client.auth.exceptions import OAuthFlowError, OAuthTokenError
from mcp.client.auth.oauth2 import OAuthContext
from mcp.client.auth.utils import handle_token_response_scopes
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)
from pydantic import AnyUrl, ValidationError
from sqlalchemy.orm import Session

from onyx.auth.oauth_token_manager import ensure_offline_access_auth_params
from onyx.cache.interface import CacheLockAcquisitionError
from onyx.cache.locks import cache_shared_lock
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import MCPOAuthProviderMode
from onyx.db.mcp import (
    get_connection_config_by_id,
    update_connection_config,
    update_connection_config__no_commit,
)
from onyx.db.models import MCPConnectionConfig, MCPServer
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.oauth.authorization_attempt import generate_authorization_state
from onyx.server.features.mcp.client_metadata import (
    mcp_oauth_redirect_uri,
    validated_mcp_oauth_client_metadata_url,
)
from onyx.server.features.mcp.credentials import (
    extract_connection_data,
    mcp_oauth_client_information_fingerprint,
    mcp_oauth_connection_headers_fingerprint,
    mcp_token_expired,
)
from onyx.server.features.mcp.models import (
    MCPOAuthKeys,
    MCPPendingOAuthAuthorization,
    merge_mcp_headers,
)
from onyx.server.features.mcp.ssrf import (
    mcp_ssrf_httpx_client_factory,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_async_sync_no_cancel
from onyx.utils.url import SSRFException
from shared_configs.contextvars import ONYX_REQUEST_ID_CONTEXTVAR, get_current_tenant_id

logger = setup_logger()

# Refresh slightly before the real expiry to absorb network latency and clock
# skew between us and the provider, avoiding edge-of-expiry 401s.
TOKEN_EXPIRY_BUFFER_SECONDS = 30.0

# The refresh POST is a small JSON exchange, so bound it well under the SDK's
# SSE-sized default timeout.
_REFRESH_POST_TIMEOUT_S = 30.0
# How long a contention loser waits for the lock. It must outlast the winner's
# whole refresh (POST + a couple of quick DB writes) so the loser wakes to the
# freshly persisted token instead of timing out mid-refresh and falling back to
# a stale/None header (which 401s). No cost in the common case: acquire returns
# the instant the winner releases — this is only the cap for a slow winner.
_REFRESH_LOCK_WAIT_S = _REFRESH_POST_TIMEOUT_S + 5.0
# Lease bounds how long the holder may keep the lock; exceeds the worst-case
# refresh so it can't expire mid-refresh and let a second caller reuse the
# rotating refresh token. Redis-enforced only (see cache_shared_lock).
_REFRESH_LOCK_LEASE_S = 60.0


REQUESTED_SCOPE: str | None = None

OAUTH_HTTP_TIMEOUT_SECONDS = 30.0


class MCPRefreshLogContext(TypedDict):
    mcp_server_id: int | None
    mcp_server_name: str
    connection_config_id: int
    transport: str
    oauth_provider_mode: str


class MCPClientRegistrationConflict(Exception):
    """Another request persisted the shared client registration first."""


class MCPRefreshSuperseded(Exception):
    """The grant changed while a refresh request was in flight."""


class MCPReauthenticationRequired(OAuthFlowError):
    """A non-interactive MCP operation requires a new browser grant."""

    def __init__(self) -> None:
        super().__init__("Please reconnect to the server through Onyx.")


def _refresh_log_context(
    mcp_server: MCPServer, connection_config_id: int
) -> MCPRefreshLogContext:
    return {
        "mcp_server_id": mcp_server.id,
        "mcp_server_name": mcp_server.name,
        "connection_config_id": connection_config_id,
        "transport": mcp_server.transport.value if mcp_server.transport else "UNKNOWN",
        "oauth_provider_mode": mcp_server.oauth_provider_mode.value,
    }


def _oauth_error_from_response(
    body: bytes, content_type: str | None
) -> tuple[str | None, str]:
    """Extract only the safe OAuth error code and body format from a response."""
    normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
    body_format = (
        "form"
        if normalized_content_type == "application/x-www-form-urlencoded"
        else "json"
    )

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        if body_format != "form":
            body_format = "unknown"
        form_payload = parse_qs(body.decode("utf-8", errors="replace"))
        return (form_payload.get("error", [None])[0], body_format)

    if isinstance(payload, dict):
        return (payload.get("error"), body_format)
    return None, body_format


def _response_request_hostname(response: httpx.Response) -> str | None:
    """Return the response hostname when httpx attached the originating request."""
    try:
        return response.request.url.host
    except RuntimeError:
        return None


def _oauth_token_from_response(body: bytes) -> OAuthToken:
    """Parse JSON or form-encoded OAuth token responses."""
    try:
        return OAuthToken.model_validate_json(body)
    except ValidationError as json_error:
        form_payload = parse_qs(body.decode("utf-8", errors="replace"))
        payload = {key: values[0] for key, values in form_payload.items() if values}
        try:
            return OAuthToken.model_validate(payload)
        except ValidationError:
            raise json_error from None


def _token_dict_with_preserved_refresh(
    tokens: OAuthToken,
    existing_tokens_raw: dict[str, Any] | None,
    *,
    preserve_existing_refresh_token: bool = True,
) -> dict[str, Any]:
    """Dump `tokens` for storage, carrying over a previously stored refresh
    token when the new payload omits one (providers like Google only issue a
    refresh token on the first authorization)."""
    token_dict = tokens.model_dump(mode="json")
    if (
        token_dict.get("refresh_token")
        or not existing_tokens_raw
        or not preserve_existing_refresh_token
    ):
        return token_dict
    existing_refresh = existing_tokens_raw.get("refresh_token")
    if existing_refresh:
        token_dict["refresh_token"] = existing_refresh
    return token_dict


def _absolute_token_expiry(tokens: OAuthToken) -> float | None:
    """Resolve the relative `expires_in` to an absolute unix timestamp so it
    survives a reload into a fresh OAuth provider (see TOKEN_EXPIRES_AT)."""
    if tokens.expires_in is None:
        return None
    return time.time() + tokens.expires_in - TOKEN_EXPIRY_BUFFER_SECONDS


async def _refresh_mcp_oauth_token_if_expired(
    mcp_server: MCPServer,
    connection_config_id: int,
) -> str | None:
    """Refresh an SSE-transport MCP server's OAuth token via the same
    `OAuthClientProvider`/`OnyxTokenStorage` every other MCP OAuth path uses
    (see `make_oauth_provider`) — the SDK's own httpx.Auth refresh can't run
    over an open SSE stream, so this drives the provider's refresh step
    directly instead of the full httpx.Auth flow. That gets client-auth-method
    handling (`client_secret_basic` vs. `client_secret_post`) and token
    persistence for free, instead of a second implementation to keep in sync.

    Uses private SDK methods (`_initialize`/`_refresh_token`/
    `_handle_refresh_response`) since there's no public "refresh if needed"
    API — may need adjusting on MCP SDK upgrades.

    Returns the `Authorization` header to use now, or `None` with no opinion
    (no refresh token / client info) — caller falls back to its own header.
    Raises on failure; caller treats that as non-fatal.
    """
    provider = make_oauth_provider(
        mcp_server,
        connection_config_id,
        None,
    )
    context = provider.context
    await provider._initialize()

    if not context.can_refresh_token():
        return None

    if context.is_token_valid():
        # Valid (no persisted expiry also reads as valid), or a racing call
        # already refreshed it — hand back the current header either way.
        current_tokens = context.current_tokens
        assert current_tokens is not None  # implied by can_refresh_token()
        return f"{current_tokens.token_type} {current_tokens.access_token}"

    refresh_request = await provider._refresh_token()
    async with mcp_ssrf_httpx_client_factory(
        timeout=httpx.Timeout(_REFRESH_POST_TIMEOUT_S)
    ) as client:
        response = await client.send(refresh_request)

    if not await provider._handle_refresh_response(response):
        raise RuntimeError(
            f"MCP OAuth refresh failed for server '{mcp_server.name}' "
            f"(config {connection_config_id}): {response.status_code}"
        )

    logger.info(
        "Refreshed SSE MCP OAuth token for server '%s' (config %s)",
        mcp_server.name,
        connection_config_id,
    )
    new_tokens = context.current_tokens
    assert new_tokens is not None  # set by _handle_refresh_response on success
    return f"{new_tokens.token_type} {new_tokens.access_token}"


def refresh_mcp_oauth_token_if_expired(
    mcp_server: MCPServer,
    connection_config_id: int,
) -> str | None:
    """Sync entry point for `_refresh_mcp_oauth_token_if_expired`, single-flighted
    per connection-config row (via `cache_shared_lock`) so two racing refreshes
    can't redeem — and burn — the same rotating refresh token.

    On contention the loser waits out the in-flight refresh (the wait outlasts a
    refresh POST) and returns the winner's freshly persisted header. Only if the
    lock still can't be acquired *and* the stored token is expired does it return
    None; the caller then falls back to its existing header.
    """
    lock_name = f"mcp_token_refresh:{get_current_tenant_id()}:{connection_config_id}"
    try:
        with cache_shared_lock(
            lock_name,
            max_time_lock_held_s=_REFRESH_LOCK_LEASE_S,
            wait_for_lock_s=_REFRESH_LOCK_WAIT_S,
            logger=logger,
        ):
            return run_async_sync_no_cancel(
                _refresh_mcp_oauth_token_if_expired(mcp_server, connection_config_id)
            )
    except MCPRefreshSuperseded:
        logger.info("mcp_token_refresh.superseded config_id=%s", connection_config_id)
        return _persisted_auth_header(connection_config_id)
    except CacheLockAcquisitionError:
        # Couldn't acquire within the wait; return whatever the winner persisted
        # (None if it hasn't finished and the stored token is still expired).
        logger.info(
            "mcp_token_refresh.lock_contended config_id=%s", connection_config_id
        )
        return _persisted_auth_header(connection_config_id)


def _persisted_auth_header(connection_config_id: int) -> str | None:
    """The stored ``Authorization`` header when the persisted token is still
    fresh, else None — used as the fallback when a concurrent refresh wins."""
    with get_session_with_current_tenant() as db:
        config_data = extract_connection_data(
            get_connection_config_by_id(connection_config_id, db)
        )
    if mcp_token_expired(config_data):
        return None
    return (config_data.get("headers") or {}).get("Authorization")


def _known_provider_oauth_metadata(mcp_server: MCPServer) -> OAuthMetadata | None:
    """Expose a KNOWN_PROVIDER server's configured endpoints as SDK OAuth
    metadata so refresh targets the real token endpoint, not the SDK's
    `<server-origin>/token` fallback."""
    if (
        mcp_server.oauth_provider_mode != MCPOAuthProviderMode.KNOWN_PROVIDER
        or not mcp_server.oauth_authorization_endpoint
        or not mcp_server.oauth_token_endpoint
    ):
        return None
    parsed = urlparse(mcp_server.oauth_authorization_endpoint)
    return OAuthMetadata(
        issuer=f"{parsed.scheme}://{parsed.netloc}",
        authorization_endpoint=mcp_server.oauth_authorization_endpoint,
        token_endpoint=mcp_server.oauth_token_endpoint,
    )


class OnyxTokenStorage(TokenStorage):
    """
    store auth info in a particular user's connection config in postgres
    """

    def __init__(
        self,
        connection_config_id: int,
        shared_client_config_id: int | None = None,
        refresh_log_context: MCPRefreshLogContext | None = None,
        *,
        load_stored_tokens: bool = True,
        expected_connection_headers_fingerprint: str | None = None,
        expected_client_information_fingerprint: str | None = None,
    ):
        self.shared_client_config_id = shared_client_config_id
        self.connection_config_id = connection_config_id
        self.refresh_log_context = refresh_log_context
        self.load_stored_tokens = load_stored_tokens
        self.expected_connection_headers_fingerprint = (
            expected_connection_headers_fingerprint
        )
        self.expected_client_information_fingerprint = (
            expected_client_information_fingerprint
        )
        self.refresh_attempt_id: str | None = None
        # When bound, `get_tokens` hydrates its `token_expiry_time` from the
        # config read it already does — no separate query for the expiry.
        self._oauth_context: OAuthContext | None = None

    def bind_oauth_context(self, context: OAuthContext) -> None:
        self._oauth_context = context

    def _ensure_connection_config(
        self, db_session: Session, *, for_update: bool = False
    ) -> MCPConnectionConfig:
        config = get_connection_config_by_id(
            self.connection_config_id, db_session, for_update=for_update
        )
        if config is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Connection config not found")
        return config

    async def get_tokens(self) -> OAuthToken | None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            # The SDK never derives expiry from stored tokens; hydrate it here
            # to drive its refresh decision (None = no known expiry).
            if self._oauth_context is not None:
                expires_at = config_data.get(MCPOAuthKeys.TOKEN_EXPIRES_AT.value)
                self._oauth_context.token_expiry_time = (
                    float(expires_at) if expires_at is not None else None
                )
                # Re-seed discovered metadata so refresh targets the real token
                # endpoint, not the SDK's `<origin>/token` fallback. Don't
                # clobber a known provider's metadata set in make_oauth_provider.
                if self._oauth_context.oauth_metadata is None:
                    metadata_raw = config_data.get(MCPOAuthKeys.METADATA.value)
                    if metadata_raw:
                        self._oauth_context.oauth_metadata = (
                            OAuthMetadata.model_validate(metadata_raw)
                        )
            tokens_raw = config_data.get(MCPOAuthKeys.TOKENS.value)
            if tokens_raw and self.load_stored_tokens:
                return OAuthToken.model_validate(tokens_raw)
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        await self._persist_tokens(tokens, preserve_existing_refresh_token=True)

    async def set_refreshed_tokens(
        self,
        tokens: OAuthToken,
        redeemed_refresh_token: str | None,
    ) -> bool:
        return await self._persist_tokens(
            tokens,
            preserve_existing_refresh_token=True,
            expected_refresh_token=redeemed_refresh_token,
            require_refresh_token_match=True,
        )

    async def set_authorization_result(
        self,
        tokens: OAuthToken,
        client_information: OAuthClientInformationFull,
    ) -> None:
        """Persist a matching registration and grant in one row update."""
        await self._persist_tokens(
            tokens,
            client_information,
            preserve_existing_refresh_token=False,
        )

    async def _persist_tokens(
        self,
        tokens: OAuthToken,
        client_information: OAuthClientInformationFull | None = None,
        *,
        preserve_existing_refresh_token: bool,
        expected_refresh_token: str | None = None,
        require_refresh_token_match: bool = False,
    ) -> bool:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session, for_update=True)
            config_data = extract_connection_data(config)
            existing_tokens_raw = config_data.get(MCPOAuthKeys.TOKENS.value)
            if require_refresh_token_match and (
                expected_refresh_token is None
                or (existing_tokens_raw or {}).get("refresh_token")
                != expected_refresh_token
            ):
                return False

            existing_client_information_raw = config_data.get(
                MCPOAuthKeys.CLIENT_INFO.value
            )
            if client_information is not None:
                try:
                    existing_client_information = (
                        OAuthClientInformationFull.model_validate(
                            existing_client_information_raw
                        )
                    )
                except ValidationError as error:
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        "MCP OAuth client registration changed while authorization "
                        "was pending.",
                    ) from error

                expected_client_fingerprint = (
                    self.expected_client_information_fingerprint
                    or mcp_oauth_client_information_fingerprint(client_information)
                )
                if (
                    mcp_oauth_client_information_fingerprint(client_information)
                    != expected_client_fingerprint
                    or mcp_oauth_client_information_fingerprint(
                        existing_client_information
                    )
                    != expected_client_fingerprint
                ):
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        "MCP OAuth client registration changed while authorization "
                        "was pending.",
                    )

                if (
                    self.expected_connection_headers_fingerprint is not None
                    and mcp_oauth_connection_headers_fingerprint(
                        config_data.get("headers", {})
                    )
                    != self.expected_connection_headers_fingerprint
                ):
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        "MCP connection headers changed while authorization was "
                        "pending.",
                    )

            persisted_token_dict = _token_dict_with_preserved_refresh(
                tokens,
                existing_tokens_raw,
                preserve_existing_refresh_token=preserve_existing_refresh_token,
            )
            config_data[MCPOAuthKeys.TOKENS.value] = persisted_token_dict
            token_expires_at_before_refresh = config_data.get(
                MCPOAuthKeys.TOKEN_EXPIRES_AT.value
            )
            expires_at = _absolute_token_expiry(tokens)
            if expires_at is not None:
                config_data[MCPOAuthKeys.TOKEN_EXPIRES_AT.value] = expires_at
            else:
                # No expires_in: drop any stale expiry so the next tool call
                # doesn't see the just-refreshed token as expired.
                config_data.pop(MCPOAuthKeys.TOKEN_EXPIRES_AT.value, None)
            # Persist discovered metadata so the next per-call provider can
            # refresh without repeating discovery.
            if (
                self._oauth_context is not None
                and self._oauth_context.oauth_metadata is not None
            ):
                config_data[MCPOAuthKeys.METADATA.value] = (
                    self._oauth_context.oauth_metadata.model_dump(mode="json")
                )
            config_data["headers"] = merge_mcp_headers(
                config_data.get("headers", {}),
                {"Authorization": f"{tokens.token_type} {tokens.access_token}"},
            )
            update_connection_config(config.id, db_session, config_data)

        if self.refresh_attempt_id and self.refresh_log_context:
            logger.info(
                "mcp_oauth.refresh.persisted",
                extra={
                    **self.refresh_log_context,
                    "request_id": ONYX_REQUEST_ID_CONTEXTVAR.get(),
                    "refresh_attempt_id": self.refresh_attempt_id,
                    "access_token_persisted": bool(
                        persisted_token_dict.get("access_token")
                    ),
                    "refresh_token_persisted": bool(
                        persisted_token_dict.get("refresh_token")
                    ),
                    "refresh_token_replaced": bool(
                        tokens.refresh_token
                        and tokens.refresh_token
                        != (existing_tokens_raw or {}).get("refresh_token")
                    ),
                    "token_expires_at_before_refresh": token_expires_at_before_refresh,
                    "token_expires_at_after_refresh": expires_at,
                    "token_expiry_persisted": expires_at is not None,
                },
            )
        return True

    async def discard_persisted_tokens(
        self, redeemed_refresh_token: str | None
    ) -> bool:
        """Drop the persisted grant (tokens, expiry, Authorization header) so
        the connection reads as unauthenticated until the user reconnects.

        No-ops when the stored refresh token no longer matches
        ``redeemed_refresh_token``: a concurrent refresh or reconnect already
        replaced the grant, and the replacement must survive. Returns whether
        the grant was discarded."""
        with get_session_with_current_tenant() as db_session:
            # Row lock: a concurrent set_tokens commit between an unlocked read
            # and the update below would be clobbered by this stale read.
            config = self._ensure_connection_config(db_session, for_update=True)
            config_data = extract_connection_data(config)
            stored_tokens = config_data.get(MCPOAuthKeys.TOKENS.value) or {}
            if (
                redeemed_refresh_token is None
                or stored_tokens.get("refresh_token") != redeemed_refresh_token
            ):
                return False
            config_data.pop(MCPOAuthKeys.TOKENS.value, None)
            config_data.pop(MCPOAuthKeys.TOKEN_EXPIRES_AT.value, None)
            config_data["headers"] = {
                key: value
                for key, value in config_data.get("headers", {}).items()
                if key.lower() != "authorization"
            }
            update_connection_config(config.id, db_session, config_data)
            return True

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            client_info_raw = config_data.get(MCPOAuthKeys.CLIENT_INFO.value)
            if client_info_raw:
                return OAuthClientInformationFull.model_validate(client_info_raw)
            if self.shared_client_config_id:
                shared_config = get_connection_config_by_id(
                    self.shared_client_config_id, db_session
                )
                if shared_config:
                    shared_config_data = extract_connection_data(shared_config)
                    shared_client_info = shared_config_data.get(
                        MCPOAuthKeys.CLIENT_INFO.value
                    )
                    if shared_client_info:
                        return OAuthClientInformationFull.model_validate(
                            shared_client_info
                        )
            return None

    async def set_client_info(  # ty: ignore[invalid-method-override]
        self, info: OAuthClientInformationFull
    ) -> None:
        info_payload = info.model_dump(mode="json")
        with get_session_with_current_tenant() as db_session:
            shared_config = None
            shared_config_data = None
            existing_shared_client_information = None
            if self.shared_client_config_id:
                shared_config = get_connection_config_by_id(
                    self.shared_client_config_id, db_session, for_update=True
                )
                if shared_config is not None:
                    shared_config_data = extract_connection_data(shared_config)
                    existing_shared_client_information_raw = shared_config_data.get(
                        MCPOAuthKeys.CLIENT_INFO.value
                    )
                    if existing_shared_client_information_raw:
                        existing_shared_client_information = (
                            OAuthClientInformationFull.model_validate(
                                existing_shared_client_information_raw
                            )
                        )

            config = self._ensure_connection_config(db_session, for_update=True)
            config_data = extract_connection_data(config)
            registration_conflict = (
                existing_shared_client_information is not None
                and existing_shared_client_information != info
            )
            selected_info_payload = (
                existing_shared_client_information.model_dump(mode="json")
                if registration_conflict
                else info_payload
            )
            config_data[MCPOAuthKeys.CLIENT_INFO.value] = selected_info_payload
            update_connection_config__no_commit(config.id, db_session, config_data)

            if shared_config is not None and shared_config_data is not None:
                shared_config_data[MCPOAuthKeys.CLIENT_INFO.value] = (
                    selected_info_payload
                )
                update_connection_config__no_commit(
                    shared_config.id, db_session, shared_config_data
                )
            db_session.commit()

            if registration_conflict:
                raise MCPClientRegistrationConflict(
                    "Concurrent MCP client registration selected a different client"
                )


AuthorizationRequestHandler = Callable[
    [MCPPendingOAuthAuthorization, OAuthContext], Awaitable[None]
]


class OAuthAuthorizationRequired(Exception):
    """Control signal for the browser boundary of a resumable OAuth flow.

    The MCP SDK currently has no resumable browser boundary, so this unwinds its
    inline HTTPX auth flow after the pending attempt has been persisted. Keep it
    as an ordinary exception so framework cancellation and error handling retain
    their normal Python semantics.
    """

    def __init__(self, authorization: MCPPendingOAuthAuthorization) -> None:
        super().__init__("MCP OAuth browser authorization is required")
        self.authorization = authorization


class OnyxOAuthClientProvider(OAuthClientProvider):
    """MCP SDK provider with an optional resumable browser handoff.

    Without a handoff, the provider can use or refresh existing credentials but
    cannot begin interactive authorization.
    """

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage,
        client_metadata_url: str | None = None,
        *,
        refresh_log_context: MCPRefreshLogContext,
        authorization_request_handler: AuthorizationRequestHandler | None = None,
    ) -> None:
        super().__init__(
            server_url=server_url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=None,
            callback_handler=None,
            client_metadata_url=client_metadata_url,
        )
        self.refresh_log_context = refresh_log_context
        self.authorization_request_handler = authorization_request_handler
        self.refresh_attempt_id: str | None = None
        self.token_expiry_before_refresh: float | None = None
        # The refresh token the in-flight refresh attempt redeemed; guards the
        # invalid_grant discard against wiping a concurrently stored grant.
        self.redeemed_refresh_token: str | None = None

    def build_resumable_authorization_request(
        self,
    ) -> MCPPendingOAuthAuthorization:
        """Build the browser request whose continuation can run in a later task."""
        redirect_uris = self.context.client_metadata.redirect_uris
        if not redirect_uris:
            raise OAuthFlowError(
                "No redirect URIs provided for authorization code grant"
            )
        client_info = self.context.client_info
        if client_info is None or not client_info.client_id:
            raise OAuthFlowError("No client info available for authorization")

        oauth_metadata = self.context.oauth_metadata
        authorization_endpoint = (
            str(oauth_metadata.authorization_endpoint)
            if oauth_metadata and oauth_metadata.authorization_endpoint
            else urljoin(
                self.context.get_authorization_base_url(self.context.server_url),
                "/authorize",
            )
        )
        pkce = PKCEParameters.generate()
        state = generate_authorization_state()
        authorization_params = {
            "response_type": "code",
            "client_id": client_info.client_id,
            "redirect_uri": str(redirect_uris[0]),
            "state": state,
            "code_challenge": pkce.code_challenge,
            "code_challenge_method": "S256",
        }
        if self.context.should_include_resource_param(self.context.protocol_version):
            authorization_params["resource"] = self.context.get_resource_url()
        if self.context.client_metadata.scope:
            authorization_params["scope"] = self.context.client_metadata.scope

        separator = "&" if "?" in authorization_endpoint else "?"
        authorization_url = ensure_offline_access_auth_params(
            f"{authorization_endpoint}{separator}{urlencode(authorization_params)}"
        )
        return MCPPendingOAuthAuthorization(
            authorization_url=authorization_url,
            state=state,
            code_verifier=pkce.code_verifier,
        )

    async def _perform_authorization_code_grant(self) -> tuple[str, str]:
        """Pause the SDK flow at the browser boundary for web applications.

        The upstream provider keeps PKCE and state in stack-local variables while
        awaiting its callback handler. In resumable mode we persist those values
        and unwind the HTTPX auth generator so the callback can run independently.
        """
        handler = self.authorization_request_handler
        if handler is None:
            raise MCPReauthenticationRequired()

        authorization = self.build_resumable_authorization_request()
        await handler(authorization, self.context)
        raise OAuthAuthorizationRequired(authorization)

    async def complete_authorization_code_exchange(
        self,
        authorization_code: str,
        code_verifier: str,
        *,
        resource: str | None = None,
    ) -> OAuthToken:
        """Exchange a callback code using a reconstructed SDK OAuth context."""
        redirect_uris = self.context.client_metadata.redirect_uris
        client_info = self.context.client_info
        if not redirect_uris or client_info is None or not client_info.client_id:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "MCP OAuth flow is missing client registration information.",
            )

        token_request = await self._exchange_token_authorization_code(
            authorization_code,
            code_verifier,
            token_data={"resource": resource} if resource else None,
        )

        try:
            async with mcp_ssrf_httpx_client_factory(
                timeout=httpx.Timeout(OAUTH_HTTP_TIMEOUT_SECONDS)
            ) as client:
                response = await client.send(token_request)
        except (SSRFException, ValueError) as error:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "MCP OAuth token endpoint is not allowed.",
            ) from error
        except httpx.HTTPError as error:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "MCP OAuth token exchange request failed.",
            ) from error

        if response.status_code != 200:
            body = await response.aread()
            oauth_error, _ = _oauth_error_from_response(
                body, response.headers.get("content-type")
            )
            detail = f"MCP OAuth token exchange failed ({response.status_code})"
            if oauth_error:
                detail += f": {oauth_error}"
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                detail,
            )

        try:
            tokens = await handle_token_response_scopes(response)
        except OAuthTokenError as error:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "MCP OAuth token endpoint returned an invalid token response.",
            ) from error
        self.context.current_tokens = tokens
        self.context.update_token_expiry(tokens)
        storage = self.context.storage
        if isinstance(storage, OnyxTokenStorage):
            await storage.set_authorization_result(tokens, client_info)
        else:
            await storage.set_tokens(tokens)
        return tokens

    def _refresh_log_fields(self, **fields: Any) -> dict[str, Any]:
        log_fields: dict[str, Any] = {
            **self.refresh_log_context,
            "request_id": ONYX_REQUEST_ID_CONTEXTVAR.get(),
            "refresh_attempt_id": self.refresh_attempt_id,
        }
        log_fields.update(fields)
        return log_fields

    async def _refresh_token(self) -> httpx.Request:
        self.refresh_attempt_id = uuid4().hex
        self.token_expiry_before_refresh = self.context.token_expiry_time
        current_tokens = self.context.current_tokens
        self.redeemed_refresh_token = (
            current_tokens.refresh_token if current_tokens else None
        )

        request = await super()._refresh_token()
        logger.info(
            "mcp_oauth.refresh.started",
            extra=self._refresh_log_fields(
                token_expires_at_before_refresh=self.token_expiry_before_refresh,
                token_endpoint_hostname=request.url.host,
                access_token_present=bool(
                    self.context.current_tokens
                    and self.context.current_tokens.access_token
                ),
                refresh_token_present=bool(
                    self.context.current_tokens
                    and self.context.current_tokens.refresh_token
                ),
            ),
        )
        return request

    async def _persist_refresh_tokens(self, tokens: OAuthToken) -> bool:
        storage = self.context.storage
        if not isinstance(storage, OnyxTokenStorage):
            await storage.set_tokens(tokens)
            return True

        storage.refresh_attempt_id = self.refresh_attempt_id
        try:
            return await storage.set_refreshed_tokens(
                tokens,
                self.redeemed_refresh_token,
            )
        finally:
            storage.refresh_attempt_id = None

    async def _handle_refresh_response(self, response: httpx.Response) -> bool:
        """Handle JSON and form-encoded refresh responses without logging secrets."""
        body = await response.aread()
        content_type = response.headers.get("content-type")
        oauth_error, body_format = _oauth_error_from_response(body, content_type)
        token_endpoint_hostname = _response_request_hostname(response)

        response_fields = self._refresh_log_fields(
            http_status=response.status_code,
            response_content_type=content_type,
            response_body_format=body_format,
            oauth_error=oauth_error,
            token_endpoint_hostname=token_endpoint_hostname,
        )

        if response.status_code != 200:
            logger.warning("mcp_oauth.refresh.failed", extra=response_fields)
            self.context.clear_tokens()
            # invalid_grant means the refresh token itself is expired or
            # revoked (RFC 6749) — discard the dead grant so the connection
            # reads as unauthenticated instead of retrying forever.
            storage = self.context.storage
            if oauth_error == "invalid_grant" and isinstance(storage, OnyxTokenStorage):
                if await storage.discard_persisted_tokens(self.redeemed_refresh_token):
                    logger.warning("mcp_oauth.tokens_discarded", extra=response_fields)
                else:
                    logger.info(
                        "mcp_oauth.tokens_discard_skipped_stale", extra=response_fields
                    )
            return False

        try:
            token_response = _oauth_token_from_response(body)
        except ValidationError:
            logger.warning("mcp_oauth.refresh.invalid_response", extra=response_fields)
            self.context.clear_tokens()
            return False

        self.context.current_tokens = token_response
        self.context.update_token_expiry(token_response)
        if not await self._persist_refresh_tokens(token_response):
            storage = self.context.storage
            current_tokens = await storage.get_tokens()
            if current_tokens is None:
                raise MCPRefreshSuperseded
            self.context.current_tokens = current_tokens
            logger.info(
                "mcp_oauth.refresh.superseded",
                extra=self._refresh_log_fields(
                    token_endpoint_hostname=token_endpoint_hostname,
                ),
            )
            return True
        logger.info(
            "mcp_oauth.refresh.succeeded",
            extra=self._refresh_log_fields(
                http_status=response.status_code,
                response_content_type=content_type,
                response_body_format=body_format,
                token_endpoint_hostname=token_endpoint_hostname,
            ),
        )
        return True


def make_oauth_provider(
    mcp_server: MCPServer,
    connection_config_id: int,
    shared_client_config_id: int | None,
    *,
    load_stored_tokens: bool = True,
    authorization_request_handler: AuthorizationRequestHandler | None = None,
    expected_connection_headers_fingerprint: str | None = None,
    expected_client_information_fingerprint: str | None = None,
) -> OnyxOAuthClientProvider:
    refresh_log_context = _refresh_log_context(mcp_server, connection_config_id)
    storage = OnyxTokenStorage(
        connection_config_id,
        shared_client_config_id,
        refresh_log_context,
        load_stored_tokens=load_stored_tokens,
        expected_connection_headers_fingerprint=(
            expected_connection_headers_fingerprint
        ),
        expected_client_information_fingerprint=(
            expected_client_information_fingerprint
        ),
    )
    client_metadata_url = (
        validated_mcp_oauth_client_metadata_url()
        if mcp_server.oauth_provider_mode is MCPOAuthProviderMode.AUTO_DISCOVERY
        else None
    )
    provider = OnyxOAuthClientProvider(
        refresh_log_context=refresh_log_context,
        server_url=mcp_server.server_url,
        client_metadata=OAuthClientMetadata(
            client_name=f"Onyx - {mcp_server.name}",
            redirect_uris=[AnyUrl(mcp_oauth_redirect_uri())],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=REQUESTED_SCOPE,  # TODO(evan): do we need to pass this in? maybe make configurable
            token_endpoint_auth_method="none",
        ),
        storage=storage,
        client_metadata_url=client_metadata_url,
        authorization_request_handler=authorization_request_handler,
    )

    # A fresh provider per tool call starts with an empty context, so the SDK
    # can't silently refresh without two hydrated fields: an absolute token
    # expiry (else `is_token_valid()` stays True and refresh never fires) and,
    # for known providers, the real OAuth metadata (else refresh hits the wrong
    # `<server-origin>/token`). Expiry is bound through storage so it rides the
    # config read `get_tokens` already does.
    storage.bind_oauth_context(provider.context)
    known_metadata = _known_provider_oauth_metadata(mcp_server)
    if known_metadata is not None:
        provider.context.oauth_metadata = known_metadata
    return provider
