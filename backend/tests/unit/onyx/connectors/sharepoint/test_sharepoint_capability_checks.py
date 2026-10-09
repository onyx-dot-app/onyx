"""Behavior tests for the SharePoint indexing checks.

Each check runs against an autospecced ``SharepointSourceOperations`` whose
operations return the gateway's plain models. Probe reach (which operations a
check exercises) is enforced by the auto-discovering coverage harness.
"""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckStatus,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.microsoft_utils.drive_delta import (
    DriveDeltaFetchResult,
    DriveDeltaPage,
)
from onyx.connectors.microsoft_utils.drive_items import (
    DriveFolderReference,
    DriveItemData,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MISSING_CREDENTIAL_CODE,
    MicrosoftAuthError,
    MicrosoftGraphError,
)
from onyx.connectors.sharepoint import connector_utils
from onyx.connectors.sharepoint.capability_checks import (
    build_sharepoint_indexing_checks,
)
from onyx.connectors.sharepoint.models import (
    SharepointDrive,
    SharepointTokenInfo,
    SitePagesPage,
)
from onyx.connectors.sharepoint.source_operations import SharepointSourceOperations
from onyx.utils.url import SSRFException

SITE_URL = "https://contoso.sharepoint.com/sites/eng"
OTHER_SITE_URL = "https://contoso.sharepoint.com/sites/ops"
DRIVE = SharepointDrive(
    id="drive-id", name="Documents", web_url=f"{SITE_URL}/Shared%20Documents"
)
ITEM_JSON: dict[str, Any] = {
    "id": "item-id",
    "name": "plan.pdf",
    "webUrl": f"{SITE_URL}/Shared%20Documents/plan.pdf",
    "size": 10,
    "file": {"mimeType": "application/pdf"},
    "parentReference": {"driveId": "drive-id"},
}
ITEM = DriveItemData.from_graph_json(ITEM_JSON)


def _delta_page(*items: dict[str, Any]) -> DriveDeltaFetchResult:
    return DriveDeltaFetchResult(
        page=DriveDeltaPage.model_validate({"value": list(items)})
    )


_CHECKS_BY_ID = {check.check_id: check for check in build_sharepoint_indexing_checks()}


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SSRF guard resolves the host, which the fake tenant has no DNS for."""
    monkeypatch.setattr(
        connector_utils, "validate_outbound_http_url", lambda *_, **__: None
    )


def _refusal(status: int, code: str = "accessDenied") -> MicrosoftGraphError:
    return MicrosoftGraphError(status, code, "refused")


def _gateway() -> MagicMock:
    """A healthy tenant: one site with one library holding one small file and
    one page."""
    gateway = create_autospec(SharepointSourceOperations, instance=True)
    gateway.check_token.return_value = SharepointTokenInfo(expires_in=3599)
    gateway.list_site_urls.return_value = [SITE_URL, OTHER_SITE_URL]
    gateway.get_site_id.return_value = "site-id"
    gateway.list_drives.return_value = [DRIVE]
    gateway.get_delta_page.return_value = _delta_page(ITEM_JSON)
    gateway.get_drive_item.return_value = ITEM
    gateway.read_item_bytes.return_value = 10
    gateway.resolve_folder.return_value = DriveFolderReference(
        id="folder-id", web_url=f"{DRIVE.web_url}/Plans"
    )
    gateway.list_site_pages.return_value = SitePagesPage(pages=[{"id": "page-id"}])
    gateway.get_site_page.return_value = {"id": "page-id"}
    return gateway


def _config(**overrides: Any) -> dict[str, Any]:
    return {
        "sites": [SITE_URL],
        "include_site_documents": True,
        "include_site_pages": True,
        **overrides,
    }


def _context(
    gateway: MagicMock, config: dict[str, Any] | None = None
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.SHAREPOINT,
        credential_json={"sp_client_id": "x", "sp_directory_id": "y"},
        connector_specific_config=config,
        source_operations=gateway,
    )


def _run(check_id: str, context: CapabilityCheckContext) -> None:
    _CHECKS_BY_ID[check_id].run(context)


def _status(check_id: str, context: CapabilityCheckContext) -> CapabilityCheckStatus:
    (result,) = run_capability_checks([_CHECKS_BY_ID[check_id]], context)
    return result.status


def test_every_check_passes_on_a_healthy_tenant() -> None:
    results = run_capability_checks(
        build_sharepoint_indexing_checks(),
        _context(_gateway(), _config(sites=[f"{SITE_URL}/Shared Documents/Plans"])),
    )

    assert {result.check_id: result.status for result in results} == {
        "sharepoint_token_auth": CapabilityCheckStatus.PASSED,
        "sharepoint_content_types": CapabilityCheckStatus.PASSED,
        "sharepoint_configured_sites": CapabilityCheckStatus.PASSED,
        "sharepoint_sites_visible": CapabilityCheckStatus.SKIPPED,
        "sharepoint_configured_folder": CapabilityCheckStatus.PASSED,
        "sharepoint_documents_read": CapabilityCheckStatus.PASSED,
        "sharepoint_site_pages_read": CapabilityCheckStatus.PASSED,
    }


def test_every_check_waits_for_a_config() -> None:
    """The token check too: the authority it signs in against is a setting."""
    gateway = _gateway()
    results = run_capability_checks(
        build_sharepoint_indexing_checks(), _context(gateway, None)
    )

    assert {result.status for result in results} == {CapabilityCheckStatus.SKIPPED}
    gateway.check_token.assert_not_called()


# sharepoint_token_auth


def test_token_check_reports_a_blank_credential_field() -> None:
    gateway = _gateway()
    gateway.check_token.side_effect = MicrosoftAuthError(MISSING_CREDENTIAL_CODE, "")

    with pytest.raises(CredentialInvalidError, match="incomplete"):
        _run("sharepoint_token_auth", _context(gateway))


def test_token_check_reports_a_rejected_secret() -> None:
    gateway = _gateway()
    gateway.check_token.side_effect = MicrosoftAuthError("invalid_client", "")

    with pytest.raises(CredentialInvalidError, match="client secret"):
        _run("sharepoint_token_auth", _context(gateway))


# sharepoint_content_types


def test_both_content_types_off_fails() -> None:
    config = _config(include_site_documents=False, include_site_pages=False)

    with pytest.raises(ConnectorValidationError, match="content type"):
        _run("sharepoint_content_types", _context(_gateway(), config))


# sharepoint_configured_sites


@pytest.mark.parametrize(
    "site_url",
    [
        "http://contoso.sharepoint.com/sites/eng",
        "https://contoso.sharepoint.com/eng",
        "https://victim.sharepoint.com/sites/eng",
        "https://contoso.sharepoint.com.attacker.example/sites/eng",
    ],
)
def test_malformed_or_foreign_site_urls_fail_before_any_read(site_url: str) -> None:
    gateway = _gateway()
    config = _config(sites=[SITE_URL, site_url])

    with pytest.raises(ConnectorValidationError):
        _run("sharepoint_configured_sites", _context(gateway, config))

    gateway.get_site_id.assert_not_called()


def test_a_site_the_ssrf_guard_rejects_fails_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway()

    def reject(*_: Any, **__: Any) -> None:
        raise SSRFException("private address")

    monkeypatch.setattr(connector_utils, "validate_outbound_http_url", reject)

    with pytest.raises(ConnectorValidationError, match="private address"):
        _run("sharepoint_configured_sites", _context(gateway, _config()))

    gateway.get_site_id.assert_not_called()


def test_a_url_that_names_no_site_fails_before_any_read() -> None:
    gateway = _gateway()
    config = _config(sites=[SITE_URL, "https://contoso.sharepoint.com/sites/"])

    with pytest.raises(ConnectorValidationError, match="name no site"):
        _run("sharepoint_configured_sites", _context(gateway, config))

    gateway.get_site_id.assert_not_called()


def test_a_host_graph_rejects_for_the_tenant_fails() -> None:
    gateway = _gateway()
    gateway.get_site_id.side_effect = _refusal(400, "invalidRequest")

    with pytest.raises(ConnectorValidationError, match="invalidRequest"):
        _run("sharepoint_configured_sites", _context(gateway, _config()))


def test_an_ambiguous_library_fails() -> None:
    gateway = _gateway()
    gateway.list_drives.return_value = [
        SharepointDrive(id="a", name="Plans", web_url=f"{SITE_URL}/Archive"),
        SharepointDrive(id="b", name="Archive", web_url=f"{SITE_URL}/archive"),
    ]
    config = _config(sites=[f"{SITE_URL}/Archive"])

    with pytest.raises(ConnectorValidationError, match="ambiguous"):
        _run("sharepoint_documents_read", _context(gateway, config))


def test_a_site_graph_does_not_know_fails_with_its_url() -> None:
    gateway = _gateway()
    gateway.get_site_id.side_effect = _refusal(404, "itemNotFound")

    with pytest.raises(ConnectorValidationError, match=SITE_URL):
        _run("sharepoint_configured_sites", _context(gateway, _config()))


def test_a_refused_site_names_the_grant() -> None:
    gateway = _gateway()
    gateway.get_site_id.side_effect = _refusal(403)

    with pytest.raises(InsufficientPermissionsError, match="Sites.Selected"):
        _run("sharepoint_configured_sites", _context(gateway, _config()))


def test_configured_sites_check_is_skipped_without_sites() -> None:
    status = _status(
        "sharepoint_configured_sites", _context(_gateway(), _config(sites=[]))
    )

    assert status is CapabilityCheckStatus.SKIPPED


def test_a_blank_site_entry_fails_like_indexing() -> None:
    gateway = _gateway()

    with pytest.raises(ConnectorValidationError, match="not a full"):
        _run(
            "sharepoint_configured_sites",
            _context(gateway, _config(sites=["", SITE_URL])),
        )

    gateway.get_site_id.assert_not_called()


def test_excluded_sites_are_validated_but_never_read() -> None:
    gateway = _gateway()
    config = _config(sites=[SITE_URL, OTHER_SITE_URL], excluded_sites=["*/sites/ops"])

    _run("sharepoint_configured_sites", _context(gateway, config))

    assert [call.kwargs["site_url"] for call in gateway.get_site_id.call_args_list] == [
        SITE_URL
    ]


def test_configured_sites_the_exclusions_remove_are_not_replaced() -> None:
    """Indexing reads nothing then, so the probe must not read other sites."""
    gateway = _gateway()
    config = _config(sites=[SITE_URL], excluded_sites=["*/sites/eng"])

    with pytest.raises(UnexpectedValidationError, match="No library"):
        _run("sharepoint_documents_read", _context(gateway, config))

    gateway.list_site_urls.assert_not_called()
    gateway.list_drives.assert_not_called()


def test_discovered_probe_sites_leave_out_personal_sites() -> None:
    gateway = _gateway()
    gateway.list_site_urls.return_value = [
        "https://contoso-my.sharepoint.com/personal/alice",
        OTHER_SITE_URL,
    ]

    _run("sharepoint_documents_read", _context(gateway, _config(sites=[])))

    assert gateway.list_drives.call_args.kwargs["site_url"] == OTHER_SITE_URL


def test_discovered_probe_sites_honor_the_exclusions() -> None:
    gateway = _gateway()
    config = _config(sites=[], excluded_sites=["*/sites/eng"])

    _run("sharepoint_documents_read", _context(gateway, config))

    assert gateway.list_drives.call_args.kwargs["site_url"] == OTHER_SITE_URL


def test_only_the_first_sites_are_probed() -> None:
    gateway = _gateway()
    sites = [f"{SITE_URL}{n}" for n in range(8)]

    _run("sharepoint_configured_sites", _context(gateway, _config(sites=sites)))

    assert gateway.get_site_id.call_count == 5


# sharepoint_sites_visible


def test_an_empty_site_listing_fails() -> None:
    gateway = _gateway()
    gateway.list_site_urls.return_value = []

    with pytest.raises(ConnectorValidationError, match="Sites.Selected"):
        _run("sharepoint_sites_visible", _context(gateway, _config(sites=[])))


def test_sites_visible_reads_one_listing_page() -> None:
    gateway = _gateway()

    _run("sharepoint_sites_visible", _context(gateway, _config(sites=[])))

    gateway.list_site_urls.assert_called_once_with(max_pages=1)


def test_sites_visible_is_skipped_with_configured_sites() -> None:
    assert (
        _status("sharepoint_sites_visible", _context(_gateway(), _config()))
        is CapabilityCheckStatus.SKIPPED
    )


# sharepoint_configured_folder


def test_folder_check_resolves_the_configured_folder() -> None:
    gateway = _gateway()
    config = _config(sites=[f"{SITE_URL}/Shared Documents/Plans/Q1"])

    _run("sharepoint_configured_folder", _context(gateway, config))

    gateway.resolve_folder.assert_called_once_with(
        drive_id="drive-id", folder_path="Plans/Q1"
    )


def test_missing_folder_fails_with_its_path() -> None:
    gateway = _gateway()
    gateway.resolve_folder.side_effect = _refusal(404, "itemNotFound")
    config = _config(sites=[f"{SITE_URL}/Shared Documents/Plans"])

    with pytest.raises(ConnectorValidationError, match="Plans"):
        _run("sharepoint_configured_folder", _context(gateway, config))


def test_unknown_library_fails_with_its_segment() -> None:
    gateway = _gateway()
    config = _config(sites=[f"{SITE_URL}/Archive/Plans"])

    with pytest.raises(ConnectorValidationError, match="Archive"):
        _run("sharepoint_configured_folder", _context(gateway, config))


def test_folder_check_is_skipped_when_documents_are_off() -> None:
    config = _config(
        sites=[f"{SITE_URL}/Shared Documents/Plans"], include_site_documents=False
    )

    assert (
        _status("sharepoint_configured_folder", _context(_gateway(), config))
        is CapabilityCheckStatus.SKIPPED
    )


def test_folder_check_is_skipped_without_a_folder_path() -> None:
    config = _config(sites=[f"{SITE_URL}/Shared Documents"])

    assert (
        _status("sharepoint_configured_folder", _context(_gateway(), config))
        is CapabilityCheckStatus.SKIPPED
    )


# sharepoint_documents_read


def test_documents_check_reads_one_file_by_id_and_content() -> None:
    gateway = _gateway()

    _run("sharepoint_documents_read", _context(gateway, _config()))

    gateway.get_drive_item.assert_called_once_with(
        drive_id="drive-id", item_id="item-id"
    )
    gateway.read_item_bytes.assert_called_once_with(
        drive_id="drive-id", item=ITEM, max_bytes=5 * 1024 * 1024
    )
    gateway.download_item.assert_not_called()


def test_documents_check_skips_rows_indexing_would_not_read() -> None:
    gateway = _gateway()
    gateway.get_delta_page.return_value = _delta_page(
        {"id": "deleted", "name": "x.pdf", "deleted": {}, "file": {}},
        {"id": "folder", "name": "f", "folder": {}},
        {"id": "notebook", "name": "Notes", "size": 1, "package": {"type": "oneNote"}},
        {"id": "unsupported", "name": "tool.exe", "size": 1, "file": {}},
        {**ITEM_JSON, "id": "from-delta"},
    )

    _run("sharepoint_documents_read", _context(gateway, _config()))

    assert gateway.get_drive_item.call_args.kwargs["item_id"] == "from-delta"
    gateway.iter_folder_items.assert_not_called()


def test_documents_check_reads_one_bounded_delta_page() -> None:
    gateway = _gateway()

    _run("sharepoint_documents_read", _context(gateway, _config()))

    assert "$top=25" in gateway.get_delta_page.call_args.kwargs["page_url"]
    gateway.iter_folder_items.assert_not_called()


def test_documents_check_reads_only_inside_the_configured_folder() -> None:
    gateway = _gateway()
    gateway.get_delta_page.return_value = _delta_page(
        {**ITEM_JSON, "id": "outside"},
        {
            **ITEM_JSON,
            "id": "inside",
            "parentReference": {
                "driveId": "drive-id",
                "path": "/drives/d/root:/Plans/Q1",
            },
        },
    )
    config = _config(sites=[f"{SITE_URL}/Shared Documents/Plans"])

    _run("sharepoint_documents_read", _context(gateway, config))

    assert gateway.get_drive_item.call_args.kwargs["item_id"] == "inside"


def test_documents_check_matches_the_configured_folder_literally() -> None:
    """A folder named `draft%20copy` is configured as `draft%2520copy`, which
    decodes once, the way indexing resolves it."""
    gateway = _gateway()
    gateway.get_delta_page.return_value = _delta_page(
        {
            **ITEM_JSON,
            "id": "decoded-twice",
            "parentReference": {
                "driveId": "drive-id",
                "path": "/drives/d/root:/draft copy",
            },
        },
        {
            **ITEM_JSON,
            "id": "literal",
            "parentReference": {
                "driveId": "drive-id",
                "path": "/drives/d/root:/draft%2520copy",
            },
        },
    )
    config = _config(sites=[f"{SITE_URL}/Shared Documents/draft%2520copy"])

    _run("sharepoint_documents_read", _context(gateway, config))

    assert gateway.get_drive_item.call_args.kwargs["item_id"] == "literal"


def test_documents_check_skips_excluded_paths() -> None:
    gateway = _gateway()
    gateway.get_delta_page.return_value = _delta_page(
        {
            **ITEM_JSON,
            "id": "archived",
            "parentReference": {
                "driveId": "drive-id",
                "path": "/drives/d/root:/Archive",
            },
        },
        {**ITEM_JSON, "id": "kept"},
    )
    config = _config(excluded_paths=["Archive/*"])

    _run("sharepoint_documents_read", _context(gateway, config))

    assert gateway.get_drive_item.call_args.kwargs["item_id"] == "kept"


def test_documents_check_matches_exclusions_on_the_literal_name() -> None:
    gateway = _gateway()
    gateway.get_delta_page.return_value = _delta_page(
        {**ITEM_JSON, "id": "literal", "name": "draft%20copy.pdf"},
        {**ITEM_JSON, "id": "kept"},
    )
    config = _config(excluded_paths=["draft%20copy.pdf"])

    _run("sharepoint_documents_read", _context(gateway, config))

    assert gateway.get_drive_item.call_args.kwargs["item_id"] == "kept"


def test_documents_check_stops_after_the_first_libraries() -> None:
    gateway = _gateway()
    gateway.list_drives.return_value = [DRIVE] * 11
    gateway.get_delta_page.return_value = _delta_page()

    with pytest.raises(UnexpectedValidationError, match="first 10 libraries"):
        _run("sharepoint_documents_read", _context(gateway, _config()))

    assert gateway.get_delta_page.call_count == 10
    gateway.get_drive_item.assert_not_called()


def test_refused_download_names_the_grant() -> None:
    gateway = _gateway()
    gateway.read_item_bytes.side_effect = _refusal(403)

    with pytest.raises(InsufficientPermissionsError, match="plan.pdf"):
        _run("sharepoint_documents_read", _context(gateway, _config()))


def test_documents_check_skips_the_download_of_a_large_file() -> None:
    gateway = _gateway()
    gateway.get_delta_page.return_value = _delta_page(
        {**ITEM_JSON, "size": 50 * 1024 * 1024}
    )

    _run("sharepoint_documents_read", _context(gateway, _config()))

    gateway.read_item_bytes.assert_not_called()


def test_documents_check_passes_on_an_empty_library() -> None:
    gateway = _gateway()
    gateway.get_delta_page.return_value = _delta_page()

    _run("sharepoint_documents_read", _context(gateway, _config()))

    gateway.get_drive_item.assert_not_called()


def test_documents_check_uses_the_configured_library() -> None:
    gateway = _gateway()
    gateway.list_drives.return_value = [
        DRIVE,
        SharepointDrive(id="other", name="Archive", web_url=f"{SITE_URL}/Archive"),
    ]
    config = _config(sites=[f"{SITE_URL}/Archive"])

    _run("sharepoint_documents_read", _context(gateway, config))

    assert gateway.get_delta_page.call_args.kwargs["drive_id"] == "other"


def test_documents_check_probes_the_listed_sites_without_configured_ones() -> None:
    gateway = _gateway()

    _run("sharepoint_documents_read", _context(gateway, _config(sites=[])))

    gateway.list_site_urls.assert_called_once_with(max_pages=1)
    assert gateway.list_drives.call_args.kwargs["site_url"] == SITE_URL


def test_refused_file_listing_names_the_grant() -> None:
    gateway = _gateway()
    gateway.get_delta_page.side_effect = _refusal(403)

    with pytest.raises(InsufficientPermissionsError, match="Sites.Read.All"):
        _run("sharepoint_documents_read", _context(gateway, _config()))


def test_throttled_listing_is_indeterminate() -> None:
    gateway = _gateway()
    gateway.list_drives.side_effect = _refusal(429, "tooManyRequests")

    with pytest.raises(UnexpectedValidationError):
        _run("sharepoint_documents_read", _context(gateway, _config()))


def test_documents_check_is_skipped_when_documents_are_off() -> None:
    config = _config(include_site_documents=False)

    assert (
        _status("sharepoint_documents_read", _context(_gateway(), config))
        is CapabilityCheckStatus.SKIPPED
    )


def test_no_library_anywhere_is_indeterminate() -> None:
    gateway = _gateway()
    gateway.list_drives.return_value = []

    with pytest.raises(UnexpectedValidationError, match="No library"):
        _run("sharepoint_documents_read", _context(gateway, _config()))


# sharepoint_site_pages_read


def test_pages_check_expands_one_page() -> None:
    gateway = _gateway()

    _run("sharepoint_site_pages_read", _context(gateway, _config()))

    gateway.get_site_page.assert_called_once_with(
        site_id="site-id", page_id="page-id", expand_canvas=True
    )


def test_pages_check_falls_back_when_the_expanded_listing_is_refused() -> None:
    """One corrupt canvas poisons the expanded listing, and indexing lists
    without it and keeps a corrupt page's metadata."""
    gateway = _gateway()
    invalid = _refusal(400, "invalidRequest")

    def list_pages(
        *,
        site_id: str,  # noqa: ARG001
        next_link: str | None = None,  # noqa: ARG001
        expand_canvas: bool,
    ) -> SitePagesPage:
        if expand_canvas:
            raise invalid
        return SitePagesPage(pages=[{"id": "page-id"}])

    gateway.list_site_pages.side_effect = list_pages
    gateway.get_site_page.side_effect = invalid

    _run("sharepoint_site_pages_read", _context(gateway, _config()))

    assert gateway.list_site_pages.call_count == 2
    gateway.get_site_page.assert_called_once()


def test_pages_check_moves_past_a_site_without_a_pages_listing() -> None:
    """A classic site answers 404 on the pages API and indexing skips it."""
    gateway = _gateway()
    gateway.list_site_pages.side_effect = [
        _refusal(404, "itemNotFound"),
        SitePagesPage(pages=[{"id": "page-id"}]),
    ]

    _run("sharepoint_site_pages_read", _context(gateway, _config(sites=[])))

    assert gateway.get_site_id.call_count == 2
    gateway.get_site_page.assert_called_once()


def test_pages_check_passes_on_a_site_without_pages() -> None:
    gateway = _gateway()
    gateway.list_site_pages.return_value = SitePagesPage(pages=[])

    _run("sharepoint_site_pages_read", _context(gateway, _config()))

    gateway.get_site_page.assert_not_called()


def test_refused_pages_fail_the_check() -> None:
    gateway = _gateway()
    gateway.list_site_pages.side_effect = _refusal(403)
    (result,) = run_capability_checks(
        [_CHECKS_BY_ID["sharepoint_site_pages_read"]], _context(gateway, _config())
    )

    assert result.status is CapabilityCheckStatus.FAILED
    assert result.required


def test_pages_check_is_skipped_when_pages_are_off() -> None:
    config = _config(include_site_pages=False)

    assert (
        _status("sharepoint_site_pages_read", _context(_gateway(), config))
        is CapabilityCheckStatus.SKIPPED
    )
