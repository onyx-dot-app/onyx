"""Unit tests for SharepointConnector site-page slim resilience and
validate_connector_settings RoleAssignments permission probe."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.sharepoint.connector import SharepointConnector

SITE_URL = "https://tenant.sharepoint.com/sites/MySite"


def _make_connector() -> SharepointConnector:
    connector = SharepointConnector(sites=[SITE_URL])
    connector.msal_app = MagicMock()
    connector.sp_tenant_domain = "tenant"
    connector._credential_json = {"sp_client_id": "x", "sp_directory_id": "y"}
    connector._graph_client = MagicMock()
    return connector


# ---------------------------------------------------------------------------
# _fetch_slim_documents_from_sharepoint — site page error resilience
# ---------------------------------------------------------------------------


@patch("onyx.connectors.sharepoint.connector._convert_sitepage_to_slim_document")
@patch(
    "onyx.connectors.sharepoint.connector.SharepointConnector._create_rest_client_context"
)
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_site_pages")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_driveitems")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector.fetch_sites")
def test_site_page_error_does_not_crash(
    mock_fetch_sites: MagicMock,
    mock_fetch_driveitems: MagicMock,
    mock_fetch_site_pages: MagicMock,
    _mock_create_ctx: MagicMock,
    mock_convert: MagicMock,
) -> None:
    """A 401 (or any exception) on a site page is caught; remaining pages are processed."""
    from onyx.connectors.models import SlimDocument

    connector = _make_connector()
    connector.include_site_documents = False
    connector.include_site_pages = True

    site = MagicMock()
    site.url = SITE_URL
    mock_fetch_sites.return_value = [site]
    mock_fetch_driveitems.return_value = iter([])

    page_ok = {"id": "1", "webUrl": SITE_URL + "/SitePages/Good.aspx"}
    page_bad = {"id": "2", "webUrl": SITE_URL + "/SitePages/Bad.aspx"}
    mock_fetch_site_pages.return_value = [page_bad, page_ok]

    good_slim = SlimDocument(id="1")

    def _convert_side_effect(
        page: dict, *_args: object, **_kwargs: object
    ) -> SlimDocument:  # noqa: ANN001
        if page["id"] == "2":
            from office365.runtime.client_request import ClientRequestException

            raise ClientRequestException(MagicMock(status_code=401), None)
        return good_slim

    mock_convert.side_effect = _convert_side_effect

    results = [
        doc
        for batch in connector._fetch_slim_documents_from_sharepoint()
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]

    # Only the good page makes it through; bad page is skipped, no exception raised.
    assert any(d.id == "1" for d in results)
    assert not any(d.id == "2" for d in results)


@patch("onyx.connectors.sharepoint.connector._convert_sitepage_to_slim_document")
@patch(
    "onyx.connectors.sharepoint.connector.SharepointConnector._create_rest_client_context"
)
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_site_pages")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_driveitems")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector.fetch_sites")
def test_all_site_pages_fail_does_not_crash(
    mock_fetch_sites: MagicMock,
    mock_fetch_driveitems: MagicMock,
    mock_fetch_site_pages: MagicMock,
    _mock_create_ctx: MagicMock,
    mock_convert: MagicMock,
) -> None:
    """When every site page fails, the generator completes without raising."""
    connector = _make_connector()
    connector.include_site_documents = False
    connector.include_site_pages = True

    site = MagicMock()
    site.url = SITE_URL
    mock_fetch_sites.return_value = [site]
    mock_fetch_driveitems.return_value = iter([])
    mock_fetch_site_pages.return_value = [
        {"id": "1", "webUrl": SITE_URL + "/SitePages/A.aspx"},
        {"id": "2", "webUrl": SITE_URL + "/SitePages/B.aspx"},
    ]
    mock_convert.side_effect = RuntimeError("context error")

    from onyx.connectors.models import SlimDocument

    # Should not raise; no SlimDocuments in output (only hierarchy nodes).
    slim_results = [
        doc
        for batch in connector._fetch_slim_documents_from_sharepoint()
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]
    assert slim_results == []


# ---------------------------------------------------------------------------
# validate_connector_settings — RoleAssignments permission probe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403])
@patch("onyx.connectors.sharepoint.connector.requests.get")
@patch("onyx.connectors.sharepoint.connector.validate_outbound_http_url")
@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
def test_validate_raises_on_401_or_403(
    mock_acquire: MagicMock,
    _mock_validate_url: MagicMock,
    mock_get: MagicMock,
    status_code: int,
) -> None:
    """validate_connector_settings raises ConnectorValidationError when probe returns 401 or 403."""
    mock_acquire.return_value = MagicMock(accessToken="tok")
    mock_get.return_value = MagicMock(status_code=status_code)

    connector = _make_connector()

    with pytest.raises(ConnectorValidationError, match="Sites.FullControl.All"):
        connector.validate_connector_settings()


@patch("onyx.connectors.sharepoint.connector.requests.get")
@patch("onyx.connectors.sharepoint.connector.validate_outbound_http_url")
@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
def test_validate_passes_on_200(
    mock_acquire: MagicMock,
    _mock_validate_url: MagicMock,
    mock_get: MagicMock,
) -> None:
    """validate_connector_settings does not raise when probe returns 200."""
    mock_acquire.return_value = MagicMock(accessToken="tok")
    mock_get.return_value = MagicMock(status_code=200)

    connector = _make_connector()
    connector.validate_connector_settings()  # should not raise


@patch("onyx.connectors.sharepoint.connector.requests.get")
@patch("onyx.connectors.sharepoint.connector.validate_outbound_http_url")
@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
def test_validate_passes_on_network_error(
    mock_acquire: MagicMock,
    _mock_validate_url: MagicMock,
    mock_get: MagicMock,
) -> None:
    """Network errors during the probe are non-blocking (logged as warning only)."""
    mock_acquire.return_value = MagicMock(accessToken="tok")
    mock_get.side_effect = Exception("timeout")

    connector = _make_connector()
    connector.validate_connector_settings()  # should not raise


@patch("onyx.connectors.sharepoint.connector.validate_outbound_http_url")
@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
def test_validate_skips_probe_without_credentials(
    mock_acquire: MagicMock,
    _mock_validate_url: MagicMock,
) -> None:
    """Probe is skipped when credentials have not been loaded."""
    connector = SharepointConnector(sites=[SITE_URL])
    # msal_app and sp_tenant_domain are None — probe must be skipped.
    connector.validate_connector_settings()  # should not raise
    mock_acquire.assert_not_called()
