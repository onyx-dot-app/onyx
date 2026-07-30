"""Shared MCP OAuth machinery: the SDK token storage/provider and their helpers.

Used by chat tool calls (`MCPTool.run`), the admin/user MCP API routes, and the
Craft sandbox proxy's token refresh — anything that authenticates against an
MCP server with the credentials persisted on `mcp_connection_config` rows.
Routes and route-only flow helpers stay in `api.py`.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.auth.oauth2 import OAuthContext
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)
from pydantic import AnyUrl, BaseModel, ValidationError
from sqlalchemy.orm import Session

from onyx.cache.interface import CacheLockAcquisitionError
from onyx.cache.locks import cache_shared_lock
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import MCPOAuthProviderMode
from onyx.db.mcp import (
    extract_connection_data,
    get_connection_config_by_id,
    update_connection_config,
)
from onyx.db.models import MCPConnectionConfig
from onyx.db.models import MCPServer as DbMCPServer
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.mcp.models import MCPConnectionData, MCPOAuthKeys
from onyx.server.features.mcp.ssrf import mcp_ssrf_httpx_client_factory
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_async_sync_no_cancel
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


STATE_TTL_SECONDS = 60 * 5  # 5 minutes
OAUTH_WAIT_SECONDS = 30  # Give the user 30 seconds to complete the OAuth flow
UNUSED_RETURN_PATH = "unused_path"


def key_auth_url(user_id: str) -> str:
    return f"mcp:oauth:{user_id}:auth_url"


def key_state(user_id: str) -> str:
    return f"mcp:oauth:{user_id}:state"


def key_code(user_id: str, state: str) -> str:
    return f"mcp:oauth:{user_id}:{state}:codes"


def key_tokens(user_id: str) -> str:
    return f"mcp:oauth:{user_id}:tokens"


def key_client_info(user_id: str) -> str:
    return f"mcp:oauth:{user_id}:client_info"


REQUESTED_SCOPE: str | None = None


class MCPOauthState(BaseModel):
    server_id: int
    return_path: str
    is_admin: bool
    state: str
    code_verifier: str | None = None


class MCPRefreshLogContext(TypedDict):
    mcp_server_id: int | None
    mcp_server_name: str
    connection_config_id: int
    transport: str
    oauth_provider_mode: str


def _refresh_log_context(
    mcp_server: DbMCPServer, connection_config_id: int
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
    tokens: OAuthToken, existing_tokens_raw: dict[str, Any] | None
) -> dict[str, Any]:
    """Dump `tokens` for storage, carrying over a previously stored refresh
    token when the new payload omits one (providers like Google only issue a
    refresh token on the first authorization)."""
    token_dict = tokens.model_dump(mode="json")
    if token_dict.get("refresh_token") or not existing_tokens_raw:
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
    mcp_server: DbMCPServer,
    connection_config_id: int,
    user_id: str,
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
    # user_id only matters to redirect/callback handlers, never invoked here
    # since UNUSED_RETURN_PATH short-circuits them.
    provider = make_oauth_provider(
        mcp_server,
        user_id,
        UNUSED_RETURN_PATH,
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
    mcp_server: DbMCPServer,
    connection_config_id: int,
    user_id: str,
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
                _refresh_mcp_oauth_token_if_expired(
                    mcp_server, connection_config_id, user_id
                )
            )
    except CacheLockAcquisitionError:
        # Couldn't acquire within the wait; return whatever the winner persisted
        # (None if it hasn't finished and the stored token is still expired).
        logger.info(
            "mcp_token_refresh.lock_contended config_id=%s", connection_config_id
        )
        return _persisted_auth_header(connection_config_id)


def mcp_token_expired(config_data: MCPConnectionData) -> bool:
    """True iff the stored access token is past its persisted expiry."""
    expires_at = config_data.get(MCPOAuthKeys.TOKEN_EXPIRES_AT.value)
    return expires_at is not None and float(expires_at) <= time.time()


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


def _known_provider_oauth_metadata(mcp_server: DbMCPServer) -> OAuthMetadata | None:
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
        issuer=f"{parsed.scheme}://{parsed.netloc}",  # ty: ignore[invalid-argument-type]
        authorization_endpoint=mcp_server.oauth_authorization_endpoint,  # ty: ignore[invalid-argument-type]
        token_endpoint=mcp_server.oauth_token_endpoint,  # ty: ignore[invalid-argument-type]
    )


class OnyxTokenStorage(TokenStorage):
    """
    store auth info in a particular user's connection config in postgres
    """

    def __init__(
        self,
        connection_config_id: int,
        alt_config_id: int | None = None,
        refresh_log_context: MCPRefreshLogContext | None = None,
    ):
        self.alt_config_id = alt_config_id
        self.connection_config_id = connection_config_id
        self.refresh_log_context = refresh_log_context
        self.refresh_attempt_id: str | None = None
        # When bound, `get_tokens` hydrates its `token_expiry_time` from the
        # config read it already does — no separate query for the expiry.
        self._oauth_context: OAuthContext | None = None

    def bind_oauth_context(self, context: OAuthContext) -> None:
        self._oauth_context = context

    def _ensure_connection_config(self, db_session: Session) -> MCPConnectionConfig:
        config = get_connection_config_by_id(self.connection_config_id, db_session)
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
            if tokens_raw:
                return OAuthToken.model_validate(tokens_raw)
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            existing_tokens_raw = config_data.get(MCPOAuthKeys.TOKENS.value)
            persisted_token_dict = _token_dict_with_preserved_refresh(
                tokens, existing_tokens_raw
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
            config_data["headers"] = {
                "Authorization": f"{tokens.token_type} {tokens.access_token}"
            }
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

        # The shared admin row is intentionally NOT written here: it
        # serves as the OAuth `client_info` registry shared across all
        # users of this MCP server (see `get_client_info`). Per-user
        # state (access tokens and resolved `Authorization` headers)
        # belongs only on the per-user row. The Redis push below is
        # what `process_oauth_callback` blocks on to know token exchange
        # has completed; the admin config id is the only stable
        # identifier shared between the two contexts.
        if self.alt_config_id:
            r = get_redis_client()
            r.rpush(key_tokens(str(self.alt_config_id)), tokens.model_dump_json())
            r.expire(key_tokens(str(self.alt_config_id)), OAUTH_WAIT_SECONDS)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            client_info_raw = config_data.get(MCPOAuthKeys.CLIENT_INFO.value)
            if client_info_raw:
                return OAuthClientInformationFull.model_validate(client_info_raw)
            if self.alt_config_id:
                alt_config = get_connection_config_by_id(self.alt_config_id, db_session)
                if alt_config:
                    alt_config_data = extract_connection_data(alt_config)
                    alt_client_info = alt_config_data.get(
                        MCPOAuthKeys.CLIENT_INFO.value
                    )
                    if alt_client_info:
                        # Cache the admin client info on the user config for future calls
                        config_data[MCPOAuthKeys.CLIENT_INFO.value] = alt_client_info
                        update_connection_config(config.id, db_session, config_data)
                        return OAuthClientInformationFull.model_validate(
                            alt_client_info
                        )
            return None

    async def set_client_info(  # ty: ignore[invalid-method-override]
        self, info: OAuthClientInformationFull
    ) -> None:
        info_payload = info.model_dump(mode="json")
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            config_data[MCPOAuthKeys.CLIENT_INFO.value] = info_payload
            update_connection_config(config.id, db_session, config_data)

            # The shared admin row holds the OAuth `client_info` registry
            # used by every user of this MCP server (see `get_client_info`).
            # When DCR runs we want to cache the discovered client_info there
            # so future users can re-use it — but ONLY the `client_info`
            # field. The per-user `config_data` carries per-user state
            # (`tokens`, resolved `Authorization` header) which belongs
            # only on the per-user row.
            if self.alt_config_id:
                alt_config = get_connection_config_by_id(self.alt_config_id, db_session)
                alt_config_data = extract_connection_data(alt_config)
                alt_config_data[MCPOAuthKeys.CLIENT_INFO.value] = info_payload
                update_connection_config(
                    self.alt_config_id, db_session, alt_config_data
                )


class OnyxOAuthClientProvider(OAuthClientProvider):
    """MCP SDK OAuth provider with safe refresh telemetry and error parsing."""

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage,
        redirect_handler: Callable[[str], Awaitable[None]] | None = None,
        callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
        timeout: float = 300.0,
        client_metadata_url: str | None = None,
        *,
        refresh_log_context: MCPRefreshLogContext,
    ) -> None:
        super().__init__(
            server_url=server_url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            timeout=timeout,
            client_metadata_url=client_metadata_url,
        )
        self.refresh_log_context = refresh_log_context
        self.refresh_attempt_id: str | None = None
        self.token_expiry_before_refresh: float | None = None

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

    async def _persist_refresh_tokens(self, tokens: OAuthToken) -> None:
        storage = self.context.storage
        if not isinstance(storage, OnyxTokenStorage):
            await storage.set_tokens(tokens)
            return

        storage.refresh_attempt_id = self.refresh_attempt_id
        try:
            await storage.set_tokens(tokens)
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
            return False

        try:
            token_response = _oauth_token_from_response(body)
        except ValidationError:
            logger.warning("mcp_oauth.refresh.invalid_response", extra=response_fields)
            self.context.clear_tokens()
            return False

        self.context.current_tokens = token_response
        self.context.update_token_expiry(token_response)
        await self._persist_refresh_tokens(token_response)
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
    mcp_server: DbMCPServer,
    user_id: str,
    return_path: str,
    connection_config_id: int,
    admin_config_id: int | None,
) -> OAuthClientProvider:
    async def redirect_handler(auth_url: str) -> None:
        if return_path == UNUSED_RETURN_PATH:
            raise ValueError("Please Reconnect to the server")
        r = get_redis_client()
        # The SDK generated & embedded 'state' in the auth_url; extract & store it.
        parsed = urlparse(auth_url)
        qs = dict([p.split("=", 1) for p in parsed.query.split("&") if "=" in p])
        state = qs.get("state")
        if not state:
            # Defensive: some providers encode state differently; adapt if needed.
            raise RuntimeError("Missing state in authorization_url")

        # Save for the frontend & for callback validation
        state_obj = MCPOauthState(
            server_id=mcp_server.id,
            return_path=return_path,
            is_admin=admin_config_id is not None,
            state=state,
        )
        r.rpush(key_auth_url(user_id), auth_url)
        r.expire(key_auth_url(user_id), OAUTH_WAIT_SECONDS)
        r.set(key_state(user_id), state_obj.model_dump_json(), ex=STATE_TTL_SECONDS)

        # Return immediately; the HTTP layer will read the stored URL and send it to the browser.

    async def callback_handler() -> tuple[str, str | None]:
        r = get_redis_client()
        # Wait up to TTL for the code published by the /oauth/callback route
        state = r.get(key_state(user_id))
        if not state:
            raise RuntimeError("No pending OAuth state for user")
        state_obj = MCPOauthState.model_validate_json(state)

        # Block on Redis for (code, state). BLPOP returns (key, value).
        key = key_code(user_id, state_obj.state)

        # requests CAN block here for up to a minute if the user doesn't resolve the OAuth flow
        # Run the blocking blpop operation in a thread pool to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        pop = await loop.run_in_executor(
            None, lambda: r.blpop([key], timeout=OAUTH_WAIT_SECONDS)
        )
        # TODO(evan): gracefully handle "user says no"
        if not pop:
            raise RuntimeError("Timed out waiting for OAuth callback")

        code_state_dict = json.loads(pop[1].decode())

        code = code_state_dict["code"]

        if code_state_dict["state"] != state_obj.state:
            raise RuntimeError("Invalid state in OAuth callback")

        # Optional: cleanup
        r.delete(key_auth_url(user_id), key_state(user_id))
        return code, state_obj.state

    refresh_log_context = _refresh_log_context(mcp_server, connection_config_id)
    storage = OnyxTokenStorage(
        connection_config_id,
        admin_config_id,
        refresh_log_context,
    )
    provider = OnyxOAuthClientProvider(
        refresh_log_context=refresh_log_context,
        server_url=mcp_server.server_url,
        client_metadata=OAuthClientMetadata(
            client_name=f"Onyx - {mcp_server.name}",
            redirect_uris=[AnyUrl(f"{WEB_DOMAIN}/mcp/oauth/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=REQUESTED_SCOPE,  # TODO(evan): do we need to pass this in? maybe make configurable
            token_endpoint_auth_method="none",
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
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
