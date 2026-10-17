"""The SharePoint checks' rows: the design's names, short lines and
descriptions, the run order, the partial finds of selected sites and
libraries, and what a check that tested nothing says."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
    CheckNotRunReason,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.microsoft_utils.models import MicrosoftTokenInfo
from onyx.connectors.sharepoint import connector_utils
from onyx.connectors.sharepoint.capability_checks import (
    build_sharepoint_doc_permission_sync_checks,
    build_sharepoint_group_sync_checks,
    build_sharepoint_indexing_checks,
)
from onyx.connectors.sharepoint.models import SitePagesPage
from tests.unit.onyx.connectors.sharepoint.test_sharepoint_perm_sync_checks import (
    ITEM_JSON,
    OTHER_SITE_URL,
    SITE_URL,
    _delta_page,
    _gateway,
    _refusal,
)

_ALL_CHECKS: dict[str, CapabilityCheck] = {
    check.check_id: check
    for check in build_sharepoint_indexing_checks()
    + build_sharepoint_doc_permission_sync_checks()
    + build_sharepoint_group_sync_checks()
}


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        connector_utils, "validate_outbound_http_url", lambda *_, **__: None
    )


def _healthy() -> MagicMock:
    gateway: MagicMock = _gateway()
    gateway.check_token.return_value = MicrosoftTokenInfo(app_name="Onyx")
    gateway.get_certificate_not_after.return_value = datetime(
        2027, 5, 1, tzinfo=timezone.utc
    )
    gateway.get_drive_item.return_value = DriveItemData.from_graph_json(ITEM_JSON)
    gateway.read_item_bytes.return_value = 10
    gateway.get_site_page.return_value = {"id": "page-id"}
    return gateway


def _config(**overrides: Any) -> dict[str, Any]:
    return {
        "sites": [SITE_URL],
        "include_site_documents": True,
        "include_site_pages": True,
        **overrides,
    }


def _run_all(
    check_ids: list[str], gateway: MagicMock, config: dict[str, Any] | None = None
) -> dict[str, CapabilityCheckResult]:
    checks: list[CapabilityCheck] = [_ALL_CHECKS[check_id] for check_id in check_ids]
    context = CapabilityCheckContext(
        source=DocumentSource.SHAREPOINT,
        credential_json={"sp_client_id": "x", "sp_directory_id": "y"},
        connector_specific_config=config if config is not None else _config(),
        source_operations=gateway,
    )
    return {
        result.check_id: result for result in run_capability_checks(checks, context)
    }


def _run(
    check_id: str, gateway: MagicMock, config: dict[str, Any] | None = None
) -> CapabilityCheckResult:
    return _run_all([check_id], gateway, config)[check_id]


def test_the_rows_have_the_design_names() -> None:
    assert {
        check_id: check.display_name for check_id, check in _ALL_CHECKS.items()
    } == {
        "sharepoint_token_auth": "Sign in to Microsoft",
        "sharepoint_content_types": "Check selected content",
        "sharepoint_sites_visible": "List sites",
        "sharepoint_configured_sites": "Find selected sites",
        "sharepoint_configured_libraries": "Find selected libraries",
        "sharepoint_documents_read": "Sample documents",
        "sharepoint_site_pages_read": "Sample site pages",
        "sharepoint_certificate_auth": "Sign in with certificate",
        "sharepoint_site_permissions_read": "Read site permissions",
        "sharepoint_site_group_members_read": "Read site group members",
        "sharepoint_document_permissions_read": "Read file permissions",
        "sharepoint_page_permissions_read": "Read page permissions",
        "sharepoint_entra_group_enumeration": "List groups",
        "sharepoint_entra_group_members_read": "Read group members",
        "sharepoint_entra_nested_groups_read": "Read nested groups",
    }


# --- Pass lines ---


@pytest.mark.parametrize(
    ("check_id", "summary"),
    [
        ("sharepoint_token_auth", "Signed in as Onyx"),
        ("sharepoint_content_types", "Indexing documents, site pages"),
        ("sharepoint_configured_sites", "1 selected site found"),
        ("sharepoint_documents_read", "Read a file in Shared Documents"),
        ("sharepoint_site_pages_read", "Read a page on eng"),
        ("sharepoint_certificate_auth", "Certificate valid until 2027/05/01"),
        ("sharepoint_site_permissions_read", "Read permissions of 1 site"),
        ("sharepoint_site_group_members_read", "Read members of Eng Members"),
        (
            "sharepoint_document_permissions_read",
            "Read permissions of a file in Shared Do…",
        ),
        ("sharepoint_page_permissions_read", "Read permissions of a page on eng"),
        ("sharepoint_entra_nested_groups_read", "Read groups inside Engineering"),
        ("sharepoint_entra_group_members_read", "Read members of Engineering"),
    ],
)
def test_a_passing_check_says_what_it_found(check_id: str, summary: str) -> None:
    result = _run(check_id, _healthy(), _config(exhaustive_ad_enumeration=True))

    assert result.status == CapabilityCheckStatus.PASSED, result.message
    assert result.summary == summary


def test_list_sites_counts_the_listed_sites() -> None:
    result = _run("sharepoint_sites_visible", _healthy(), _config(sites=[]))

    assert result.summary == "2 sites visible"


def test_the_group_listing_names_the_group() -> None:
    result = _run(
        "sharepoint_entra_group_enumeration",
        _healthy(),
        _config(exhaustive_ad_enumeration=True),
    )

    assert result.summary == "Listed groups, read Engineering"


# --- Find selected sites ---


def test_a_site_url_without_a_site_path_names_the_url() -> None:
    result = _run(
        "sharepoint_configured_sites",
        _healthy(),
        _config(sites=["https://contoso.sharepoint.com/eng"]),
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary is not None
    assert result.summary.startswith("Not a site URL: ")


def test_a_site_on_another_tenant_says_so() -> None:
    result = _run(
        "sharepoint_configured_sites",
        _healthy(),
        _config(sites=[SITE_URL, "https://victim.sharepoint.com/sites/x"]),
    )

    assert result.summary == "Site is on another host: x"


def test_every_site_excluded_fails_the_find() -> None:
    result = _run(
        "sharepoint_configured_sites", _healthy(), _config(excluded_sites=["*/eng"])
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Every selected site is excluded"


def test_some_missing_sites_are_a_partial_find() -> None:
    gateway = _healthy()
    gateway.get_site_id.side_effect = lambda site_url: (
        "site-id" if site_url == SITE_URL else _raise(_refusal(404, "itemNotFound"))
    )

    results = _run_all(
        [
            "sharepoint_token_auth",
            "sharepoint_configured_sites",
            "sharepoint_documents_read",
        ],
        gateway,
        _config(sites=[SITE_URL, OTHER_SITE_URL]),
    )

    sites = results["sharepoint_configured_sites"]
    assert sites.status == CapabilityCheckStatus.INCOMPLETE
    assert sites.partial
    assert sites.summary == "Site not found: ops"
    documents = results["sharepoint_documents_read"]
    assert documents.status == CapabilityCheckStatus.PASSED
    assert [call.kwargs["site_url"] for call in gateway.list_drives.call_args_list] == [
        SITE_URL
    ]


def _raise(error: Exception) -> str:
    raise error


def test_no_selected_site_found_fails() -> None:
    gateway = _healthy()
    gateway.get_site_id.side_effect = _refusal(404, "itemNotFound")

    result = _run(
        "sharepoint_configured_sites",
        gateway,
        _config(sites=[SITE_URL, OTHER_SITE_URL]),
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "No selected site found"


def test_more_than_five_sites_pass_with_a_caveat() -> None:
    sites = [f"{SITE_URL}{n}" for n in range(7)]

    result = _run("sharepoint_configured_sites", _healthy(), _config(sites=sites))

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "First 5 of 7 sites found"
    assert result.advisories


# --- Samples that test nothing ---


def test_no_file_in_scope_is_incomplete() -> None:
    gateway = _healthy()
    gateway.get_delta_page.return_value = _delta_page()

    result = _run("sharepoint_documents_read", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No files found to test"


def test_no_page_in_scope_is_skipped() -> None:
    gateway = _healthy()
    gateway.list_site_pages.return_value = SitePagesPage(pages=[])

    result = _run("sharepoint_site_pages_read", gateway)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.not_run_reason == CheckNotRunReason.NOTHING_IN_SCOPE
    assert result.summary == "No site pages in scope"


def test_a_file_that_went_away_passes_with_a_caveat() -> None:
    gateway = _healthy()
    gateway.get_list_item_id.side_effect = _refusal(404, "itemNotFound")

    result = _run("sharepoint_document_permissions_read", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "Sample file disappeared"
    assert result.advisories


# --- Denials name the grant ---


def test_a_refused_file_listing_names_the_library_and_grant() -> None:
    gateway = _healthy()
    gateway.get_delta_page.side_effect = _refusal(403)

    result = _run("sharepoint_documents_read", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "No read access to Shared Documents"
    assert result.description is not None
    assert "`Sites.Read.All` (Microsoft Graph, application)" in result.description


def test_a_refused_site_permission_read_names_the_rest_grant() -> None:
    gateway = _healthy()
    gateway.list_role_assignments.side_effect = _refusal(403)

    result = _run("sharepoint_site_permissions_read", gateway)

    assert result.summary == "No access to permissions of eng"
    assert result.description is not None
    assert "`Sites.FullControl.All` (SharePoint API, application)" in (
        result.description
    )


def test_a_rest_401_is_no_token_for_the_host() -> None:
    gateway = _healthy()
    gateway.list_role_assignments.side_effect = _refusal(401, "Unauthorized")

    result = _run("sharepoint_site_permissions_read", gateway)

    assert result.error_kind == CheckErrorKind.REJECTED
    assert result.summary == "No token for the SharePoint host"


def test_a_client_secret_stops_the_permission_checks() -> None:
    gateway = _healthy()
    gateway.get_auth_method.return_value = MicrosoftAuthMethod.CLIENT_SECRET

    results = _run_all(
        [
            "sharepoint_certificate_auth",
            "sharepoint_site_permissions_read",
            "sharepoint_document_permissions_read",
        ],
        gateway,
    )

    assert results["sharepoint_certificate_auth"].summary == (
        "Account uses a client secret"
    )
    for check_id in (
        "sharepoint_site_permissions_read",
        "sharepoint_document_permissions_read",
    ):
        assert results[check_id].status == CapabilityCheckStatus.SKIPPED
        assert results[check_id].blocked_by == "sharepoint_certificate_auth"
    gateway.list_role_assignments.assert_not_called()


def test_a_throttled_listing_stops_the_run() -> None:
    gateway = _healthy()
    gateway.list_site_urls.side_effect = _refusal(429, "tooManyRequests")

    results = _run_all(
        [
            "sharepoint_token_auth",
            "sharepoint_sites_visible",
            "sharepoint_entra_group_enumeration",
        ],
        gateway,
        _config(sites=[], exhaustive_ad_enumeration=True),
    )

    assert results["sharepoint_sites_visible"].error_kind == CheckErrorKind.RATE_LIMITED
    assert results["sharepoint_sites_visible"].summary == (
        "Microsoft is throttling requests"
    )
    assert (
        results["sharepoint_entra_group_enumeration"].not_run_reason
        == CheckNotRunReason.RATE_LIMITED
    )
