"""Guards the SSRF policy for outbound MCP traffic: internal targets are blocked
by default; the private-network opt-in re-opens RFC1918 but loopback needs its
own MCP_SERVER_ALLOW_LOOPBACK gate (it reaches the app host itself), while
cloud-metadata/link-local and unspecified stay blocked under both opt-ins; the
httpx transport validates every hop; and the store-time error message steers
operators to the right remedy."""

import asyncio

import httpx
import pytest

from onyx.auth.oauth_token_manager import exchange_oauth_code_for_token
from onyx.auth.oauth_token_manager import OAuthFlowParams
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api
from onyx.tools.tool_implementations.mcp import mcp_ssrf
from onyx.utils.url import SSRFException

# IP literals (and the named host localhost, blocked by name) so validation never
# performs real DNS.
NAMED_BLOCKED = ["http://localhost:9000/mcp"]  # in BLOCKED_HOSTNAMES
METADATA_AND_UNSPECIFIED = [
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
    "http://0.0.0.0/mcp",  # unspecified
]
LOOPBACK = ["http://127.0.0.1:8010/mcp"]
PRIVATE_HOSTS = [
    "http://10.0.0.5/mcp",
    "http://192.168.1.10:3000/mcp",
    "http://172.16.0.1/mcp",
]
PUBLIC_HOSTS = [
    "http://8.8.8.8/mcp",
    "https://1.1.1.1/mcp",
]

# Never reachable, even with both opt-ins on.
ALWAYS_BLOCKED = NAMED_BLOCKED + METADATA_AND_UNSPECIFIED


def _allow_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_ssrf, "MCP_SERVER_ALLOW_PRIVATE_NETWORK", True)
    monkeypatch.setattr(api, "MCP_SERVER_ALLOW_PRIVATE_NETWORK", True)


def _allow_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Loopback also requires the private-network opt-in to take effect.
    _allow_private(monkeypatch)
    monkeypatch.setattr(mcp_ssrf, "MCP_SERVER_ALLOW_LOOPBACK", True)
    monkeypatch.setattr(api, "MCP_SERVER_ALLOW_LOOPBACK", True)


@pytest.mark.parametrize("url", ALWAYS_BLOCKED + LOOPBACK + PRIVATE_HOSTS)
def test_validate_blocks_internal_by_default(url: str) -> None:
    with pytest.raises(SSRFException):
        mcp_ssrf.validate_mcp_outbound_url(url)


@pytest.mark.parametrize("url", PUBLIC_HOSTS)
def test_validate_allows_public(url: str) -> None:
    assert mcp_ssrf.validate_mcp_outbound_url(url) == url


@pytest.mark.parametrize("url", PRIVATE_HOSTS)
def test_private_opt_in_allows_private(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_private(monkeypatch)
    assert mcp_ssrf.validate_mcp_outbound_url(url) == url


@pytest.mark.parametrize("url", LOOPBACK)
def test_private_opt_in_alone_still_blocks_loopback(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loopback reaches the app host itself, so the private-network opt-in alone
    must not unblock it — it needs the dedicated MCP_SERVER_ALLOW_LOOPBACK gate."""
    _allow_private(monkeypatch)
    with pytest.raises(SSRFException):
        mcp_ssrf.validate_mcp_outbound_url(url)


@pytest.mark.parametrize("url", LOOPBACK)
def test_loopback_opt_in_allows_loopback(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_loopback(monkeypatch)
    assert mcp_ssrf.validate_mcp_outbound_url(url) == url


@pytest.mark.parametrize("url", ALWAYS_BLOCKED)
def test_opt_in_still_blocks_metadata_and_named_hosts(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_loopback(monkeypatch)
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


@pytest.mark.parametrize(
    "url", ["http://localhost:9000/mcp", "http://169.254.169.254/x"]
)
def test_error_hint_for_never_allowed_omits_env_var(url: str) -> None:
    """Named hosts (localhost) and link-local/metadata can't be opted into, so
    the message must not dangle the env var as a remedy."""
    with pytest.raises(OnyxError) as exc_info:
        api._validate_mcp_server_url(url, "server_url", require_https=False)
    detail = exc_info.value.detail
    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert "never permitted" in detail
    assert "MCP_SERVER_ALLOW_PRIVATE_NETWORK" not in detail


def test_error_hint_for_private_points_at_private_var() -> None:
    with pytest.raises(OnyxError) as exc_info:
        api._validate_mcp_server_url(
            "http://10.0.0.5/mcp", "server_url", require_https=False
        )
    detail = exc_info.value.detail
    assert "MCP_SERVER_ALLOW_PRIVATE_NETWORK=true" in detail
    assert "never permitted" not in detail


def test_error_hint_for_loopback_points_at_loopback_var() -> None:
    """Loopback is opt-in-able via its own gate, so steer the operator there."""
    with pytest.raises(OnyxError) as exc_info:
        api._validate_mcp_server_url(
            "http://127.0.0.1:8010/mcp", "server_url", require_https=False
        )
    detail = exc_info.value.detail
    assert "MCP_SERVER_ALLOW_LOOPBACK=true" in detail
    assert "never permitted" not in detail


def test_error_hint_for_loopback_names_missing_private_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ALLOW_LOOPBACK on but ALLOW_PRIVATE_NETWORK off, loopback is still
    blocked (it needs both), so the hint must name the still-missing gate rather
    than going silent."""
    monkeypatch.setattr(mcp_ssrf, "MCP_SERVER_ALLOW_LOOPBACK", True)
    monkeypatch.setattr(api, "MCP_SERVER_ALLOW_LOOPBACK", True)
    with pytest.raises(OnyxError) as exc_info:
        api._validate_mcp_server_url(
            "http://127.0.0.1:8010/mcp", "server_url", require_https=False
        )
    detail = exc_info.value.detail
    assert "MCP_SERVER_ALLOW_PRIVATE_NETWORK=true" in detail
    assert "MCP_SERVER_ALLOW_LOOPBACK=true" not in detail


def test_store_time_allows_loopback_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirrors the integration test: with both opt-ins on, a loopback MCP server
    URL saves cleanly (the fetch-time transport guard applies the same policy)."""
    _allow_loopback(monkeypatch)
    api._validate_mcp_server_url(
        "http://127.0.0.1:8010/mcp", "server_url", require_https=False
    )


def test_oauth_endpoint_rejects_http_at_store_time() -> None:
    """http OAuth endpoints must fail at save time, matching the fetch-time
    https_only check, so a saved server can't silently fail the OAuth flow."""
    with pytest.raises(OnyxError) as exc_info:
        api._validate_mcp_server_url(
            "http://token.example.com/token", "oauth_token_endpoint", require_https=True
        )
    detail = exc_info.value.detail
    assert "https" in detail.lower()
    # Scheme failure shouldn't tack on the private-network hint.
    assert "MCP_SERVER_ALLOW_PRIVATE_NETWORK" not in detail


def test_server_url_allows_http() -> None:
    api._validate_mcp_server_url(
        "http://8.8.8.8/mcp", "server_url", require_https=False
    )


def test_exchange_raises_ssrf_for_internal_token_url() -> None:
    """Locks the contract the MCP callback relies on: an internal token endpoint
    fails with SSRFException (before any network call), so the callback's
    SSRFException handler converts it to a clean error instead of a 500."""
    params = OAuthFlowParams(
        authorization_url="https://provider.example.com/authorize",
        token_url="https://169.254.169.254/token",
        client_id="client-123",
    )
    with pytest.raises(SSRFException):
        exchange_oauth_code_for_token(
            params, code="abc", redirect_uri="https://onyx.example.com/cb"
        )
