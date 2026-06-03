"""Guards the SSRF policy for outbound MCP traffic: internal/loopback/metadata
targets are blocked by default, the private-network opt-in only re-opens RFC1918
(never loopback/cloud-metadata), the httpx transport validates every hop, and
the store-time error message steers operators to the right remedy."""

import asyncio

import httpx
import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api
from onyx.tools.tool_implementations.mcp import mcp_ssrf
from onyx.utils.url import SSRFException

# IP literals throughout so validation never performs real DNS.
ALWAYS_BLOCKED = [
    "http://localhost:9000/mcp",
    "http://127.0.0.1/mcp",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://0.0.0.0/mcp",  # unspecified
]
PRIVATE_HOSTS = [
    "http://10.0.0.5/mcp",
    "http://192.168.1.10:3000/mcp",
    "http://172.16.0.1/mcp",
]
PUBLIC_HOSTS = [
    "http://8.8.8.8/mcp",
    "https://1.1.1.1/mcp",
]


def _allow_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_ssrf, "MCP_SERVER_ALLOW_PRIVATE_NETWORK", True)
    monkeypatch.setattr(api, "MCP_SERVER_ALLOW_PRIVATE_NETWORK", True)


@pytest.mark.parametrize("url", ALWAYS_BLOCKED + PRIVATE_HOSTS)
def test_validate_blocks_internal_by_default(url: str) -> None:
    with pytest.raises(SSRFException):
        mcp_ssrf.validate_mcp_outbound_url(url)


@pytest.mark.parametrize("url", PUBLIC_HOSTS)
def test_validate_allows_public(url: str) -> None:
    assert mcp_ssrf.validate_mcp_outbound_url(url) == url


@pytest.mark.parametrize("url", PRIVATE_HOSTS)
def test_opt_in_allows_private(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_private(monkeypatch)
    assert mcp_ssrf.validate_mcp_outbound_url(url) == url


@pytest.mark.parametrize("url", ALWAYS_BLOCKED)
def test_opt_in_still_blocks_loopback_and_metadata(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_private(monkeypatch)
    with pytest.raises(SSRFException):
        mcp_ssrf.validate_mcp_outbound_url(url)


def test_factory_uses_guard_transport() -> None:
    client = mcp_ssrf.mcp_ssrf_httpx_client_factory(headers={"X-Test": "1"})
    try:
        assert client.follow_redirects is True
        assert isinstance(client._transport, mcp_ssrf._SSRFGuardAsyncTransport)
    finally:
        asyncio.run(client.aclose())


def test_transport_blocks_before_network() -> None:
    """A redirect hop to an internal address is rejected at the transport layer,
    so validation fires before any socket is opened."""
    transport = mcp_ssrf._SSRFGuardAsyncTransport()
    request = httpx.Request("GET", "http://169.254.169.254/latest/meta-data/")
    with pytest.raises(SSRFException):
        asyncio.run(transport.handle_async_request(request))


def test_error_hint_for_loopback_omits_env_var() -> None:
    with pytest.raises(OnyxError) as exc_info:
        api._validate_mcp_server_url("http://localhost:9000/mcp", "server_url")
    detail = exc_info.value.detail
    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert "never permitted" in detail
    assert "MCP_SERVER_ALLOW_PRIVATE_NETWORK" not in detail


def test_error_hint_for_private_points_at_env_var() -> None:
    with pytest.raises(OnyxError) as exc_info:
        api._validate_mcp_server_url("http://10.0.0.5/mcp", "server_url")
    detail = exc_info.value.detail
    assert "MCP_SERVER_ALLOW_PRIVATE_NETWORK=true" in detail
    assert "never permitted" not in detail
