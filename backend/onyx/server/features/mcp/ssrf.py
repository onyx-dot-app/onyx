"""SSRF protection for outbound MCP traffic.

The MCP SDK builds its own URLs from server responses (WWW-Authenticate, OAuth
metadata, redirects, dynamic client registration), so validating the stored
``server_url`` alone is insufficient. The guard is injected at the httpx
transport so every request the SDK makes — each redirect hop, discovery,
registration, and token request — is checked.
"""

import httpx
from fastapi.concurrency import run_in_threadpool

from onyx.auth.oauth_token_manager import validate_oauth_endpoint_url
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.security.models import outbound_ssrf_params, ssrf_error_hint
from onyx.server.security.store import get_security_settings
from onyx.utils.url import SSRFException, validate_outbound_http_url

# Mirror the MCP SDK defaults (see mcp.shared._httpx_utils.create_mcp_http_client).
_MCP_DEFAULT_TIMEOUT = 30.0
_MCP_DEFAULT_SSE_READ_TIMEOUT = 300.0


def validate_mcp_outbound_url(url: str, *, resolve_dns: bool = True) -> str:
    """SSRF guard for a URL the backend fetches in an MCP flow. Validation is
    driven by the admin ``SSRF Protection`` setting: at the VALIDATE_* levels
    private/internal targets are blocked; when DISABLED, private + loopback
    become reachable while cloud-metadata/link-local stays blocked.
    ``resolve_dns=False`` skips the DNS lookup at store time — the transport
    guard re-validates with DNS on every fetch."""
    params = outbound_ssrf_params(get_security_settings().ssrf_protection_level)
    return validate_outbound_http_url(
        url,
        allow_private_network=params.allow_private_network,
        block_loopback_and_link_local=params.block_loopback_and_link_local,
        block_link_local_only=params.block_link_local_only,
        resolve_dns=resolve_dns,
    )


class _SSRFGuardAsyncTransport(httpx.AsyncHTTPTransport):
    """SSRF-validates every request URL before sending. With
    ``follow_redirects=True`` httpx re-enters the transport per hop, so redirect
    targets are validated too."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await run_in_threadpool(validate_mcp_outbound_url, str(request.url))
        return await super().handle_async_request(request)


class _OAuthChallengeTransport(httpx.AsyncBaseTransport):
    """Drive OAuth with a local challenge and authenticated completion response."""

    def __init__(self, server_url: str, metadata_url: str) -> None:
        self._server_url = httpx.URL(server_url)
        self._metadata_url = metadata_url
        self._challenged = False
        self._delegate = _SSRFGuardAsyncTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url == self._server_url:
            if not self._challenged:
                self._challenged = True
                return httpx.Response(
                    status_code=401,
                    headers={
                        "WWW-Authenticate": (
                            f'Bearer resource_metadata="{self._metadata_url}"'
                        )
                    },
                    request=request,
                )
            # The SDK retries the original request after storing the token. The
            # OAuth connection is complete; no MCP request is needed here.
            return httpx.Response(status_code=204, request=request)

        return await self._delegate.handle_async_request(request)

    async def aclose(self) -> None:
        await self._delegate.aclose()


def mcp_ssrf_httpx_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Drop-in replacement for the MCP SDK's default client factory that swaps
    in an SSRF-guarded transport. Signature matches ``McpHttpClientFactory``."""
    return httpx.AsyncClient(
        auth=auth,
        follow_redirects=True,
        headers=headers,
        timeout=timeout
        or httpx.Timeout(_MCP_DEFAULT_TIMEOUT, read=_MCP_DEFAULT_SSE_READ_TIMEOUT),
        transport=_SSRFGuardAsyncTransport(),
    )


def mcp_oauth_challenge_httpx_client_factory(
    server_url: str,
    metadata_url: str,
    auth: httpx.Auth,
    timeout: httpx.Timeout,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        auth=auth,
        follow_redirects=True,
        timeout=timeout,
        transport=_OAuthChallengeTransport(server_url, metadata_url),
    )


def validate_mcp_url(url: str | None, field: str, *, require_https: bool) -> None:
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
            f"Invalid {field}: {e}{ssrf_error_hint(url, e)}",
        )
