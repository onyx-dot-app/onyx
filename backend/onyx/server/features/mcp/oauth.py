"""Shared MCP OAuth machinery: the SDK token storage/provider and their helpers.

Used by chat tool calls (`MCPTool.run`), the admin/user MCP API routes, and the
Craft sandbox proxy's token refresh — anything that authenticates against an
MCP server with the credentials persisted on `mcp_connection_config` rows.
Routes and route-only flow helpers stay in `api.py`.
"""

import asyncio
import json
import time
from typing import Any
from urllib.parse import urlparse

from mcp.client.auth import OAuthClientProvider
from mcp.client.auth import TokenStorage
from mcp.client.auth.oauth2 import OAuthContext
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthClientMetadata
from mcp.shared.auth import OAuthMetadata
from mcp.shared.auth import OAuthToken
from pydantic import AnyUrl
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import MCPOAuthProviderMode
from onyx.db.mcp import extract_connection_data
from onyx.db.mcp import get_connection_config_by_id
from onyx.db.mcp import update_connection_config
from onyx.db.models import MCPConnectionConfig
from onyx.db.models import MCPServer as DbMCPServer
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.mcp.models import MCPOAuthKeys
from onyx.server.features.mcp.ssrf import mcp_ssrf_httpx_client_factory
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_async_sync_no_cancel

logger = setup_logger()

# Refresh slightly before the real expiry to absorb network latency and clock
# skew between us and the provider, avoiding edge-of-expiry 401s.
TOKEN_EXPIRY_BUFFER_SECONDS = 30.0


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
    async with mcp_ssrf_httpx_client_factory() as client:
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
    """Sync wrapper for `_refresh_mcp_oauth_token_if_expired` (see there for
    behavior), for the sync `MCPTool.run` call site."""
    return run_async_sync_no_cancel(
        _refresh_mcp_oauth_token_if_expired(mcp_server, connection_config_id, user_id)
    )


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

    def __init__(self, connection_config_id: int, alt_config_id: int | None = None):
        self.alt_config_id = alt_config_id
        self.connection_config_id = connection_config_id
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
            config_data[MCPOAuthKeys.TOKENS.value] = _token_dict_with_preserved_refresh(
                tokens, existing_tokens_raw
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

    storage = OnyxTokenStorage(connection_config_id, admin_config_id)
    provider = OAuthClientProvider(
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
