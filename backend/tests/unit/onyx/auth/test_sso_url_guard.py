"""Which IdP URLs the server will fetch on an admin's behalf.

Where the admin is the operator, an IdP on their own network is a normal setup
and nothing here applies. Where the admin is one tenant among many, the same
URL is a request Onyx makes into its own network, so it is held to the public
internet. Both directions are guarded: over-blocking would break real IdPs.
"""

from unittest.mock import patch

import pytest

from onyx.auth.oauth_refresher import _get_oidc_token_endpoint
from onyx.auth.sso_url_guard import UnsafeSSOUrl, validate_idp_url

_CONFIG_PATH = "/.well-known/openid-configuration"


@pytest.mark.parametrize(
    "host",
    [
        "169.254.169.254",
        "127.0.0.1",
        "10.0.0.1",
        "[::1]",
        "[fc00::1]",
        # Python reports each of these as global, so `is_global` alone is not
        # the question being asked.
        "[fec0::1]",
        "[ff02::1]",
        # NAT64 and IPv4-mapped, both carrying 127.0.0.1.
        "[64:ff9b::7f00:1]",
        "[::ffff:127.0.0.1]",
        # 6to4 is deprecated (RFC 7526) and the stdlib treats the whole prefix
        # as private, so every 6to4 address is refused, loopback or not.
        "[2002:7f00:1::1]",
        "[2002:0808:0808::1]",
    ],
)
@patch("onyx.auth.sso_url_guard.MULTI_TENANT", True)
def test_rejects_addresses_off_the_public_internet(host: str) -> None:
    with pytest.raises(UnsafeSSOUrl):
        validate_idp_url(f"https://{host}{_CONFIG_PATH}", field="openid_config_url")


@pytest.mark.parametrize(
    "url",
    [
        f"http://idp.example.com{_CONFIG_PATH}",
        f"https://user:pw@idp.example.com{_CONFIG_PATH}",
        f"https:{_CONFIG_PATH}",
    ],
)
@patch("onyx.auth.sso_url_guard.MULTI_TENANT", True)
def test_rejects_malformed_or_unencrypted_urls(url: str) -> None:
    with pytest.raises(UnsafeSSOUrl):
        validate_idp_url(url, field="openid_config_url")


@pytest.mark.parametrize(
    "host",
    [
        "8.8.8.8",
        "[2001:4860:4860::8888]",
        "[2606:4700::1111]",
        # A public IPv4 wrapped as IPv4-mapped stays reachable (is_global judges
        # the embedded address).
        "[::ffff:8.8.8.8]",
    ],
)
@patch("onyx.auth.sso_url_guard.MULTI_TENANT", True)
def test_allows_public_addresses(host: str) -> None:
    validate_idp_url(f"https://{host}{_CONFIG_PATH}", field="openid_config_url")


@patch("onyx.auth.sso_url_guard.MULTI_TENANT", False)
def test_allows_private_hosts_when_self_hosted() -> None:
    """An IdP on the operator's own network is a normal self-hosted setup."""
    validate_idp_url(
        f"http://keycloak.internal{_CONFIG_PATH}", field="openid_config_url"
    )


@pytest.mark.asyncio
@patch("onyx.auth.sso_url_guard.MULTI_TENANT", True)
async def test_refresh_declines_a_private_discovery_url() -> None:
    """Refresh posts the client secret and the user's refresh token to whatever
    the document names, so it cannot fetch one login would not."""
    assert (
        await _get_oidc_token_endpoint(f"https://169.254.169.254{_CONFIG_PATH}") is None
    )
