"""The SharePoint permission-sync checks read what the sync reads, on the
sites the sync reads, and name the grant a refusal needs."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from ee.onyx.connectors.capability_checks import get_perm_sync_capability_checks
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckStatus,
    CredentialCapability,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.microsoft_utils.drive_delta import (
    DriveDeltaFetchResult,
    DriveDeltaPage,
)
from onyx.connectors.microsoft_utils.entra import EntraGroup, EntraPage
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.microsoft_utils.models import (
    SharepointPrincipal,
    SharepointRoleAssignment,
    SharepointSecurableKind,
)
from onyx.connectors.microsoft_utils.sharepoint_principals import (
    SharepointPrincipalType,
)
from onyx.connectors.sharepoint.capability_checks import (
    build_sharepoint_doc_permission_sync_checks,
)
from onyx.connectors.sharepoint.models import SharepointDrive, SitePagesPage
from onyx.connectors.sharepoint.source_operations import SharepointSourceOperations

SITE_URL = "https://contoso.sharepoint.com/sites/eng"
OTHER_SITE_URL = "https://contoso.sharepoint.com/sites/ops"
GROUP_ID = "11111111-1111-1111-1111-111111111111"
CLAIMS_LOGIN = f"c:0t.c|tenant|{GROUP_ID}"
PUBLIC_LOGIN = "c:0-.f|rolemanager|spo-grid-all-users/tenant-id"
DRIVE = SharepointDrive(
    id="drive-id",
    name="Documents",
    web_url=f"{SITE_URL}/Shared%20Documents",
    list_id="list-id",
)
ITEM_JSON: dict[str, Any] = {
    "id": "item-id",
    "name": "plan.pdf",
    "webUrl": f"{SITE_URL}/Shared%20Documents/Plans/plan.pdf",
    "size": 10,
    "file": {"mimeType": "application/pdf"},
    "parentReference": {"driveId": "drive-id", "path": "/drives/d/root:/Plans"},
}
# The Graph expansion the nested-groups check makes on the group it found.
_EXPANSIONS: list[tuple[str, Callable[[MagicMock], MagicMock]]] = [
    ("sharepoint_entra_nested_groups_read", lambda g: g.list_nested_entra_groups),
]
_CHECKS_BY_ID = {
    check.check_id: check for check in build_sharepoint_doc_permission_sync_checks()
}


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.connectors.sharepoint.connector_utils.validate_outbound_http_url",
        lambda url: url,
    )


def _assignment(
    principal_type: SharepointPrincipalType,
    login_name: str,
    title: str | None = None,
    role_type_kinds: list[int] | None = None,
) -> SharepointRoleAssignment:
    return SharepointRoleAssignment(
        member=SharepointPrincipal(
            principal_type=principal_type,
            login_name=login_name,
            title=title or login_name,
        ),
        role_type_kinds=[3] if role_type_kinds is None else role_type_kinds,
    )


SITE_GROUP = _assignment(SharepointPrincipalType.SHAREPOINT_GROUP, "Eng Members")
ENTRA_GROUP = _assignment(
    SharepointPrincipalType.ENTRA_GROUP, CLAIMS_LOGIN, "Engineering"
)


def _refusal(status: int, code: str = "accessDenied") -> MicrosoftGraphError:
    return MicrosoftGraphError(status, code, "refused")


def _delta_page(*items: dict[str, Any]) -> DriveDeltaFetchResult:
    return DriveDeltaFetchResult(
        page=DriveDeltaPage.model_validate({"value": list(items)})
    )


def _gateway() -> MagicMock:
    """A certificate app on a tenant with one site naming a site group and an
    Entra group, holding one library with one file in a folder and one page."""
    gateway = create_autospec(SharepointSourceOperations, instance=True)
    gateway.get_auth_method.return_value = MicrosoftAuthMethod.CERTIFICATE
    gateway.list_site_urls.return_value = [SITE_URL, OTHER_SITE_URL]
    gateway.get_site_id.return_value = "site-id"
    gateway.list_drives.return_value = [DRIVE]
    gateway.get_delta_page.return_value = _delta_page(ITEM_JSON)
    gateway.list_site_pages.return_value = SitePagesPage(
        pages=[{"id": "page-id", "webUrl": f"{SITE_URL}/SitePages/Home.aspx"}]
    )
    gateway.list_role_assignments.return_value = [SITE_GROUP, ENTRA_GROUP]
    gateway.list_site_group_users.return_value = []
    gateway.find_entra_group_id.return_value = GROUP_ID
    gateway.list_nested_entra_groups.return_value = []
    gateway.list_entra_group_members.return_value = []
    gateway.get_folder_unique_id.return_value = "folder-id"
    gateway.get_list_item_id.return_value = 7
    gateway.list_sharing_link_scopes.return_value = []
    gateway.list_entra_groups.return_value = EntraPage(
        items=[EntraGroup(id=GROUP_ID, displayName="Engineering")]
    )
    gateway.list_entra_group_member_page.return_value = EntraPage(items=[])
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
    """``config`` None is the credential-time run, before any settings."""
    return CapabilityCheckContext(
        source=DocumentSource.SHAREPOINT,
        credential_json={"sp_client_id": "x", "sp_directory_id": "y"},
        connector_specific_config=config,
        source_operations=gateway,
    )


def _run(check_id: str, context: CapabilityCheckContext) -> None:
    _CHECKS_BY_ID[check_id].run(context)


def _securable_kinds(gateway: MagicMock) -> list[SharepointSecurableKind]:
    return [
        call.kwargs["securable"].kind
        for call in gateway.list_role_assignments.call_args_list
    ]


def test_every_check_passes_on_a_healthy_tenant() -> None:
    results = run_capability_checks(
        get_perm_sync_capability_checks(DocumentSource.SHAREPOINT),
        _context(_gateway(), _config()),
    )

    # Group sync keeps the legacy probe, which needs a connector instance.
    expected: dict[tuple[str, CredentialCapability], CapabilityCheckStatus] = {
        ("sharepoint_group_members_probe", CredentialCapability.EXTERNAL_GROUP_SYNC): (
            CapabilityCheckStatus.SKIPPED
        )
    }
    expected.update(
        {
            (check_id, CredentialCapability.DOC_PERMISSION_SYNC): (
                CapabilityCheckStatus.PASSED
            )
            for check_id in (
                "sharepoint_certificate_auth",
                "sharepoint_site_permissions_read",
                "sharepoint_site_group_members_read",
                "sharepoint_entra_nested_groups_read",
                "sharepoint_document_permissions_read",
                "sharepoint_page_permissions_read",
            )
        }
    )
    assert {
        (result.check_id, result.capability): result.status for result in results
    } == expected


def test_every_check_waits_for_a_config() -> None:
    results = run_capability_checks(
        get_perm_sync_capability_checks(DocumentSource.SHAREPOINT),
        _context(_gateway(), None),
    )

    assert {result.status for result in results} == {CapabilityCheckStatus.SKIPPED}


# sharepoint_certificate_auth


def test_a_client_secret_credential_fails_before_any_read() -> None:
    gateway = _gateway()
    gateway.get_auth_method.return_value = MicrosoftAuthMethod.CLIENT_SECRET

    with pytest.raises(ConnectorValidationError, match="certificate"):
        _run("sharepoint_certificate_auth", _context(gateway, _config()))

    gateway.list_role_assignments.assert_not_called()


# sharepoint_site_permissions_read


def test_site_permissions_are_read_on_every_probe_site() -> None:
    gateway = _gateway()
    config = _config(sites=[SITE_URL, OTHER_SITE_URL])

    _run("sharepoint_site_permissions_read", _context(gateway, config))

    assert [
        call.kwargs["site_url"] for call in gateway.list_role_assignments.call_args_list
    ] == [SITE_URL, OTHER_SITE_URL]
    assert _securable_kinds(gateway) == [SharepointSecurableKind.SITE] * 2


def test_refused_site_permissions_name_the_rest_grant() -> None:
    gateway = _gateway()
    gateway.list_role_assignments.side_effect = _refusal(403)

    with pytest.raises(InsufficientPermissionsError, match="Sites.FullControl.All"):
        _run("sharepoint_site_permissions_read", _context(gateway, _config()))


def test_a_site_sharepoint_does_not_know_fails_with_its_url() -> None:
    gateway = _gateway()
    gateway.list_role_assignments.side_effect = _refusal(404, "itemNotFound")

    with pytest.raises(ConnectorValidationError, match=SITE_URL):
        _run("sharepoint_site_permissions_read", _context(gateway, _config()))


def test_configured_sites_the_exclusions_remove_leave_nothing_to_probe() -> None:
    gateway = _gateway()
    config = _config(excluded_sites=["*/sites/eng"])

    with pytest.raises(UnexpectedValidationError, match="No site"):
        _run("sharepoint_site_permissions_read", _context(gateway, config))

    gateway.list_site_urls.assert_not_called()


def test_discovered_probe_sites_leave_out_personal_sites() -> None:
    gateway = _gateway()
    gateway.list_site_urls.return_value = [
        "https://contoso-my.sharepoint.com/personal/alice",
        OTHER_SITE_URL,
    ]

    _run("sharepoint_site_permissions_read", _context(gateway, _config(sites=[])))

    assert gateway.list_role_assignments.call_args.kwargs["site_url"] == OTHER_SITE_URL


# sharepoint_site_group_members_read


def test_site_group_members_are_read_for_the_first_granting_group() -> None:
    gateway = _gateway()
    gateway.list_role_assignments.return_value = [
        _assignment(
            SharepointPrincipalType.SHAREPOINT_GROUP, "Limited", role_type_kinds=[1]
        ),
        SITE_GROUP,
        _assignment(SharepointPrincipalType.SHAREPOINT_GROUP, "Eng Owners"),
    ]

    _run("sharepoint_site_group_members_read", _context(gateway, _config()))

    gateway.list_site_group_users.assert_called_once_with(
        site_url=SITE_URL, group_name="Eng Members", max_rows=50
    )


def test_site_group_members_pass_when_no_site_names_a_group() -> None:
    gateway = _gateway()
    gateway.list_role_assignments.return_value = [ENTRA_GROUP]

    _run("sharepoint_site_group_members_read", _context(gateway, _config()))

    gateway.list_site_group_users.assert_not_called()


def test_refused_site_group_members_name_the_rest_grant() -> None:
    gateway = _gateway()
    gateway.list_site_group_users.side_effect = _refusal(403)

    with pytest.raises(InsufficientPermissionsError, match="Eng Members"):
        _run("sharepoint_site_group_members_read", _context(gateway, _config()))


# sharepoint_entra_nested_groups_read


@pytest.mark.parametrize(("check_id", "expansion"), _EXPANSIONS)
def test_entra_group_is_resolved_from_its_claims_login(
    check_id: str, expansion: Callable[[MagicMock], MagicMock]
) -> None:
    gateway = _gateway()

    _run(check_id, _context(gateway, _config()))

    expansion(gateway).assert_called_once_with(group_id=GROUP_ID, max_rows=50)
    gateway.find_entra_group_id.assert_not_called()


@pytest.mark.parametrize("check_id", ["sharepoint_entra_nested_groups_read"])
def test_entra_group_named_by_title_is_looked_up(check_id: str) -> None:
    gateway = _gateway()
    gateway.list_role_assignments.return_value = [
        _assignment(SharepointPrincipalType.ENTRA_GROUP, "Engineering")
    ]

    _run(check_id, _context(gateway, _config()))

    gateway.find_entra_group_id.assert_called_once_with(display_name="Engineering")


@pytest.mark.parametrize("check_id", ["sharepoint_entra_nested_groups_read"])
def test_refused_entra_group_lookup_names_the_graph_grant(check_id: str) -> None:
    gateway = _gateway()
    gateway.list_role_assignments.return_value = [
        _assignment(SharepointPrincipalType.ENTRA_GROUP, "Engineering")
    ]
    gateway.find_entra_group_id.side_effect = _refusal(403)

    with pytest.raises(InsufficientPermissionsError, match="GroupMember.Read.All"):
        _run(check_id, _context(gateway, _config()))


@pytest.mark.parametrize(("check_id", "expansion"), _EXPANSIONS)
def test_a_group_entra_no_longer_knows_by_name_is_skipped(
    check_id: str, expansion: Callable[[MagicMock], MagicMock]
) -> None:
    """The sync skips it, so a stale name must not block indexing."""
    gateway = _gateway()
    gateway.list_role_assignments.return_value = [
        _assignment(SharepointPrincipalType.ENTRA_GROUP, "Old Name")
    ]
    gateway.find_entra_group_id.return_value = None

    _run(check_id, _context(gateway, _config()))

    expansion(gateway).assert_not_called()


@pytest.mark.parametrize(("check_id", "expansion"), _EXPANSIONS)
def test_public_and_limited_entra_groups_are_not_expanded(
    check_id: str, expansion: Callable[[MagicMock], MagicMock]
) -> None:
    gateway = _gateway()
    gateway.list_role_assignments.return_value = [
        _assignment(SharepointPrincipalType.ENTRA_GROUP, PUBLIC_LOGIN, "Everyone"),
        _assignment(SharepointPrincipalType.ENTRA_GROUP, CLAIMS_LOGIN, "Guests", [1]),
    ]

    _run(check_id, _context(gateway, _config()))

    expansion(gateway).assert_not_called()


@pytest.mark.parametrize(("check_id", "expansion"), _EXPANSIONS)
def test_an_entra_group_entra_no_longer_has_is_skipped(
    check_id: str, expansion: Callable[[MagicMock], MagicMock]
) -> None:
    gateway = _gateway()
    expansion(gateway).side_effect = _refusal(404, "Request_ResourceNotFound")

    _run(check_id, _context(gateway, _config()))


@pytest.mark.parametrize(("check_id", "expansion"), _EXPANSIONS)
def test_refused_entra_group_expansion_names_the_graph_grant(
    check_id: str, expansion: Callable[[MagicMock], MagicMock]
) -> None:
    gateway = _gateway()
    expansion(gateway).side_effect = _refusal(403)

    with pytest.raises(InsufficientPermissionsError, match="GroupMember.Read.All"):
        _run(check_id, _context(gateway, _config()))


# sharepoint_entra_group_enumeration


@pytest.mark.parametrize(("check_id", "expansion"), _EXPANSIONS)
def test_entra_group_inside_a_site_group_is_found(
    check_id: str, expansion: Callable[[MagicMock], MagicMock]
) -> None:
    """The sync expands site groups and reaches the Entra groups inside."""
    gateway = _gateway()
    gateway.list_role_assignments.return_value = [SITE_GROUP]
    gateway.list_site_group_users.return_value = [
        SharepointPrincipal(
            principal_type=SharepointPrincipalType.USER,
            login_name="i:0#.f|membership|ada@contoso.com",
            title="Ada",
        ),
        ENTRA_GROUP.member,
    ]

    _run(check_id, _context(gateway, _config()))

    gateway.list_site_group_users.assert_called_once_with(
        site_url=SITE_URL, group_name="Eng Members", max_rows=50
    )
    expansion(gateway).assert_called_once_with(group_id=GROUP_ID, max_rows=50)


@pytest.mark.parametrize(("check_id", "expansion"), _EXPANSIONS)
def test_no_entra_group_anywhere_passes_without_a_graph_read(
    check_id: str, expansion: Callable[[MagicMock], MagicMock]
) -> None:
    gateway = _gateway()
    gateway.list_role_assignments.return_value = [SITE_GROUP]

    _run(check_id, _context(gateway, _config()))

    expansion(gateway).assert_not_called()


# sharepoint_document_permissions_read


def test_document_permissions_read_the_library_folder_and_item() -> None:
    gateway = _gateway()

    _run("sharepoint_document_permissions_read", _context(gateway, _config()))

    assert _securable_kinds(gateway) == [
        SharepointSecurableKind.LIBRARY,
        SharepointSecurableKind.FOLDER,
        SharepointSecurableKind.LIST_ITEM,
    ]
    gateway.get_folder_unique_id.assert_called_once_with(
        site_url=SITE_URL, server_relative_path="/sites/eng/Shared Documents/Plans"
    )
    item_securable = gateway.list_role_assignments.call_args.kwargs["securable"]
    assert (item_securable.list_id, item_securable.item_id) == ("list-id", 7)
    gateway.list_sharing_link_scopes.assert_not_called()


def test_sharing_links_are_read_under_the_setting() -> None:
    gateway = _gateway()
    config = _config(treat_sharing_link_as_public=True)

    _run("sharepoint_document_permissions_read", _context(gateway, config))

    assert gateway.list_sharing_link_scopes.call_args.kwargs["item"].id == "item-id"


def test_a_root_file_reads_no_folder() -> None:
    gateway = _gateway()
    gateway.get_delta_page.return_value = _delta_page(
        {**ITEM_JSON, "parentReference": {"driveId": "drive-id"}}
    )

    _run("sharepoint_document_permissions_read", _context(gateway, _config()))

    gateway.get_folder_unique_id.assert_not_called()
    assert _securable_kinds(gateway) == [
        SharepointSecurableKind.LIBRARY,
        SharepointSecurableKind.LIST_ITEM,
    ]


def test_a_library_without_a_list_id_is_skipped_like_the_sync() -> None:
    """The sync indexes it without permissions, so the check does not block."""
    gateway = _gateway()
    gateway.list_drives.return_value = [DRIVE.model_copy(update={"list_id": None})]

    _run("sharepoint_document_permissions_read", _context(gateway, _config()))

    gateway.list_role_assignments.assert_not_called()


def test_an_empty_library_proves_the_library_read() -> None:
    gateway = _gateway()
    gateway.get_delta_page.return_value = _delta_page()

    _run("sharepoint_document_permissions_read", _context(gateway, _config()))

    assert _securable_kinds(gateway) == [SharepointSecurableKind.LIBRARY]


def test_document_permissions_stop_after_the_first_libraries() -> None:
    """Ten empty libraries prove the library read and pass, since the sync
    runs this check before every attempt."""
    gateway = _gateway()
    gateway.list_drives.return_value = [DRIVE] * 11
    gateway.get_delta_page.return_value = _delta_page()

    _run("sharepoint_document_permissions_read", _context(gateway, _config()))

    assert gateway.get_delta_page.call_count == 10
    assert gateway.list_role_assignments.call_count == 10


def test_an_item_without_a_list_item_id_is_indeterminate() -> None:
    gateway = _gateway()
    gateway.get_list_item_id.return_value = None

    with pytest.raises(UnexpectedValidationError, match="list item id"):
        _run("sharepoint_document_permissions_read", _context(gateway, _config()))


def test_a_sampled_item_that_went_away_is_skipped() -> None:
    """The sync records that item and moves on, so the check does not block."""
    gateway = _gateway()
    gateway.list_role_assignments.side_effect = [[], [], _refusal(404, "itemNotFound")]

    _run("sharepoint_document_permissions_read", _context(gateway, _config()))


def test_permission_probes_read_one_page() -> None:
    gateway = _gateway()

    _run("sharepoint_document_permissions_read", _context(gateway, _config()))

    assert {
        call.kwargs["max_rows"] for call in gateway.list_role_assignments.call_args_list
    } == {100}


def test_refused_item_permissions_name_the_rest_grant() -> None:
    gateway = _gateway()
    gateway.list_role_assignments.side_effect = [[], [], _refusal(403)]

    with pytest.raises(InsufficientPermissionsError, match="plan.pdf"):
        _run("sharepoint_document_permissions_read", _context(gateway, _config()))


def test_document_permissions_are_skipped_when_documents_are_off() -> None:
    (result,) = run_capability_checks(
        [_CHECKS_BY_ID["sharepoint_document_permissions_read"]],
        _context(_gateway(), _config(include_site_documents=False)),
    )

    assert result.status is CapabilityCheckStatus.SKIPPED


# sharepoint_page_permissions_read


def test_page_permissions_read_the_first_page() -> None:
    gateway = _gateway()

    _run("sharepoint_page_permissions_read", _context(gateway, _config()))

    securable = gateway.list_role_assignments.call_args.kwargs["securable"]
    assert securable.kind is SharepointSecurableKind.PAGE
    assert securable.page_url == f"{SITE_URL}/SitePages/Home.aspx"


def test_page_permissions_move_past_a_site_without_a_pages_listing() -> None:
    gateway = _gateway()
    gateway.list_site_pages.side_effect = [
        _refusal(404, "itemNotFound"),
        SitePagesPage(pages=[{"id": "p", "webUrl": f"{OTHER_SITE_URL}/x.aspx"}]),
    ]
    config = _config(sites=[SITE_URL, OTHER_SITE_URL])

    _run("sharepoint_page_permissions_read", _context(gateway, config))

    assert gateway.list_role_assignments.call_args.kwargs["site_url"] == OTHER_SITE_URL


def test_a_sampled_page_that_went_away_is_skipped() -> None:
    gateway = _gateway()
    gateway.list_role_assignments.side_effect = _refusal(404, "itemNotFound")

    _run("sharepoint_page_permissions_read", _context(gateway, _config()))


def test_refused_page_permissions_name_the_rest_grant() -> None:
    gateway = _gateway()
    gateway.list_role_assignments.side_effect = _refusal(403)

    with pytest.raises(InsufficientPermissionsError, match="Home.aspx"):
        _run("sharepoint_page_permissions_read", _context(gateway, _config()))


def test_page_permissions_are_skipped_when_pages_are_off() -> None:
    (result,) = run_capability_checks(
        [_CHECKS_BY_ID["sharepoint_page_permissions_read"]],
        _context(_gateway(), _config(include_site_pages=False)),
    )

    assert result.status is CapabilityCheckStatus.SKIPPED
