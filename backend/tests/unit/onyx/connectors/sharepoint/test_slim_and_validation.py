"""Unit tests for SharepointConnector site-page slim resilience and
validate_connector_settings RoleAssignments permission probe."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.entra import EntraGroup, EntraPage
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.models import ExternalAccess, SlimDocument
from onyx.connectors.sharepoint.connector import (
    FetchedDriveItem,
    SharepointConnector,
    SiteDrive,
    _convert_sitepage_to_document,
    _convert_sitepage_to_slim_document,
)
from onyx.connectors.sharepoint.connector_utils import SharepointPermissionCache
from tests.unit.onyx.connectors.sharepoint.sharepoint_gateway_fakes import (
    connector_with_gateway,
    fake_gateway,
    stub_operation,
)

SITE_URL = "https://tenant.sharepoint.com/sites/MySite"


def _make_connector() -> SharepointConnector:
    connector = SharepointConnector(sites=[SITE_URL])
    connector_with_gateway(connector)
    return connector


def _stub_auth_method(
    connector: SharepointConnector, method: MicrosoftAuthMethod
) -> None:
    stub_operation(connector.ops, "get_auth_method", lambda: method)


def _stub_rest_probe(
    connector: SharepointConnector, refused_sites: dict[str, bool] | None = None
) -> list[str]:
    """Answers the REST probe per site and records which sites were asked.
    Sites absent from ``refused_sites`` pass."""
    probed: list[str] = []
    refused = refused_sites or {}

    def probe_rest_access(*, site_url: str) -> bool:
        probed.append(site_url)
        return not refused.get(site_url, False)

    stub_operation(connector.ops, "probe_rest_access", probe_rest_access)
    return probed


@patch("onyx.connectors.sharepoint.connector.get_sharepoint_external_access")
def test_full_and_slim_site_pages_share_permission_resolution(
    mock_get_access: MagicMock,
) -> None:
    access = ExternalAccess(
        external_user_emails={"alice@contoso.com"},
        external_user_group_ids={"engineering"},
        is_public=False,
    )
    mock_get_access.return_value = access
    permission_cache = SharepointPermissionCache()
    ops = fake_gateway(sites=[SITE_URL])
    site_page = {
        "id": "page-1",
        "webUrl": f"{SITE_URL}/SitePages/Home.aspx",
        "title": "Home",
        "name": "Home.aspx",
    }

    full_document = _convert_sitepage_to_document(
        site_page,
        "MySite",
        ops,
        SITE_URL,
        permission_cache,
        include_permissions=True,
    )
    slim_document = _convert_sitepage_to_slim_document(
        site_page,
        ops,
        SITE_URL,
        permission_cache,
    )

    assert full_document.external_access == slim_document.external_access == access
    assert all(
        call.kwargs["permission_cache"] is permission_cache
        for call in mock_get_access.call_args_list
    )


# ---------------------------------------------------------------------------
# _fetch_slim_documents_from_sharepoint — site page error resilience
# ---------------------------------------------------------------------------


@patch("onyx.connectors.sharepoint.connector._convert_driveitem_to_slim_document")
@patch(
    "onyx.connectors.sharepoint.connector.get_sharepoint_hierarchy_node_external_access",
    return_value=ExternalAccess.empty(),
)
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_driveitems")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector.fetch_sites")
def test_slim_permission_sync_skips_missing_list_id_and_continues(
    mock_fetch_sites: MagicMock,
    mock_fetch_driveitems: MagicMock,
    _mock_get_access: MagicMock,
    mock_convert: MagicMock,
) -> None:
    connector = _make_connector()
    connector.include_site_documents = True
    connector.include_site_pages = False
    site = MagicMock(url=SITE_URL)
    mock_fetch_sites.return_value = [site]

    def fetched_item(item_id: str, list_id: str | None) -> FetchedDriveItem:
        return FetchedDriveItem(
            driveitem=DriveItemData(
                id=item_id,
                name=f"{item_id}.pdf",
                web_url=f"{SITE_URL}/{item_id}.pdf",
            ),
            drive=SiteDrive(
                drive_id=f"{item_id}-drive",
                display_name=item_id,
                web_url=f"{SITE_URL}/{item_id}",
                list_id=list_id,
            ),
        )

    missing = fetched_item("missing", None)
    valid = fetched_item("valid", "valid-list")
    mock_fetch_driveitems.return_value = [missing, valid]
    mock_convert.return_value = SlimDocument(id="valid")

    results = [
        item
        for batch in connector._fetch_slim_documents_from_sharepoint()
        for item in batch
        if isinstance(item, SlimDocument)
    ]

    assert [item.id for item in results] == ["valid"]
    assert mock_convert.call_args.args[0] is valid.driveitem


@patch("onyx.connectors.sharepoint.connector._convert_sitepage_to_slim_document")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_site_pages")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_driveitems")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector.fetch_sites")
def test_site_page_error_does_not_crash(
    mock_fetch_sites: MagicMock,
    mock_fetch_driveitems: MagicMock,
    mock_fetch_site_pages: MagicMock,
    mock_convert: MagicMock,
) -> None:
    """A 401 (or any exception) on a site page is caught; remaining pages are processed."""
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
            raise MicrosoftGraphError(401, "unauthorized", "x")
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
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_site_pages")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_driveitems")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector.fetch_sites")
def test_all_site_pages_fail_does_not_crash(
    mock_fetch_sites: MagicMock,
    mock_fetch_driveitems: MagicMock,
    mock_fetch_site_pages: MagicMock,
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

    # Should not raise; no SlimDocuments in output (only hierarchy nodes).
    slim_results = [
        doc
        for batch in connector._fetch_slim_documents_from_sharepoint()
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]
    assert slim_results == []


# ---------------------------------------------------------------------------
# _fetch_slim_documents_from_sharepoint — `_fetch_site_pages` raising
# ---------------------------------------------------------------------------


@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_site_pages")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_driveitems")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector.fetch_sites")
def test_fetch_site_pages_runtime_error_does_not_crash_slim_run(
    mock_fetch_sites: MagicMock,
    mock_fetch_driveitems: MagicMock,
    mock_fetch_site_pages: MagicMock,
) -> None:
    """When `_fetch_site_pages` itself raises a non-Graph-4xx (e.g. a
    RuntimeError, 500, JSON decode error), the broadened outer except still
    log-and-skips so other sites can finish."""
    connector = _make_connector()
    connector.include_site_documents = False
    connector.include_site_pages = True

    bad_site = MagicMock()
    bad_site.url = SITE_URL + "/Bad"
    good_site = MagicMock()
    good_site.url = SITE_URL + "/Good"
    mock_fetch_sites.return_value = [bad_site, good_site]
    mock_fetch_driveitems.return_value = iter([])

    good_page = {"id": "g1", "webUrl": good_site.url + "/SitePages/Home.aspx"}

    def _fetch_side_effect(
        site_descriptor: object, *_args: object, **_kwargs: object
    ) -> list[dict[str, str]]:
        if (
            getattr(site_descriptor, "url", None)  # ods: ignore[getattr]
            == bad_site.url
        ):
            raise RuntimeError("pages endpoint blew up")
        return [good_page]

    mock_fetch_site_pages.side_effect = _fetch_side_effect

    slim_results = [
        doc
        for batch in connector._fetch_slim_documents_from_sharepoint(
            include_permissions=False
        )
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]

    # Good site's page survives; bad site is silently skipped (slim retrieval
    # can't yield ConnectorFailure).
    assert [d.id for d in slim_results] == ["g1"]


# ---------------------------------------------------------------------------
# retrieve_all_slim_docs — pruning path skips permission fetching
# ---------------------------------------------------------------------------


@patch("onyx.connectors.sharepoint.connector.get_sharepoint_external_access")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_site_pages")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector._fetch_driveitems")
@patch("onyx.connectors.sharepoint.connector.SharepointConnector.fetch_sites")
def test_retrieve_all_slim_docs_does_not_fetch_permissions(
    mock_fetch_sites: MagicMock,
    mock_fetch_driveitems: MagicMock,
    mock_fetch_site_pages: MagicMock,
    mock_get_access: MagicMock,
) -> None:
    """retrieve_all_slim_docs (pruning path) never resolves external access
    and returns SlimDocuments with empty ExternalAccess."""
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
    driveitem.created_datetime = None
    mock_fetch_driveitems.return_value = [
        FetchedDriveItem(
            driveitem=driveitem,
            drive=SiteDrive(
                drive_id="drive-id",
                list_id="list-id",
                display_name="Documents",
                web_url=f"{SITE_URL}/Shared%20Documents",
            ),
        ),
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

    # Permissions were never fetched.
    mock_get_access.assert_not_called()

    assert any(d.id == "item-1" for d in results)
    assert any(d.id == "page-1" for d in results)
    for doc in results:
        assert doc.external_access == ExternalAccess.empty()


# ---------------------------------------------------------------------------
# probe_role_assignments_permission — perm-sync RoleAssignments REST probe
# ---------------------------------------------------------------------------


def test_probe_role_assignments_raises_on_401_or_403() -> None:
    """A refused probe raises ConnectorValidationError naming the rejecting site."""
    connector = _make_connector()
    _stub_auth_method(connector, MicrosoftAuthMethod.CERTIFICATE)
    _stub_rest_probe(connector, {SITE_URL: True})

    with pytest.raises(ConnectorValidationError) as exc_info:
        connector.probe_role_assignments_permission()
    assert "Sites.FullControl.All" in str(exc_info.value)
    assert SITE_URL in str(exc_info.value)


def test_probe_role_assignments_passes_on_200() -> None:
    """An accepted probe means the app has the required permission."""
    connector = _make_connector()
    _stub_auth_method(connector, MicrosoftAuthMethod.CERTIFICATE)
    probed = _stub_rest_probe(connector)

    connector.probe_role_assignments_permission()  # should not raise
    assert probed == [SITE_URL]


def test_probe_role_assignments_skips_on_network_error() -> None:
    """A probe that raises is not a refusal, so it does not block validation."""
    connector = _make_connector()
    _stub_auth_method(connector, MicrosoftAuthMethod.CERTIFICATE)

    def probe_rest_access(*, site_url: str) -> bool:  # noqa: ARG001
        raise RuntimeError("timeout")

    stub_operation(connector.ops, "probe_rest_access", probe_rest_access)

    connector.probe_role_assignments_permission()  # should not raise


def test_probe_role_assignments_skips_without_credentials() -> None:
    """Probe is a no-op when credentials have not been loaded."""
    connector = SharepointConnector(sites=[SITE_URL])
    # No gateway is attached, so there is nothing to probe with.
    connector.probe_role_assignments_permission()  # should not raise


def test_probe_role_assignments_aggregates_unauthorized_sites() -> None:
    """When some sites refuse and others accept, the error names every failing site."""
    site_ok = "https://tenant.sharepoint.com/sites/Allowed"
    site_bad_1 = "https://tenant.sharepoint.com/teams/Forbidden1"
    site_bad_2 = "https://tenant.sharepoint.com/teams/Forbidden2"

    connector = _make_connector()
    # _make_connector seeds a single site; override with a mixed list.
    connector.sites = [site_ok, site_bad_1, site_bad_2]
    _stub_auth_method(connector, MicrosoftAuthMethod.CERTIFICATE)
    probed = _stub_rest_probe(connector, {site_bad_1: True, site_bad_2: True})

    with pytest.raises(ConnectorValidationError) as exc_info:
        connector.probe_role_assignments_permission()

    message = str(exc_info.value)
    assert site_bad_1 in message
    assert site_bad_2 in message
    assert site_ok not in message
    # All three sites should have been probed (in parallel).
    assert sorted(probed) == sorted([site_ok, site_bad_1, site_bad_2])


def test_probe_role_assignments_caps_probed_sites() -> None:
    """Only the first ROLE_ASSIGNMENTS_PROBE_MAX_SITES sites are probed."""
    from onyx.connectors.sharepoint.connector import ROLE_ASSIGNMENTS_PROBE_MAX_SITES

    connector = _make_connector()
    connector.sites = [
        f"https://tenant.sharepoint.com/sites/Site{i}"
        for i in range(ROLE_ASSIGNMENTS_PROBE_MAX_SITES + 2)
    ]
    _stub_auth_method(connector, MicrosoftAuthMethod.CERTIFICATE)
    probed = _stub_rest_probe(connector)

    connector.probe_role_assignments_permission()
    assert len(probed) == ROLE_ASSIGNMENTS_PROBE_MAX_SITES


# ---------------------------------------------------------------------------
# probe_group_members_permission — perm-sync Graph group-members probe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403])
def test_probe_group_members_raises_on_401_or_403(status_code: int) -> None:
    """probe raises ConnectorValidationError naming GroupMember.Read.All when Graph rejects."""
    connector = _make_connector()

    def list_entra_groups(**_kwargs: object) -> EntraPage[EntraGroup]:
        raise MicrosoftGraphError(status_code, "accessDenied", "x")

    stub_operation(connector.ops, "list_entra_groups", list_entra_groups)

    with pytest.raises(ConnectorValidationError, match="GroupMember.Read.All"):
        connector.probe_group_members_permission()


def test_probe_group_members_passes_on_200() -> None:
    """A listing that Graph answers means the app has the required permission."""
    connector = _make_connector()

    def list_entra_groups(**_kwargs: object) -> EntraPage[EntraGroup]:
        return EntraPage(items=[])

    stub_operation(connector.ops, "list_entra_groups", list_entra_groups)

    connector.probe_group_members_permission()  # should not raise


def test_probe_role_assignments_rejects_client_secret_auth() -> None:
    """A client secret can never reach the REST surface, so say that instead of
    sending the admin to grant more permissions."""
    connector = _make_connector()
    _stub_auth_method(connector, MicrosoftAuthMethod.CLIENT_SECRET)
    probed = _stub_rest_probe(connector)

    with pytest.raises(ConnectorValidationError) as exc_info:
        connector.probe_role_assignments_permission()

    message = str(exc_info.value)
    assert "certificate" in message.lower()
    assert "Sites.FullControl.All" not in message
    assert probed == []


def test_probe_role_assignments_rejects_client_secret_in_all_sites_mode() -> None:
    """With no configured sites there is nothing to probe, but the credential
    type is still wrong and permission sync would still fail later."""
    connector = SharepointConnector(sites=[])
    connector_with_gateway(connector)
    _stub_auth_method(connector, MicrosoftAuthMethod.CLIENT_SECRET)
    probed = _stub_rest_probe(connector)

    with pytest.raises(ConnectorValidationError):
        connector.probe_role_assignments_permission()

    assert probed == []
