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
# retrieve_all_slim_docs — pruning path skips permission fetching
# ---------------------------------------------------------------------------


@patch(
    "onyx.connectors.sharepoint.connector.SharepointConnector._create_rest_client_context"
)
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_site_pages")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_driveitems")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector.fetch_sites")
def test_retrieve_all_slim_docs_does_not_fetch_permissions(
    mock_fetch_sites: MagicMock,
    mock_fetch_driveitems: MagicMock,
    mock_fetch_site_pages: MagicMock,
    mock_create_ctx: MagicMock,
) -> None:
    """retrieve_all_slim_docs (pruning path) never calls _create_rest_client_context
    and returns SlimDocuments with empty ExternalAccess."""
    from onyx.connectors.models import ExternalAccess
    from onyx.connectors.models import SlimDocument
    from onyx.connectors.sharepoint.connector import DriveItemData

    connector = _make_connector()
    connector.include_site_documents = True
    connector.include_site_pages = True

    site = MagicMock()
    site.url = SITE_URL
    mock_fetch_sites.return_value = [site]

    driveitem = MagicMock(spec=DriveItemData)
    driveitem.id = "item-1"
    driveitem.web_url = SITE_URL + "/doc.docx"
    driveitem.parent_reference_path = None
    mock_fetch_driveitems.return_value = [
        (driveitem, "Documents", None),
    ]

    mock_fetch_site_pages.return_value = [
        {"id": "page-1", "webUrl": SITE_URL + "/SitePages/Home.aspx"},
    ]

    results = [
        doc
        for batch in connector.retrieve_all_slim_docs()
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]

    # Permissions were never fetched — no REST client context created.
    mock_create_ctx.assert_not_called()

    assert any(d.id == "item-1" for d in results)
    assert any(d.id == "page-1" for d in results)
    for doc in results:
        assert doc.external_access == ExternalAccess.empty()


# ---------------------------------------------------------------------------
# probe_role_assignments_permission — perm-sync RoleAssignments REST probe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403])
@patch("onyx.connectors.sharepoint.connector.requests.get")
@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
def test_probe_role_assignments_raises_on_401_or_403(
    mock_acquire: MagicMock,
    mock_get: MagicMock,
    status_code: int,
) -> None:
    """probe raises ConnectorValidationError naming the rejecting site."""
    mock_acquire.return_value = MagicMock(accessToken="tok")
    mock_get.return_value = MagicMock(status_code=status_code)

    connector = _make_connector()

    with pytest.raises(ConnectorValidationError) as exc_info:
        connector.probe_role_assignments_permission()
    assert "Sites.FullControl.All" in str(exc_info.value)
    assert SITE_URL in str(exc_info.value)


@patch("onyx.connectors.sharepoint.connector.requests.get")
@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
def test_probe_role_assignments_passes_on_200(
    mock_acquire: MagicMock,
    mock_get: MagicMock,
) -> None:
    """A 200 response means the app has the required permission."""
    mock_acquire.return_value = MagicMock(accessToken="tok")
    mock_get.return_value = MagicMock(status_code=200)

    connector = _make_connector()
    connector.probe_role_assignments_permission()  # should not raise


@patch("onyx.connectors.sharepoint.connector.requests.get")
@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
def test_probe_role_assignments_skips_on_network_error(
    mock_acquire: MagicMock,
    mock_get: MagicMock,
) -> None:
    """Per-site transport errors are non-blocking (treated as authorized)."""
    mock_acquire.return_value = MagicMock(accessToken="tok")
    mock_get.side_effect = Exception("timeout")

    connector = _make_connector()
    connector.probe_role_assignments_permission()  # should not raise


@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
def test_probe_role_assignments_skips_without_credentials(
    mock_acquire: MagicMock,
) -> None:
    """Probe is a no-op when credentials have not been loaded."""
    connector = SharepointConnector(sites=[SITE_URL])
    # msal_app and sp_tenant_domain are None — probe must be skipped.
    connector.probe_role_assignments_permission()  # should not raise
    mock_acquire.assert_not_called()


@patch("onyx.connectors.sharepoint.connector.requests.get")
@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
def test_probe_role_assignments_aggregates_unauthorized_sites(
    mock_acquire: MagicMock,
    mock_get: MagicMock,
) -> None:
    """When some sites 401 and others 200, the error names every failing site."""
    mock_acquire.return_value = MagicMock(accessToken="tok")

    site_ok = "https://tenant.sharepoint.com/sites/Allowed"
    site_bad_1 = "https://tenant.sharepoint.com/teams/Forbidden1"
    site_bad_2 = "https://tenant.sharepoint.com/teams/Forbidden2"

    def _fake_get(url: str, **_kwargs: object) -> MagicMock:
        if site_bad_1 in url:
            return MagicMock(status_code=401)
        if site_bad_2 in url:
            return MagicMock(status_code=403)
        return MagicMock(status_code=200)

    mock_get.side_effect = _fake_get

    connector = _make_connector()
    # _make_connector seeds a single site; override with a mixed list.
    connector.sites = [site_ok, site_bad_1, site_bad_2]

    with pytest.raises(ConnectorValidationError) as exc_info:
        connector.probe_role_assignments_permission()

    message = str(exc_info.value)
    assert site_bad_1 in message
    assert site_bad_2 in message
    assert site_ok not in message
    # All three sites should have been probed (in parallel).
    assert mock_get.call_count == 3


@patch("onyx.connectors.sharepoint.connector.requests.get")
@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
def test_probe_role_assignments_caps_probed_sites(
    mock_acquire: MagicMock,
    mock_get: MagicMock,
) -> None:
    """Only the first ROLE_ASSIGNMENTS_PROBE_MAX_SITES sites are probed."""
    from onyx.connectors.sharepoint.connector import ROLE_ASSIGNMENTS_PROBE_MAX_SITES

    mock_acquire.return_value = MagicMock(accessToken="tok")
    mock_get.return_value = MagicMock(status_code=200)

    connector = _make_connector()
    connector.sites = [
        f"https://tenant.sharepoint.com/sites/Site{i}"
        for i in range(ROLE_ASSIGNMENTS_PROBE_MAX_SITES + 2)
    ]

    connector.probe_role_assignments_permission()
    assert mock_get.call_count == ROLE_ASSIGNMENTS_PROBE_MAX_SITES


# ---------------------------------------------------------------------------
# probe_group_members_permission — perm-sync Graph group-members probe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403])
@patch("onyx.connectors.sharepoint.connector.requests.get")
@patch(
    "onyx.connectors.sharepoint.connector.SharepointConnector._get_graph_access_token"
)
def test_probe_group_members_raises_on_401_or_403(
    mock_token: MagicMock,
    mock_get: MagicMock,
    status_code: int,
) -> None:
    """probe raises ConnectorValidationError naming GroupMember.Read.All when Graph rejects."""
    mock_token.return_value = "tok"
    mock_get.return_value = MagicMock(status_code=status_code)

    connector = _make_connector()

    with pytest.raises(ConnectorValidationError, match="GroupMember.Read.All"):
        connector.probe_group_members_permission()


@patch("onyx.connectors.sharepoint.connector.requests.get")
@patch(
    "onyx.connectors.sharepoint.connector.SharepointConnector._get_graph_access_token"
)
def test_probe_group_members_passes_on_200(
    mock_token: MagicMock,
    mock_get: MagicMock,
) -> None:
    """A 200 response means the app has the required Graph permission."""
    mock_token.return_value = "tok"
    mock_get.return_value = MagicMock(status_code=200)

    connector = _make_connector()
    connector.probe_group_members_permission()  # should not raise
