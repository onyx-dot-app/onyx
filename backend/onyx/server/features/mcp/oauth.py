"""Shared MCP OAuth machinery: the SDK token storage/provider and their helpers.

Used by chat tool calls (`MCPTool.run`), the integration sign-in and the Craft
sandbox proxy: anything that authenticates against an MCP server with the
credentials of an `integration_connection` row.
"""

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, TypedDict
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from uuid import UUID, uuid4

import httpx
from mcp.client.auth import OAuthClientProvider, PKCEParameters, TokenStorage
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.oauth2 import OAuthContext
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)
from pydantic import AnyUrl, ValidationError
from sqlalchemy.orm import Session

from onyx.cache.interface import CacheLockAcquisitionError
from onyx.cache.locks import async_cache_shared_lock
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    IntegrationConnectionStatus,
    IntegrationOAuthProviderMode,
    MCPOAuthProviderMode,
)
from onyx.db.integration_connection import (
    get_connection,
    get_oauth_client,
    mark_connection_needs_reconnect__no_commit,
    set_oauth_client_credentials__no_commit,
    upsert_connection__no_commit,
)
from onyx.db.models import (
    Integration,
    IntegrationOAuthClient,
    MCPServer,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.connection_models import (
    OAUTH_CLIENT_INFO_KEY,
    OAUTH_METADATA_KEY,
    SIGN_IN_REJECTED_REASON,
    ConnectionSecret,
    OAuthClientCredentials,
    connection_refresh_lock_name,
    expiry_from_expires_in,
    read_connection,
    read_connection_secret,
    read_oauth_client,
)
from onyx.oauth.authorization_attempt import generate_authorization_state
from onyx.oauth.protocol import ensure_offline_access_auth_params
from onyx.server.features.mcp.client_metadata import (
    is_mcp_oauth_cimd_client_id,
    mcp_oauth_redirect_uri,
    validated_mcp_oauth_client_metadata_url,
)
from onyx.server.features.mcp.credentials import (
    mcp_oauth_client_information_fingerprint,
)
from onyx.server.features.mcp.models import (
    MCPPendingOAuthAuthorization,
    MCPServerConnection,
)
from onyx.server.features.mcp.ssrf import (
    mcp_ssrf_httpx_client_factory,
)
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException
from shared_configs.contextvars import ONYX_REQUEST_ID_CONTEXTVAR

logger = setup_logger()

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

# Refresh slightly before the real expiry to absorb network latency and clock
# skew between us and the provider, avoiding edge-of-expiry 401s.
TOKEN_EXPIRY_BUFFER_SECONDS = 30.0


REQUESTED_SCOPE: str | None = None

OAUTH_HTTP_TIMEOUT_SECONDS = 30.0


class MCPRefreshLogContext(TypedDict):
    mcp_server_id: int | None
    mcp_server_name: str
    connection_config_id: int | None
    transport: str
    oauth_provider_mode: str
    oauth_cimd_enabled: bool


class MCPClientRegistrationConflict(Exception):
    """Another request persisted the shared client registration first."""


class MCPRefreshSuperseded(Exception):
    """The grant changed while a refresh request was in flight."""


class MCPReauthenticationRequired(OAuthFlowError):
    """A non-interactive MCP operation requires a new browser grant."""

    def __init__(self) -> None:
        super().__init__("Please reconnect to the server through Onyx.")


def _refresh_log_context(
    mcp_server: MCPServer | MCPServerConnection, connection_config_id: int | None
) -> MCPRefreshLogContext:
    return {
        "mcp_server_id": mcp_server.id,
        "mcp_server_name": mcp_server.name,
        "connection_config_id": connection_config_id,
        "transport": mcp_server.transport.value if mcp_server.transport else "UNKNOWN",
        "oauth_provider_mode": mcp_server.oauth_provider_mode.value,
        "oauth_cimd_enabled": mcp_server.oauth_cimd_enabled,
    }


def oauth_error_from_response(
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


def oauth_token_from_response(body: bytes) -> OAuthToken:
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


def _known_provider_oauth_metadata(
    mcp_server: MCPServer | MCPServerConnection,
) -> OAuthMetadata | None:
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


def _authorization_handoffs(
    error: BaseException,
) -> list[OAuthAuthorizationRequired]:
    if isinstance(error, OAuthAuthorizationRequired):
        return [error]
    if isinstance(error, BaseExceptionGroup):
        return [
            handoff
            for nested_error in error.exceptions
            for handoff in _authorization_handoffs(nested_error)
        ]
    return []


async def run_with_authorization_handoff(
    operation: Awaitable[object],
) -> MCPPendingOAuthAuthorization | None:
    """Run one SDK operation, returning its resumable browser handoff.

    AnyIO may wrap the control signal in nested exception groups. A group that
    also contains a real failure is still a failure; only a single, otherwise
    clean handoff is converted into a normal result.
    """
    try:
        await operation
    except OAuthAuthorizationRequired as error:
        return error.authorization
    except ExceptionGroup as error:
        matching_errors, unexpected_errors = error.split(OAuthAuthorizationRequired)
        if unexpected_errors is not None:
            raise unexpected_errors
        if matching_errors is None:
            raise error
        handoffs = _authorization_handoffs(matching_errors)
        if len(handoffs) != 1:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "MCP OAuth discovery produced multiple authorization redirects.",
            )
        return handoffs[0].authorization
    return None


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
        authorization_state_factory: Callable[[], str] = generate_authorization_state,
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
        self.authorization_state_factory = authorization_state_factory
        self.refresh_attempt_id: str | None = None
        self.token_expiry_before_refresh: float | None = None
        # The refresh token the in-flight refresh attempt redeemed; guards the
        # invalid_grant discard against wiping a concurrently stored grant.
        self.redeemed_refresh_token: str | None = None

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Single-flight the refresh, then delegate to the SDK flow.

        The SDK serializes refreshes with a per-instance context lock, but every
        tool call builds its own provider — so concurrent calls each refresh on
        their own and providers that rotate refresh tokens (Snowflake, GitHub)
        reject the second redemption with invalid_grant, which can discard the
        grant entirely. Refresh here under the cross-process cache lock first;
        the SDK flow below then sees a valid token and skips its own refresh.
        """
        storage = self.context.storage
        refresh_lock_name = (
            storage.refresh_lock_name
            if isinstance(storage, IntegrationTokenStorage)
            else None
        )
        if refresh_lock_name is not None:
            await self._initialize()
            if not self.context.is_token_valid() and self.context.can_refresh_token():
                try:
                    async with async_cache_shared_lock(
                        refresh_lock_name,
                        max_time_lock_held_s=_REFRESH_LOCK_LEASE_S,
                        wait_for_lock_s=_REFRESH_LOCK_WAIT_S,
                        logger=logger,
                    ):
                        # The lock holder may have already refreshed; re-read
                        # the stored grant before redeeming the refresh token.
                        await self._initialize()
                        if (
                            not self.context.is_token_valid()
                            and self.context.can_refresh_token()
                        ):
                            refresh_request = await self._refresh_token()
                            refresh_response = yield refresh_request
                            await self._handle_refresh_response(refresh_response)
                except CacheLockAcquisitionError:
                    # Contention outlasted the wait; the SDK flow below retries
                    # its own refresh, no worse than the unlocked status quo.
                    logger.info(
                        "mcp_token_refresh.lock_contended lock=%s", refresh_lock_name
                    )

        sdk_flow = super().async_auth_flow(request)
        try:
            pending = await sdk_flow.__anext__()
            while True:
                try:
                    pending = await sdk_flow.asend((yield pending))
                except StopAsyncIteration:
                    return
        finally:
            await sdk_flow.aclose()

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
        state = self.authorization_state_factory()
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
            oauth_error, _ = oauth_error_from_response(
                body, response.headers.get("content-type")
            )
            detail = f"MCP OAuth token exchange failed ({response.status_code})"
            if oauth_error:
                detail += f": {oauth_error}"
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                detail,
            )

        body = await response.aread()
        try:
            tokens = oauth_token_from_response(body)
        except ValidationError:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "MCP OAuth token endpoint returned an invalid token response.",
            ) from None
        self.context.current_tokens = tokens
        self.context.update_token_expiry(tokens)
        storage = self.context.storage
        if isinstance(storage, IntegrationTokenStorage):
            await storage.set_authorization_result(tokens, client_info)
        else:
            await storage.set_tokens(tokens)
        return tokens

    async def build_refresh_request(self) -> httpx.Request | None:
        """Load the stored grant and build the SDK refresh request, or None
        when the grant cannot refresh."""
        await self._initialize()
        if not self.context.can_refresh_token():
            return None
        return await self._refresh_token()

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
        if not isinstance(storage, IntegrationTokenStorage):
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
        oauth_error, body_format = oauth_error_from_response(body, content_type)
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
            if oauth_error == "invalid_grant" and isinstance(
                storage, IntegrationTokenStorage
            ):
                if await storage.discard_persisted_tokens(self.redeemed_refresh_token):
                    logger.warning("mcp_oauth.tokens_discarded", extra=response_fields)
                else:
                    logger.info(
                        "mcp_oauth.tokens_discard_skipped_stale", extra=response_fields
                    )
            return False

        try:
            token_response = oauth_token_from_response(body)
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


def make_oauth_provider_with_storage(
    mcp_server: MCPServer | MCPServerConnection,
    storage: TokenStorage,
    *,
    connection_config_id: int | None = None,
    authorization_request_handler: AuthorizationRequestHandler | None = None,
    authorization_state_factory: Callable[[], str] = generate_authorization_state,
) -> OnyxOAuthClientProvider:
    """Build the shared provider for persisted or pending connections."""
    client_metadata_url = (
        validated_mcp_oauth_client_metadata_url()
        if mcp_server.oauth_provider_mode is MCPOAuthProviderMode.AUTO_DISCOVERY
        and mcp_server.oauth_cimd_enabled
        else None
    )
    provider = OnyxOAuthClientProvider(
        refresh_log_context=_refresh_log_context(mcp_server, connection_config_id),
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
        authorization_state_factory=authorization_state_factory,
    )

    known_metadata = _known_provider_oauth_metadata(mcp_server)
    if known_metadata is not None:
        provider.context.oauth_metadata = known_metadata
    return provider


def _oauth_token_from_secret(
    secret: ConnectionSecret, granted_scopes: list[str] | None
) -> OAuthToken | None:
    if not secret.access_token:
        return None
    return OAuthToken(
        access_token=secret.access_token,
        token_type="Bearer",
        refresh_token=secret.refresh_token,
        scope=" ".join(granted_scopes) if granted_scopes else None,
    )


def _secret_from_oauth_token(
    tokens: OAuthToken, previous: ConnectionSecret | None, *, keep_refresh: bool
) -> ConnectionSecret:
    refresh_token = tokens.refresh_token
    if refresh_token is None and keep_refresh and previous is not None:
        refresh_token = previous.refresh_token
    return ConnectionSecret(
        access_token=tokens.access_token,
        refresh_token=refresh_token,
        token_type=tokens.token_type,
        fields=previous.fields if previous is not None else {},
        headers=previous.headers if previous is not None else {},
    )


class IntegrationTokenStorage(TokenStorage):
    """MCP SDK storage over the integration tables: the grant lives in the
    ``integration_connection`` row of one user (or of the organization when
    ``user_id`` is None), and the client registration and discovered
    metadata live in ``integration_oauth_client``."""

    def __init__(
        self,
        integration_id: int,
        user_id: UUID | None,
        *,
        load_stored_tokens: bool = True,
        cimd_enabled: bool = True,
        expected_client_information_fingerprint: str | None = None,
        check_settings_unchanged: Callable[[Session], None] | None = None,
    ) -> None:
        self.integration_id = integration_id
        self.user_id = user_id
        self.load_stored_tokens = load_stored_tokens
        self.cimd_enabled = cimd_enabled
        self.expected_client_information_fingerprint = (
            expected_client_information_fingerprint
        )
        self.check_settings_unchanged = check_settings_unchanged
        self.refresh_attempt_id: str | None = None
        self._oauth_context: OAuthContext | None = None

    @property
    def refresh_lock_name(self) -> str:
        return connection_refresh_lock_name(self.integration_id, self.user_id)

    def bind_oauth_context(self, context: OAuthContext) -> None:
        self._oauth_context = context

    def _credentials(self, db_session: Session) -> OAuthClientCredentials:
        oauth_client = get_oauth_client(db_session, self.integration_id)
        if oauth_client is None:
            return OAuthClientCredentials()
        return read_oauth_client(oauth_client)

    async def get_tokens(self) -> OAuthToken | None:
        with get_session_with_current_tenant() as db_session:
            connection = get_connection(db_session, self.integration_id, self.user_id)
            record = read_connection(connection) if connection is not None else None
            if self._oauth_context is not None:
                # The buffer makes the SDK refresh a token that is about to expire.
                self._oauth_context.token_expiry_time = (
                    record.expires_at.timestamp() - TOKEN_EXPIRY_BUFFER_SECONDS
                    if record is not None and record.expires_at is not None
                    else None
                )
                if self._oauth_context.oauth_metadata is None:
                    metadata_raw = self._credentials(db_session).registration.get(
                        OAUTH_METADATA_KEY
                    )
                    if metadata_raw:
                        self._oauth_context.oauth_metadata = (
                            OAuthMetadata.model_validate(metadata_raw)
                        )
            if (
                record is None
                or not self.load_stored_tokens
                or record.status is IntegrationConnectionStatus.NEEDS_RECONNECT
            ):
                return None
            return _oauth_token_from_secret(record.secret, record.granted_scopes)

    async def set_tokens(self, tokens: OAuthToken) -> None:
        await self._persist_tokens(tokens, keep_refresh=True)

    async def set_refreshed_tokens(
        self, tokens: OAuthToken, redeemed_refresh_token: str | None
    ) -> bool:
        if redeemed_refresh_token is None:
            return False
        return await self._persist_tokens(
            tokens, keep_refresh=True, expected_refresh_token=redeemed_refresh_token
        )

    async def set_authorization_result(
        self, tokens: OAuthToken, client_information: OAuthClientInformationFull
    ) -> None:
        expected = (
            self.expected_client_information_fingerprint
            or mcp_oauth_client_information_fingerprint(client_information)
        )
        with get_session_with_current_tenant() as db_session:
            if self.check_settings_unchanged is not None:
                self.check_settings_unchanged(db_session)
            # The lock keeps the client from changing between the check and
            # the write of the grant.
            get_oauth_client(db_session, self.integration_id, for_update=True)
            # An entered client has no registration document, so compare the
            # client that the storage gives to the SDK.
            stored = self._client_information(db_session)
            if (
                mcp_oauth_client_information_fingerprint(client_information) != expected
                or stored is None
                or mcp_oauth_client_information_fingerprint(stored) != expected
            ):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "MCP OAuth client registration changed while authorization "
                    "was pending.",
                )
            self._write_tokens(db_session, tokens, keep_refresh=False)

    async def _persist_tokens(
        self,
        tokens: OAuthToken,
        *,
        keep_refresh: bool,
        expected_refresh_token: str | None = None,
    ) -> bool:
        with get_session_with_current_tenant() as db_session:
            return self._write_tokens(
                db_session,
                tokens,
                keep_refresh=keep_refresh,
                expected_refresh_token=expected_refresh_token,
            )

    def _write_tokens(
        self,
        db_session: Session,
        tokens: OAuthToken,
        *,
        keep_refresh: bool,
        expected_refresh_token: str | None = None,
    ) -> bool:
        # Lock the OAuth client before the connection, in the same order as
        # set_authorization_result, so the two paths cannot deadlock.
        metadata_client = self._lock_client_for_new_metadata(db_session)
        existing = get_connection(
            db_session, self.integration_id, self.user_id, for_update=True
        )
        record = read_connection(existing) if existing is not None else None
        previous = record.secret if record is not None else None
        if expected_refresh_token is not None and (
            record is None
            or record.status is not IntegrationConnectionStatus.CONNECTED
            or record.secret.refresh_token != expected_refresh_token
        ):
            return False
        secret = _secret_from_oauth_token(tokens, previous, keep_refresh=keep_refresh)
        upsert_connection__no_commit(
            db_session,
            integration_id=self.integration_id,
            user_id=self.user_id,
            secret=secret.model_dump(mode="json"),
            expires_at=expiry_from_expires_in(
                tokens.expires_in, datetime.now(timezone.utc)
            ),
            granted_scopes=(
                tokens.scope.split()
                if tokens.scope
                else (record.granted_scopes if record is not None else None)
            ),
        )
        if metadata_client is not None:
            oauth_client, metadata = metadata_client
            credentials = read_oauth_client(oauth_client)
            set_oauth_client_credentials__no_commit(
                db_session,
                oauth_client,
                client_id=credentials.client_id,
                client_secret=credentials.client_secret,
                registration={
                    **credentials.registration,
                    OAUTH_METADATA_KEY: metadata,
                },
            )
        db_session.commit()
        return True

    def _lock_client_for_new_metadata(
        self, db_session: Session
    ) -> tuple[IntegrationOAuthClient, dict[str, Any]] | None:
        """Returns the locked OAuth client and the discovered metadata when
        the client needs a write of that metadata."""
        if self._oauth_context is None or self._oauth_context.oauth_metadata is None:
            return None
        metadata = self._oauth_context.oauth_metadata.model_dump(mode="json")
        oauth_client = get_oauth_client(db_session, self.integration_id)
        if oauth_client is None or (
            oauth_client.legacy_format is None
            and read_oauth_client(oauth_client).registration.get(OAUTH_METADATA_KEY)
            == metadata
        ):
            return None
        oauth_client = get_oauth_client(
            db_session, self.integration_id, for_update=True
        )
        return None if oauth_client is None else (oauth_client, metadata)

    async def discard_persisted_tokens(
        self, redeemed_refresh_token: str | None
    ) -> bool:
        """A dead grant keeps its row and reads as Needs reconnect."""
        with get_session_with_current_tenant() as db_session:
            connection = get_connection(
                db_session, self.integration_id, self.user_id, for_update=True
            )
            if (
                connection is None
                or redeemed_refresh_token is None
                or read_connection_secret(connection).refresh_token
                != redeemed_refresh_token
            ):
                return False
            mark_connection_needs_reconnect__no_commit(
                db_session, connection, SIGN_IN_REJECTED_REASON
            )
            db_session.commit()
            return True

    def _client_information(
        self, db_session: Session
    ) -> OAuthClientInformationFull | None:
        credentials = self._credentials(db_session)
        stored_raw = credentials.registration.get(OAUTH_CLIENT_INFO_KEY)
        if stored_raw:
            client_info = OAuthClientInformationFull.model_validate(stored_raw)
            if not self.cimd_enabled and is_mcp_oauth_cimd_client_id(
                client_info.client_id
            ):
                return None
            return client_info
        # A client the admin entered has no registration document.
        client_id = credentials.client_id
        if not client_id:
            return None
        client_secret = credentials.client_secret
        return OAuthClientInformationFull(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uris=[AnyUrl(mcp_oauth_redirect_uri())],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=REQUESTED_SCOPE,
            token_endpoint_auth_method=(
                "client_secret_post" if client_secret else "none"
            ),
        )

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        with get_session_with_current_tenant() as db_session:
            return self._client_information(db_session)

    async def set_client_info(  # ty: ignore[invalid-method-override]
        self, info: OAuthClientInformationFull
    ) -> None:
        with get_session_with_current_tenant() as db_session:
            oauth_client = get_oauth_client(
                db_session, self.integration_id, for_update=True
            )
            if oauth_client is None:
                raise OnyxError(
                    OnyxErrorCode.NOT_FOUND, "The integration has no OAuth client."
                )
            registration = dict(read_oauth_client(oauth_client).registration)
            existing_raw = registration.get(OAUTH_CLIENT_INFO_KEY)
            if existing_raw is not None:
                existing = OAuthClientInformationFull.model_validate(existing_raw)
                usable = self.cimd_enabled or not is_mcp_oauth_cimd_client_id(
                    existing.client_id
                )
                if usable and existing != info:
                    raise MCPClientRegistrationConflict(
                        "Concurrent MCP client registration selected a different client"
                    )
            registration[OAUTH_CLIENT_INFO_KEY] = info.model_dump(mode="json")
            set_oauth_client_credentials__no_commit(
                db_session,
                oauth_client,
                client_id=info.client_id,
                client_secret=info.client_secret,
                registration=registration,
            )
            db_session.commit()


def integration_mcp_server_connection(
    mcp_server: MCPServer,
    integration: Integration,
    oauth_client: IntegrationOAuthClient,
) -> MCPServerConnection:
    """The server settings for the SDK, with the sign-in settings read from
    the integration tables."""
    return MCPServerConnection(
        id=mcp_server.id,
        name=integration.name,
        server_url=mcp_server.server_url,
        auth_type=mcp_server.auth_type,
        transport=mcp_server.transport,
        oauth_provider_mode=(
            MCPOAuthProviderMode.AUTO_DISCOVERY
            if oauth_client.provider_mode is IntegrationOAuthProviderMode.DISCOVERY
            else MCPOAuthProviderMode.KNOWN_PROVIDER
        ),
        oauth_cimd_enabled=oauth_client.cimd_enabled,
        oauth_authorization_endpoint=oauth_client.authorization_url,
        oauth_token_endpoint=oauth_client.token_url,
    )


def make_integration_oauth_provider(
    server: MCPServerConnection,
    storage: IntegrationTokenStorage,
    *,
    authorization_request_handler: AuthorizationRequestHandler | None = None,
) -> OnyxOAuthClientProvider:
    provider = make_oauth_provider_with_storage(
        server,
        storage,
        authorization_request_handler=authorization_request_handler,
    )
    storage.bind_oauth_context(provider.context)
    return provider
