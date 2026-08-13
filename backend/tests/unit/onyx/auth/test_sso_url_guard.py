"""Which IdP URLs the server will fetch on an admin's behalf.

Admin-configured IdP URLs run through the shared outbound-SSRF guard, so this
covers the guard's own job: reject credentials in the URL, delegate the address
check to that guard, and honor the SSRF Protection setting. A private IdP is
reachable only when the operator relaxes that setting.
"""

import time
from contextlib import AbstractContextManager
from unittest.mock import MagicMock, patch

import pytest

from onyx.auth import oauth_refresher
from onyx.auth.oauth_refresher import _get_oidc_token_endpoint
from onyx.auth.sso_url_guard import UnsafeSSOUrl, validate_idp_url
from onyx.server.security.models import SSRFProtectionLevel

_CONFIG_PATH = "/.well-known/openid-configuration"


def _at_level(level: SSRFProtectionLevel) -> AbstractContextManager[MagicMock]:
    settings = MagicMock()
    settings.ssrf_protection_level = level
    return patch("onyx.auth.sso_url_guard.get_security_settings", return_value=settings)


@pytest.mark.parametrize("host", ["169.254.169.254", "127.0.0.1", "10.0.0.1"])
def test_strict_level_rejects_private_targets(host: str) -> None:
    with _at_level(SSRFProtectionLevel.VALIDATE_ALL), pytest.raises(UnsafeSSOUrl):
        validate_idp_url(f"https://{host}{_CONFIG_PATH}", field="openid_config_url")


@pytest.mark.parametrize(
    "url",
    [
        f"http://idp.example.com{_CONFIG_PATH}",
        f"https://user:pw@idp.example.com{_CONFIG_PATH}",
    ],
)
def test_rejects_unencrypted_or_credentialed_urls(url: str) -> None:
    with _at_level(SSRFProtectionLevel.VALIDATE_ALL), pytest.raises(UnsafeSSOUrl):
        validate_idp_url(url, field="openid_config_url")


def test_strict_level_allows_a_public_address() -> None:
    with _at_level(SSRFProtectionLevel.VALIDATE_ALL):
        validate_idp_url(f"https://8.8.8.8{_CONFIG_PATH}", field="openid_config_url")


def test_disabled_level_allows_a_private_idp() -> None:
    """Relaxing the SSRF Protection setting is how a self-hosted operator points
    at an IdP on their own network."""
    with _at_level(SSRFProtectionLevel.DISABLED):
        validate_idp_url(f"https://10.0.0.1{_CONFIG_PATH}", field="openid_config_url")


@pytest.mark.asyncio
async def test_refresh_declines_a_private_discovery_url() -> None:
    """Refresh posts the client secret and the refresh token to whatever the
    document names, so it cannot fetch one login would not."""
    with _at_level(SSRFProtectionLevel.VALIDATE_ALL):
        assert (
            await _get_oidc_token_endpoint(f"https://169.254.169.254{_CONFIG_PATH}")
            is None
        )


@pytest.mark.asyncio
async def test_refresh_rechecks_a_cached_endpoint_when_policy_tightens() -> None:
    """A token endpoint cached under a looser setting is re-validated on the next
    refresh, so tightening the SSRF Protection setting is not bypassed."""
    config_url = f"https://8.8.8.8{_CONFIG_PATH}"
    oauth_refresher._OIDC_TOKEN_ENDPOINT_CACHE[config_url] = (
        "https://10.0.0.1/token",
        time.monotonic(),
    )
    try:
        with _at_level(SSRFProtectionLevel.VALIDATE_ALL):
            assert await _get_oidc_token_endpoint(config_url) is None
    finally:
        oauth_refresher._OIDC_TOKEN_ENDPOINT_CACHE.pop(config_url, None)
