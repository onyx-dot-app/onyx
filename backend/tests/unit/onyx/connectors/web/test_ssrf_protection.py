"""The web connector must not fetch internal/loopback targets (SSRF) anywhere in
its lifecycle — sitemap construction, validation, or indexing — at the default
VALIDATE_ALL level. Covers the recursive and sitemap paths (ON-001 / ON-002).

Targets use literal IPs so socket.getaddrinfo resolves locally (hermetic).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.web import connector as web_connector
from onyx.connectors.web.connector import check_internet_connection
from onyx.connectors.web.connector import extract_urls_from_sitemap
from onyx.connectors.web.connector import WEB_CONNECTOR_VALID_SETTINGS
from onyx.connectors.web.connector import WebConnector
from onyx.server.security.models import SSRFProtectionLevel

LOOPBACK_URL = "http://127.0.0.1:9999/ssrf-poc"
PRIVATE_URL = "http://10.0.0.5/internal"
# Cloud metadata endpoint (link-local).
METADATA_URL = "http://169.254.169.254/latest/meta-data/"


@pytest.fixture(autouse=True)
def _enforce_ssrf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the most restrictive SSRF level so ``protected_url_check`` enforces,
    independent of DB/env resolution."""
    monkeypatch.setattr(
        web_connector,
        "get_security_settings",
        lambda: SimpleNamespace(ssrf_protection_level=SSRFProtectionLevel.VALIDATE_ALL),
    )


def test_check_internet_connection_blocks_internal_before_fetch() -> None:
    """The connectivity primitive must reject an internal target before any GET."""
    with patch.object(web_connector.requests, "Session") as mock_session:
        with pytest.raises(ValueError, match="Non-global IP"):
            check_internet_connection(LOOPBACK_URL)
        mock_session.assert_not_called()


def test_extract_urls_from_sitemap_blocks_internal_before_fetch() -> None:
    """The sitemap fetch (runs in ``__init__``) must reject an internal target
    before any GET."""
    with patch.object(web_connector.requests, "get") as mock_get:
        with pytest.raises(ValueError, match="Non-global IP"):
            extract_urls_from_sitemap(PRIVATE_URL)
        mock_get.assert_not_called()


@pytest.mark.parametrize(
    "connector_type",
    [
        WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
        WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE.value,
    ],
)
def test_validate_rejects_internal_target_for_single_and_recursive(
    connector_type: str,
) -> None:
    """Validation must reject an internal base_url for both single and recursive."""
    connector = WebConnector(base_url=PRIVATE_URL, web_connector_type=connector_type)
    with pytest.raises(ConnectorValidationError, match="Protected URL check failed"):
        connector.validate_connector_settings()


def test_sitemap_connector_construction_blocks_internal() -> None:
    """A sitemap connector fetches at construction; an internal sitemap URL must
    fail before any outbound request — the connector can't even be instantiated."""
    with patch.object(web_connector.requests, "get") as mock_get:
        with pytest.raises(ValueError, match="Non-global IP"):
            WebConnector(
                base_url=METADATA_URL,
                web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SITEMAP.value,
            )
        mock_get.assert_not_called()
