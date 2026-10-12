from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.microsoft_utils.entra_groups import (
    ResolvedEntraGroup,
)
from ee.onyx.external_permissions.sharepoint.permission_utils import (
    AZURE_AD_GROUP_PRINCIPAL_TYPE,
    SHAREPOINT_GROUP_PRINCIPAL_TYPE,
    USER_PRINCIPAL_TYPE,
    DocumentGroupsResult,
    GroupsResult,
    _get_azuread_groups,
    _get_nested_azuread_groups,
    _has_only_limited_access,
    _is_public_item,
    _resolve_document_groups,
    get_external_access_from_sharepoint,
    get_hierarchy_node_external_access_from_sharepoint,
    get_sharepoint_external_groups,
)
from onyx.access.models import ExternalAccess
from onyx.background.indexing.checkpointing_utils import check_checkpoint_size
from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.entra import EntraGroup
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.microsoft_utils.models import (
    SharepointPrincipal,
    SharepointRoleAssignment,
    SharepointSecurable,
    SharepointSecurableKind,
)
from onyx.connectors.sharepoint.connector import SharepointConnectorCheckpoint
from onyx.connectors.sharepoint.connector_utils import (
    SharepointGroup,
    SharepointPermissionCache,
    get_sharepoint_external_access,
    get_sharepoint_hierarchy_node_external_access,
)
from onyx.db.enums import HierarchyNodeType
from tests.unit.onyx.connectors.microsoft_utils.fake_sharepoint_reader import (
    FakeSharepointReader,
)

MODULE = "ee.onyx.external_permissions.sharepoint.permission_utils"
SITE_URL = "https://contoso.sharepoint.com/sites/eng"
PUBLIC_LOGIN = "c:0-.f|rolemanager|spo-grid-all-users/tenant-id"


def _make_ad_group(name: str, login_name: str | None = None) -> SharepointGroup:
    return SharepointGroup(
        name=name,
        login_name=login_name or name,
        principal_type=AZURE_AD_GROUP_PRINCIPAL_TYPE,
    )


def _make_sharepoint_group(name: str) -> SharepointGroup:
    return SharepointGroup(
        name=name,
        login_name=name,
        principal_type=SHAREPOINT_GROUP_PRINCIPAL_TYPE,
    )


def _assignment(
    principal_type: int,
    title: str,
    role_type_kinds: list[int] | None = None,
    user_principal_name: str | None = None,
) -> SharepointRoleAssignment:
    return SharepointRoleAssignment(
        member=SharepointPrincipal(
            principal_type=principal_type,
            login_name=title,
            title=title,
            user_principal_name=user_principal_name,
        ),
        role_type_kinds=role_type_kinds or [2],
    )


def _drive_item(item_id: str = "item-123") -> DriveItemData:
    return DriveItemData.from_graph_json(
        {
            "id": item_id,
            "name": "document.pdf",
            "webUrl": f"{SITE_URL}/document.pdf",
            "parentReference": {"driveId": "drive-id"},
        }
    )


@patch(f"{MODULE}._get_nested_azuread_groups")
def test_document_group_expansion_is_cached(mock_get_group: MagicMock) -> None:
    group = _make_ad_group("Engineering", "engineering-id")
    mock_get_group.return_value = set()
    cache = SharepointPermissionCache()

    first = _resolve_document_groups(MagicMock(), SITE_URL, {group}, cache)
    second = _resolve_document_groups(MagicMock(), SITE_URL, {group}, cache)

    assert first == second
    assert first.group_ids == {"Engineering"}
    mock_get_group.assert_called_once()


@patch(f"{MODULE}._get_sharepoint_groups")
def test_sharepoint_group_cache_is_scoped_to_site(
    mock_get_group: MagicMock,
) -> None:
    group = _make_sharepoint_group("Site Members")
    mock_get_group.return_value = (set(), set())
    cache = SharepointPermissionCache()

    _resolve_document_groups(
        MagicMock(), "https://tenant.sharepoint.com/sites/first", {group}, cache
    )
    _resolve_document_groups(
        MagicMock(), "https://tenant.sharepoint.com/sites/second", {group}, cache
    )

    assert mock_get_group.call_count == 2
    assert len(cache.group_expansions) == 2


@patch(f"{MODULE}._get_sharepoint_groups")
def test_sharepoint_group_404_is_not_cached(mock_get_group: MagicMock) -> None:
    mock_get_group.side_effect = MicrosoftGraphError(404, "itemNotFound", "gone")
    group = _make_sharepoint_group("Missing Group")
    cache = SharepointPermissionCache()

    with pytest.raises(MicrosoftGraphError):
        _resolve_document_groups(MagicMock(), SITE_URL, {group}, cache)

    assert cache.group_expansions == {}


def test_deleted_entra_group_expands_to_nothing() -> None:
    group_id = "11111111-1111-1111-1111-111111111111"
    reader = FakeSharepointReader(
        nested_entra_groups={
            group_id: MicrosoftGraphError(404, "Request_ResourceNotFound", "")
        }
    )
    cache = SharepointPermissionCache()

    result = _resolve_document_groups(
        reader, SITE_URL, {_make_ad_group("Removed", group_id)}, cache
    )

    assert result.group_ids == {"Removed"}
    assert next(iter(cache.group_expansions.values())).nested_groups == set()


@patch(f"{MODULE}._get_nested_azuread_groups")
def test_ad_group_claims_token_and_guid_share_cache(
    mock_get_group: MagicMock,
) -> None:
    group_id = "11111111-1111-1111-1111-111111111111"
    claims_group = _make_ad_group("Engineering Members", f"c:0t.c|tenant|{group_id}")
    guid_group = _make_ad_group("Engineering Owners", group_id)
    mock_get_group.return_value = set()
    cache = SharepointPermissionCache()

    result = _resolve_document_groups(
        MagicMock(), SITE_URL, {claims_group, guid_group}, cache
    )

    mock_get_group.assert_called_once()
    assert result.group_ids == {"Engineering Members", "Engineering Owners"}


@patch(f"{MODULE}._get_nested_azuread_groups")
def test_document_group_cache_survives_checkpoint(
    mock_get_group: MagicMock,
) -> None:
    group = _make_ad_group("Engineering", "engineering-id")
    nested_group = _make_ad_group("Platform", "platform-id")
    mock_get_group.side_effect = [{nested_group}, set()]
    cache = SharepointPermissionCache()
    _resolve_document_groups(MagicMock(), SITE_URL, {group}, cache)

    checkpoint = SharepointConnectorCheckpoint(
        has_more=True,
        permission_cache=cache,
    )
    check_checkpoint_size(checkpoint)
    restored = SharepointConnectorCheckpoint.model_validate_json(
        checkpoint.model_dump_json()
    )
    _resolve_document_groups(
        MagicMock(),
        SITE_URL,
        {group},
        restored.permission_cache,
    )

    assert isinstance(
        next(iter(restored.permission_cache.group_expansions.values())).nested_groups,
        set,
    )
    assert mock_get_group.call_count == 2


@patch(f"{MODULE}._get_nested_azuread_groups")
def test_nested_public_group_uses_cached_parent_expansion(
    mock_get_group: MagicMock,
) -> None:
    parent = _make_ad_group("Site Members", "site-members-id")
    public = _make_ad_group("Everyone", PUBLIC_LOGIN)
    mock_get_group.return_value = {public}
    cache = SharepointPermissionCache()

    first = _resolve_document_groups(MagicMock(), SITE_URL, {parent}, cache)
    second = _resolve_document_groups(MagicMock(), SITE_URL, {parent}, cache)

    assert first.found_public_group
    assert second.found_public_group
    mock_get_group.assert_called_once()


@patch(f"{MODULE}._get_nested_azuread_groups")
def test_direct_public_group_skips_expansion(mock_get_group: MagicMock) -> None:
    public = _make_ad_group("Everyone", PUBLIC_LOGIN)

    result = _resolve_document_groups(
        MagicMock(),
        SITE_URL,
        {public},
        SharepointPermissionCache(),
    )

    assert result.found_public_group
    mock_get_group.assert_not_called()


@patch(f"{MODULE}._get_nested_azuread_groups")
def test_document_group_cycles_are_resolved_once(mock_get_group: MagicMock) -> None:
    first_group = _make_ad_group("First", "first-id")
    second_group = _make_ad_group("Second", "second-id")
    mock_get_group.side_effect = [{second_group}, {first_group}]

    result = _resolve_document_groups(
        MagicMock(),
        SITE_URL,
        {first_group},
        SharepointPermissionCache(),
    )

    assert result.group_ids == {"First", "Second"}
    assert not result.found_public_group
    assert mock_get_group.call_count == 2


@patch(f"{MODULE}.expand_entra_group")
def test_azuread_groups_wrap_shared_expansion(mock_expand: MagicMock) -> None:
    """Shared Entra results come back as SharePoint principals for the cache."""
    mock_expand.return_value = (
        {ResolvedEntraGroup(id="g2", name="Nested_g2")},
        {"alice@contoso.com"},
    )

    groups, user_emails = _get_azuread_groups(MagicMock(), "g1")

    assert groups == {_make_ad_group("Nested_g2", login_name="g2")}
    assert user_emails == {"alice@contoso.com"}


def test_document_readers_list_nested_groups_without_members() -> None:
    """A document's readers need only nested groups, so its members are never
    listed."""
    group_id = "11111111-1111-1111-1111-111111111111"
    nested_id = "22222222-2222-2222-2222-222222222222"
    reader = FakeSharepointReader(
        nested_entra_groups={group_id: [EntraGroup(id=nested_id, displayName="Nested")]}
    )

    groups = _get_nested_azuread_groups(reader, group_id)

    assert groups == {_make_ad_group(f"Nested_{nested_id}", login_name=nested_id)}
    assert "list_entra_group_members" not in reader.operations()


@pytest.mark.parametrize("role_type_kind", [1, 9])
def test_limited_access_detection_uses_numeric_role_type(role_type_kind: int) -> None:
    assert _has_only_limited_access(
        SharepointRoleAssignment(member=None, role_type_kinds=[role_type_kind])
    )


def test_limited_access_detection_rejects_mixed_roles() -> None:
    assert not _has_only_limited_access(
        SharepointRoleAssignment(member=None, role_type_kinds=[1, 2])
    )


def test_assignment_without_bindings_grants_access() -> None:
    assert not _has_only_limited_access(
        SharepointRoleAssignment(member=None, role_type_kinds=[])
    )


@patch(f"{MODULE}._get_groups_and_members_recursively")
def test_default_skips_ad_enumeration(mock_recursive: MagicMock) -> None:
    mock_recursive.return_value = GroupsResult(
        groups_to_emails={"SiteGroup_abc": {"alice@contoso.com"}},
        found_public_group=False,
    )
    reader = FakeSharepointReader()

    results = get_sharepoint_external_groups(reader, SITE_URL)

    assert len(results) == 1
    assert results[0].id == "SiteGroup_abc"
    assert results[0].user_emails == ["alice@contoso.com"]
    assert "list_entra_groups" not in reader.operations()


@pytest.mark.parametrize(
    ("node_type", "list_id", "folder_server_relative_path", "expected"),
    [
        (
            HierarchyNodeType.SITE,
            None,
            None,
            SharepointSecurable(kind=SharepointSecurableKind.SITE),
        ),
        (
            HierarchyNodeType.DRIVE,
            "list-id",
            None,
            SharepointSecurable(
                kind=SharepointSecurableKind.LIBRARY, list_id="list-id"
            ),
        ),
        (
            HierarchyNodeType.FOLDER,
            None,
            "/sites/eng/Shared Documents/API",
            SharepointSecurable(
                kind=SharepointSecurableKind.FOLDER, folder_unique_id="folder-guid"
            ),
        ),
    ],
)
def test_hierarchy_node_access_reads_the_node_assignments(
    node_type: HierarchyNodeType,
    list_id: str | None,
    folder_server_relative_path: str | None,
    expected: SharepointSecurable,
) -> None:
    reader = FakeSharepointReader(
        folder_ids={"/sites/eng/Shared Documents/API": "folder-guid"}
    )

    result = get_hierarchy_node_external_access_from_sharepoint(
        reader,
        SITE_URL,
        node_type,
        list_id,
        folder_server_relative_path,
    )

    assert result == ExternalAccess(
        external_user_emails=set(), external_user_group_ids=set(), is_public=False
    )
    assert reader.calls[-1].securable == expected
    assert reader.calls[-1].site_url == SITE_URL


def test_drive_hierarchy_without_list_id_fails_before_any_read() -> None:
    reader = FakeSharepointReader()

    with pytest.raises(ValueError, match="requires a list ID"):
        get_sharepoint_hierarchy_node_external_access(
            reader,
            SITE_URL,
            SharepointPermissionCache(),
            HierarchyNodeType.DRIVE,
            list_id=None,
        )

    assert reader.calls == []


def test_sharepoint_group_ids_are_scoped_to_their_site() -> None:
    first_site = "https://contoso.sharepoint.com/sites/first"
    second_site = "https://contoso.sharepoint.com/sites/second"
    reader = FakeSharepointReader(
        role_assignments={
            site: [_assignment(SHAREPOINT_GROUP_PRINCIPAL_TYPE, "Project Members")]
            for site in (first_site, second_site)
        }
    )

    first_groups = get_sharepoint_external_groups(reader, first_site)
    second_groups = get_sharepoint_external_groups(reader, second_site)

    assert first_groups[0].id == f"{first_site}::Project Members"
    assert second_groups[0].id == f"{second_site}::Project Members"


def test_group_sync_skips_users_and_limited_access() -> None:
    reader = FakeSharepointReader(
        role_assignments={
            SITE_URL: [
                _assignment(
                    USER_PRINCIPAL_TYPE, "Ada", user_principal_name="ada@contoso.com"
                ),
                _assignment(SHAREPOINT_GROUP_PRINCIPAL_TYPE, "Guests", [1]),
                _assignment(SHAREPOINT_GROUP_PRINCIPAL_TYPE, "Members"),
            ]
        }
    )

    groups = get_sharepoint_external_groups(reader, SITE_URL)

    assert [group.id for group in groups] == [f"{SITE_URL}::Members"]


@patch(f"{MODULE}.enumerate_entra_groups")
@patch(f"{MODULE}._get_groups_and_members_recursively")
def test_enumerate_all_includes_ad_groups(
    mock_recursive: MagicMock,
    mock_enum: MagicMock,
) -> None:
    mock_recursive.return_value = GroupsResult(
        groups_to_emails={"SiteGroup_abc": {"alice@contoso.com"}},
        found_public_group=False,
    )
    mock_enum.return_value = [
        ExternalUserGroup(id="ADGroup_xyz", user_emails=["bob@contoso.com"]),
    ]

    results = get_sharepoint_external_groups(
        FakeSharepointReader(), SITE_URL, enumerate_all_ad_groups=True
    )

    assert {r.id for r in results} == {"SiteGroup_abc", "ADGroup_xyz"}
    mock_enum.assert_called_once()


def test_site_page_access_reads_the_page_assignments() -> None:
    page_url = f"{SITE_URL}/SitePages/Home.aspx"
    reader = FakeSharepointReader()

    get_external_access_from_sharepoint(
        reader,
        SITE_URL,
        list_id=None,
        drive_item=None,
        site_page={"webUrl": page_url},
    )

    assert reader.calls[-1].securable == SharepointSecurable(
        kind=SharepointSecurableKind.PAGE, page_url=page_url
    )


@pytest.mark.parametrize(
    ("scopes", "treat_sharing_link_as_public", "expected"),
    [
        (["anonymous"], True, True),
        (["organization"], True, True),
        (["anonymous"], False, False),
        (["organization"], False, False),
        (["users"], True, False),
        ([], True, False),
    ],
)
def test_is_public_item_follows_sharing_link_scopes(
    scopes: list[str], treat_sharing_link_as_public: bool, expected: bool
) -> None:
    item = _drive_item()
    reader = FakeSharepointReader(link_scopes={item.id: scopes})

    assert _is_public_item(reader, item, treat_sharing_link_as_public) is expected


def test_is_public_item_default_is_false() -> None:
    item = _drive_item()
    reader = FakeSharepointReader(link_scopes={item.id: ["anonymous"]})

    assert _is_public_item(reader, item) is False
    assert reader.calls == []


def test_is_public_item_read_failure_is_not_public() -> None:
    item = _drive_item()
    reader = FakeSharepointReader(
        link_scopes={item.id: MicrosoftGraphError(503, "serviceNotAvailable", "")}
    )

    assert _is_public_item(reader, item, treat_sharing_link_as_public=True) is False


def test_drive_item_without_list_id_fails_before_any_read() -> None:
    reader = FakeSharepointReader()

    with pytest.raises(ValueError, match="requires a list ID"):
        get_sharepoint_external_access(
            reader=reader,
            site_url=SITE_URL,
            permission_cache=SharepointPermissionCache(),
            list_id=None,
            drive_item=_drive_item(),
        )

    assert reader.calls == []


def test_drive_item_public_when_sharing_link_enabled() -> None:
    """A public item skips role-assignment resolution entirely."""
    item = _drive_item()
    reader = FakeSharepointReader(link_scopes={item.id: ["anonymous"]})

    result = get_external_access_from_sharepoint(
        reader,
        SITE_URL,
        list_id="list-id",
        drive_item=item,
        site_page=None,
        treat_sharing_link_as_public=True,
    )

    assert result.is_public is True
    assert result.external_user_emails == set()
    assert result.external_user_group_ids == set()
    assert "list_role_assignments" not in reader.operations()


@patch(f"{MODULE}._resolve_document_groups")
def test_drive_item_falls_through_when_sharing_link_disabled(
    mock_resolve_groups: MagicMock,
) -> None:
    """Without the flag, access comes from the list item's role assignments."""
    mock_resolve_groups.return_value = DocumentGroupsResult(
        group_ids={"SiteMembers_abc"},
        found_public_group=False,
    )
    item = _drive_item()
    reader = FakeSharepointReader(list_item_ids={item.id: 42})

    result = get_external_access_from_sharepoint(
        reader,
        SITE_URL,
        list_id="list-id",
        drive_item=item,
        site_page=None,
        treat_sharing_link_as_public=False,
    )

    assert result.is_public is False
    assert result.external_user_group_ids == {"sitemembers_abc"}
    assert reader.calls[-1].securable == SharepointSecurable(
        kind=SharepointSecurableKind.LIST_ITEM, list_id="list-id", item_id=42
    )


def test_drive_item_without_list_item_id_fails() -> None:
    item = _drive_item()
    reader = FakeSharepointReader(list_item_ids={item.id: None})

    with pytest.raises(RuntimeError, match="list item ID"):
        get_external_access_from_sharepoint(
            reader, SITE_URL, list_id="list-id", drive_item=item, site_page=None
        )


def test_document_access_collects_users_and_prefixed_groups() -> None:
    reader = FakeSharepointReader(
        role_assignments={
            SITE_URL: [
                _assignment(
                    USER_PRINCIPAL_TYPE,
                    "Ada",
                    user_principal_name="ada@contoso.onmicrosoft.com",
                ),
                _assignment(USER_PRINCIPAL_TYPE, "No UPN"),
                _assignment(SHAREPOINT_GROUP_PRINCIPAL_TYPE, "Members"),
                _assignment(SHAREPOINT_GROUP_PRINCIPAL_TYPE, "Limited", [1]),
            ]
        }
    )

    result = get_hierarchy_node_external_access_from_sharepoint(
        reader, SITE_URL, HierarchyNodeType.SITE, None, None
    )

    assert result.external_user_emails == {"ada@contoso.com"}
    assert result.external_user_group_ids == {f"sharepoint_{SITE_URL}::members".lower()}
