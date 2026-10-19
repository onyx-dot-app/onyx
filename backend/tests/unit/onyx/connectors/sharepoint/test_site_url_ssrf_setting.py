"""SharePoint site URLs follow the shared SSRF Protection setting: the strict
levels block private hosts, the relaxed levels reach them, and cloud metadata
stays blocked at every level."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from onyx.connectors.sharepoint.connector_utils import (
    SiteUrlBlockedError,
    validate_site_url,
)
from onyx.server.security.models import SSRFProtectionLevel

_SITE_URL = "https://tenant.sharepoint.com/sites/MySite"
_SUFFIX = "sharepoint.com"
_PRIVATE_IP = "10.0.0.5"


@contextmanager
def _policy(level: SSRFProtectionLevel, resolves_to: str) -> Iterator[None]:
    """Pin the SSRF level and DNS so these tests never touch the network."""
    with patch(
        "onyx.connectors.sharepoint.connector_utils.get_security_settings"
    ) as settings:
        settings.return_value.ssrf_protection_level = level
        with patch("onyx.utils.url.socket.getaddrinfo") as getaddrinfo:
            getaddrinfo.return_value = [(2, 1, 6, "", (resolves_to, 443))]
            yield


@pytest.mark.parametrize(
    "level", [SSRFProtectionLevel.VALIDATE_ALL, SSRFProtectionLevel.VALIDATE_LLM]
)
def test_a_strict_level_blocks_a_private_host(level: SSRFProtectionLevel) -> None:
    with _policy(level, _PRIVATE_IP), pytest.raises(SiteUrlBlockedError):
        validate_site_url(_SITE_URL, _SUFFIX, "tenant")


@pytest.mark.parametrize(
    "level",
    [SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK, SSRFProtectionLevel.DISABLED],
)
def test_a_relaxed_level_reaches_a_private_host(level: SSRFProtectionLevel) -> None:
    with _policy(level, _PRIVATE_IP):
        validate_site_url(_SITE_URL, _SUFFIX, "tenant")


def test_cloud_metadata_stays_blocked_when_protection_is_off() -> None:
    with (
        _policy(SSRFProtectionLevel.DISABLED, "169.254.169.254"),
        pytest.raises(SiteUrlBlockedError),
    ):
        validate_site_url(_SITE_URL, _SUFFIX, "tenant")
