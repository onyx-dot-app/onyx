"""Resumable browser OAuth flows for MCP connections."""

import asyncio

import httpx
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth.utils import (
    build_protected_resource_metadata_discovery_urls,
    create_oauth_metadata_request,
    handle_protected_resource_response,
)
from pydantic import BaseModel, ConfigDict

from onyx.db.enums import MCPTransport
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp.client import initialize_mcp_client
from onyx.server.features.mcp.client_metadata import (
    is_mcp_oauth_cimd_client_id,
)
from onyx.server.features.mcp.models import (
    DENYLISTED_MCP_HEADERS,
)
from onyx.server.features.mcp.oauth import (
    OAUTH_HTTP_TIMEOUT_SECONDS,
    MCPClientRegistrationConflict,
    run_with_authorization_handoff,
)
from onyx.server.features.mcp.oauth_discovery import authorization_request_accepted
from onyx.server.features.mcp.ssrf import (
    mcp_oauth_challenge_httpx_client_factory,
    mcp_ssrf_httpx_client_factory,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class OAuthAlreadyAuthenticated(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)


class OAuthAuthorizationRedirect(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    url: str


type OAuthStartResult = OAuthAlreadyAuthenticated | OAuthAuthorizationRedirect


async def _start_oauth_from_well_known_metadata(
    oauth_provider: OAuthClientProvider,
    server_url: str,
    connection_headers: dict[str, str],
) -> None:
    timeout = httpx.Timeout(OAUTH_HTTP_TIMEOUT_SECONDS)
    discovery_urls = build_protected_resource_metadata_discovery_urls(None, server_url)
    metadata_url: str | None = None
    excluded_headers = DENYLISTED_MCP_HEADERS | {"authorization"}
    discovery_headers = {
        key: value
        for key, value in connection_headers.items()
        if key.lower() not in excluded_headers
    }
    async with mcp_ssrf_httpx_client_factory(timeout=timeout) as client:
        for url in discovery_urls:
            request = create_oauth_metadata_request(url)
            request.headers.update(discovery_headers)
            response = await client.send(request)
            if await handle_protected_resource_response(response) is not None:
                metadata_url = url
                break

    if metadata_url is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "OAuth auto-discovery could not find protected resource metadata at "
            "the MCP server's well-known URI. Check the URL or enter OAuth endpoints manually.",
            extra={"oauth_error": "discovery_failed"},
        )

    async with mcp_oauth_challenge_httpx_client_factory(
        server_url,
        metadata_url,
        oauth_provider,
        timeout,
    ) as client:
        await client.get(server_url)


async def validate_client_metadata_authorization(
    authorization_url: str, client_id: str | None
) -> None:
    """Pre-fetch the authorization URL so a provider that cannot read the CIMD
    document fails here, not on its error page. Network errors fail open."""
    if not is_mcp_oauth_cimd_client_id(client_id):
        return
    if await authorization_request_accepted(authorization_url) is not False:
        return
    logger.warning("MCP OAuth authorization pre-check rejected the client metadata")
    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        "The OAuth provider could not use this instance's client metadata document. "
        "If this instance is not reachable from the public internet, turn off "
        "'Use client metadata document' and connect again.",
        extra={"oauth_error": "client_metadata_rejected"},
    )


async def run_oauth_discovery(
    *,
    oauth_provider: OAuthClientProvider,
    server_url: str,
    connection_headers: dict[str, str],
    transport: MCPTransport,
    use_authenticated_connection: bool = False,
) -> OAuthStartResult:
    """Probe a connection, then fall back to protected-resource discovery."""
    try:
        async with asyncio.timeout(OAUTH_HTTP_TIMEOUT_SECONDS):
            try:
                authorization = await run_with_authorization_handoff(
                    initialize_mcp_client(
                        server_url,
                        connection_headers=connection_headers,
                        transport=transport,
                        auth=oauth_provider,
                    )
                )
                if authorization is not None:
                    return OAuthAuthorizationRedirect(
                        url=authorization.authorization_url
                    )
            except (ExceptionGroup, OnyxError):
                raise
            except Exception as error:
                if _client_registration_conflict(error) is not None:
                    raise
                if (
                    use_authenticated_connection
                    or oauth_provider.context.is_token_valid()
                ):
                    raise
                logger.info(
                    "Initial MCP OAuth probe failed; trying well-known discovery",
                    exc_info=True,
                )

            if use_authenticated_connection or oauth_provider.context.is_token_valid():
                return OAuthAlreadyAuthenticated()

            authorization = await run_with_authorization_handoff(
                _start_oauth_from_well_known_metadata(
                    oauth_provider,
                    server_url,
                    connection_headers,
                )
            )
            if authorization is not None:
                return OAuthAuthorizationRedirect(url=authorization.authorization_url)
    except TimeoutError as error:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Timed out during MCP OAuth discovery. Check the server URL and try again.",
            extra={"oauth_error": "connection_failed"},
        ) from error

    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        "OAuth auto-discovery did not produce an authorization redirect. Check the provider settings.",
        extra={"oauth_error": "discovery_failed"},
    )


def _client_registration_conflict(
    error: BaseException,
) -> MCPClientRegistrationConflict | None:
    if isinstance(error, MCPClientRegistrationConflict):
        return error
    if isinstance(error, BaseExceptionGroup):
        for nested_error in error.exceptions:
            if conflict := _client_registration_conflict(nested_error):
                return conflict
    return None
