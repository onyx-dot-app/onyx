"""SSRF protection for outbound MCP traffic.

The MCP SDK builds its own URLs from server responses (WWW-Authenticate, OAuth
metadata, redirects, dynamic client registration), so validating the stored
``server_url`` alone is insufficient. The guard is injected at the httpx
transport so every request the SDK makes — each redirect hop, discovery,
registration, and token request — is checked.
"""

from typing import Any

import httpx

from onyx.configs.app_configs import MCP_SERVER_ALLOW_LOOPBACK
from onyx.configs.app_configs import MCP_SERVER_ALLOW_PRIVATE_NETWORK
from onyx.utils.url import validate_outbound_http_url

# Mirror the MCP SDK defaults (see mcp.shared._httpx_utils.create_mcp_http_client).
_MCP_DEFAULT_TIMEOUT = 30.0
_MCP_DEFAULT_SSE_READ_TIMEOUT = 300.0


def validate_mcp_outbound_url(url: str, *, resolve_dns: bool = True) -> str:
    """SSRF guard for a URL the backend fetches in an MCP flow. Private targets
    gated behind ``MCP_SERVER_ALLOW_PRIVATE_NETWORK``; loopback needs the
    additional ``MCP_SERVER_ALLOW_LOOPBACK`` opt-in (it reaches the app host
    itself); cloud-metadata/link-local always blocked. ``resolve_dns=False``
    skips the DNS lookup at store time — the transport guard re-validates with
    DNS on every fetch."""
    return validate_outbound_http_url(
        url,
        allow_private_network=MCP_SERVER_ALLOW_PRIVATE_NETWORK,
        block_loopback_and_link_local=not MCP_SERVER_ALLOW_LOOPBACK,
        block_link_local_only=MCP_SERVER_ALLOW_LOOPBACK,
        resolve_dns=resolve_dns,
    )


class _SSRFGuardAsyncTransport(httpx.AsyncHTTPTransport):
    """SSRF-validates every request URL before sending. With
    ``follow_redirects=True`` httpx re-enters the transport per hop, so redirect
    targets are validated too."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        validate_mcp_outbound_url(str(request.url))
        return await super().handle_async_request(request)


def mcp_ssrf_httpx_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Drop-in replacement for the MCP SDK's default client factory that swaps
    in an SSRF-guarded transport. Signature matches ``McpHttpClientFactory``."""
    kwargs: dict[str, Any] = {
        "follow_redirects": True,
        "transport": _SSRFGuardAsyncTransport(),
        "timeout": timeout
        or httpx.Timeout(_MCP_DEFAULT_TIMEOUT, read=_MCP_DEFAULT_SSE_READ_TIMEOUT),
    }
    if headers is not None:
        kwargs["headers"] = headers
    if auth is not None:
        kwargs["auth"] = auth
    return httpx.AsyncClient(**kwargs)
