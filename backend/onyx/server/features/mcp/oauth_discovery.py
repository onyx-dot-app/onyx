"""Read-only OAuth capability discovery and safe setup errors."""

import asyncio

import httpx
from mcp.client.auth.exceptions import OAuthRegistrationError
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_oauth_metadata_request,
    extract_resource_metadata_from_www_auth,
    handle_auth_metadata_response,
    handle_protected_resource_response,
)
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp.models import MCPOAuthDiscoveryResponse
from onyx.server.features.mcp.ssrf import mcp_ssrf_httpx_client_factory
from onyx.utils.url import SSRFException


async def discover_oauth_capabilities(server_url: str) -> MCPOAuthDiscoveryResponse:
    """Inspect public metadata without registering a client or sending credentials."""
    try:
        async with asyncio.timeout(15):
            return await _discover_oauth_capabilities(server_url)
    except (httpx.HTTPError, TimeoutError, ValueError, SSRFException):
        return MCPOAuthDiscoveryResponse(status="unreachable")


async def _discover_oauth_capabilities(server_url: str) -> MCPOAuthDiscoveryResponse:
    saw_server_error = False
    async with mcp_ssrf_httpx_client_factory(timeout=httpx.Timeout(5)) as client:
        # Stream the challenge: an SSE endpoint can keep a GET body open forever.
        async with client.stream("GET", server_url) as response:
            challenge_url = extract_resource_metadata_from_www_auth(response)
        auth_server_url: str | None = None
        for url in build_protected_resource_metadata_discovery_urls(
            challenge_url, server_url
        ):
            response = await client.send(create_oauth_metadata_request(url))
            saw_server_error |= response.status_code >= 500
            resource_metadata = await handle_protected_resource_response(response)
            if resource_metadata and check_resource_allowed(
                requested_resource=resource_url_from_server_url(server_url),
                configured_resource=str(resource_metadata.resource),
            ):
                auth_server_url = str(resource_metadata.authorization_servers[0])
                break
        for url in build_oauth_authorization_server_metadata_discovery_urls(
            auth_server_url, server_url
        ):
            response = await client.send(create_oauth_metadata_request(url))
            saw_server_error |= response.status_code >= 500
            _, metadata = await handle_auth_metadata_response(response)
            if metadata:
                return MCPOAuthDiscoveryResponse(
                    status="metadata_found",
                    supports_automatic_registration=bool(
                        metadata.registration_endpoint
                        or metadata.client_id_metadata_document_supported
                    ),
                    authorization_endpoint=str(metadata.authorization_endpoint),
                    token_endpoint=str(metadata.token_endpoint),
                )
    return MCPOAuthDiscoveryResponse(
        status="unreachable" if saw_server_error else "metadata_missing"
    )


def oauth_setup_error(error: Exception) -> OnyxError:
    """Do not expose upstream response bodies, URLs, or credentials to the browser."""
    if isinstance(error, ExceptionGroup):
        errors = [oauth_setup_error(child) for child in error.exceptions]
        return next(
            (item for item in errors if item.extra != {"oauth_error": "oauth_failed"}),
            errors[0],
        )
    if isinstance(error, OAuthRegistrationError):
        return OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Automatic OAuth client registration failed. Use your own OAuth client, or check the provider's registration requirements.",
            extra={"oauth_error": "client_registration_failed"},
        )
    if isinstance(error, (httpx.HTTPError, TimeoutError)):
        return OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Could not reach the OAuth provider. Check the server URL and try again.",
            extra={"oauth_error": "connection_failed"},
        )
    return OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        "OAuth setup failed. Check the provider's OAuth settings and try again.",
        extra={"oauth_error": "oauth_failed"},
    )
