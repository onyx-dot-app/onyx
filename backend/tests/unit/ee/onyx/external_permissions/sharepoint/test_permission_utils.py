from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from office365.runtime.client_request import ClientRequestException
from office365.sharepoint.client_context import ClientContext

from ee.onyx.external_permissions.microsoft_utils.entra_groups import (
    ResolvedEntraGroup,
)
from ee.onyx.external_permissions.sharepoint.permission_utils import (
    AZURE_AD_GROUP_PRINCIPAL_TYPE,
    SHAREPOINT_GROUP_PRINCIPAL_TYPE,
    DocumentGroupsResult,
    GroupsResult,
    _get_azuread_groups,
    _get_sharepoint_list_item_id,
    _has_only_limited_access,
    _is_public_item,
    _resolve_document_groups,
    get_external_access_from_sharepoint,
    get_hierarchy_node_external_access_from_sharepoint,
    get_sharepoint_external_groups,
)
from onyx.access.models import ExternalAccess
from onyx.background.indexing.checkpointing_utils import check_checkpoint_size
from onyx.connectors.sharepoint.connector import (
    DriveItemData,
    SharepointConnectorCheckpoint,
)
from onyx.connectors.sharepoint.connector_utils import (
    SharepointGroup,
    SharepointPermissionCache,
    get_sharepoint_external_access,
    get_sharepoint_hierarchy_node_external_access,
)
from onyx.db.enums import HierarchyNodeType

MODULE = "ee.onyx.external_permissions.sharepoint.permission_utils"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


@patch(f"{MODULE}.sleep_and_retry")
def test_sharepoint_ids_avoid_list_item_lookup(mock_sleep_and_retry: MagicMock) -> None:
    drive_item = DriveItemData.from_graph_json(
        {
            "id": "drive-item-id",
            "name": "document.pdf",
            "webUrl": "https://tenant.sharepoint.com/document.pdf",
            "parentReference": {"driveId": "drive-id"},
            "sharepointIds": {"listItemId": "42"},
        }
    ).to_sdk_driveitem(MagicMock())

    assert _get_sharepoint_list_item_id(drive_item) == 42
    mock_sleep_and_retry.assert_not_called()


def test_list_item_id_builds_numeric_sdk_resource_path() -> None:
    context = ClientContext("https://tenant.sharepoint.com/sites/test")
    item = context.web.lists.get_by_id(
        "11111111-1111-1111-1111-111111111111"
    ).items.get_by_id(42)

    assert item.resource_path.to_url().endswith("/items/GetById(42)")


@patch(f"{MODULE}._get_azuread_groups")
def test_document_group_expansion_is_cached(mock_get_group: MagicMock) -> None:
    group = _make_ad_group("Engineering", "engineering-id")
    mock_get_group.return_value = (set(), {"alice@contoso.com"})
    cache = SharepointPermissionCache()

    first = _resolve_document_groups(MagicMock(), MagicMock(), {group}, cache)
    second = _resolve_document_groups(MagicMock(), MagicMock(), {group}, cache)

    assert first == second
    assert first.group_ids == {"Engineering"}
    mock_get_group.assert_called_once()


@patch(f"{MODULE}._get_sharepoint_groups")
def test_sharepoint_group_cache_is_scoped_to_site(
    mock_get_group: MagicMock,
) -> None:
    group = _make_sharepoint_group("Site Members")
    first_context = MagicMock(base_url="https://tenant.sharepoint.com/sites/first")
    second_context = MagicMock(base_url="https://tenant.sharepoint.com/sites/second")
    mock_get_group.return_value = (set(), set())
    cache = SharepointPermissionCache()

    _resolve_document_groups(first_context, MagicMock(), {group}, cache)
    _resolve_document_groups(second_context, MagicMock(), {group}, cache)

    assert mock_get_group.call_count == 2
    assert len(cache.group_expansions) == 2


@patch(f"{MODULE}._get_sharepoint_groups")
def test_sharepoint_group_404_is_not_cached(mock_get_group: MagicMock) -> None:
    response = MagicMock(status_code=404, headers={}, content=b"")
    mock_get_group.side_effect = ClientRequestException(response=response)
    group = _make_sharepoint_group("Missing Group")
    cache = SharepointPermissionCache()

    with pytest.raises(ClientRequestException):
        _resolve_document_groups(MagicMock(), MagicMock(), {group}, cache)

    assert cache.group_expansions == {}


@patch(f"{MODULE}._get_azuread_groups")
def test_ad_group_claims_token_and_guid_share_cache(
    mock_get_group: MagicMock,
) -> None:
    group_id = "11111111-1111-1111-1111-111111111111"
    claims_group = _make_ad_group("Engineering Members", f"c:0t.c|tenant|{group_id}")
    guid_group = _make_ad_group("Engineering Owners", group_id)
    mock_get_group.return_value = (set(), set())
    cache = SharepointPermissionCache()

    result = _resolve_document_groups(
        MagicMock(), MagicMock(), {claims_group, guid_group}, cache
    )

    mock_get_group.assert_called_once()
    assert result.group_ids == {"Engineering Members", "Engineering Owners"}


@patch(f"{MODULE}._get_azuread_groups")
def test_document_group_cache_survives_checkpoint(
    mock_get_group: MagicMock,
) -> None:
    group = _make_ad_group("Engineering", "engineering-id")
    nested_group = _make_ad_group("Platform", "platform-id")
    mock_get_group.side_effect = [({nested_group}, set()), (set(), set())]
    cache = SharepointPermissionCache()
    _resolve_document_groups(MagicMock(), MagicMock(), {group}, cache)

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
        MagicMock(),
        {group},
        restored.permission_cache,
    )

    assert isinstance(
        next(iter(restored.permission_cache.group_expansions.values())).nested_groups,
        set,
    )
    assert mock_get_group.call_count == 2


@patch(f"{MODULE}._get_azuread_groups")
def test_nested_public_group_uses_cached_parent_expansion(
    mock_get_group: MagicMock,
) -> None:
    parent = _make_ad_group("Site Members", "site-members-id")
    public = _make_ad_group(
        "Everyone",
        "c:0-.f|rolemanager|spo-grid-all-users/tenant-id",
    )
    mock_get_group.return_value = ({public}, set())
    cache = SharepointPermissionCache()

    first = _resolve_document_groups(MagicMock(), MagicMock(), {parent}, cache)
    second = _resolve_document_groups(MagicMock(), MagicMock(), {parent}, cache)

    assert first.found_public_group
    assert second.found_public_group
    mock_get_group.assert_called_once()


@patch(f"{MODULE}._get_azuread_groups")
def test_direct_public_group_skips_expansion(mock_get_group: MagicMock) -> None:
    public = _make_ad_group(
        "Everyone",
        "c:0-.f|rolemanager|spo-grid-all-users/tenant-id",
    )

    result = _resolve_document_groups(
        MagicMock(),
        MagicMock(),
        {public},
        SharepointPermissionCache(),
    )

    assert result.found_public_group
    mock_get_group.assert_not_called()


@patch(f"{MODULE}._get_azuread_groups")
def test_document_group_cycles_are_resolved_once(mock_get_group: MagicMock) -> None:
    first_group = _make_ad_group("First", "first-id")
    second_group = _make_ad_group("Second", "second-id")
    mock_get_group.side_effect = [
        ({second_group}, set()),
        ({first_group}, set()),
    ]

    result = _resolve_document_groups(
        MagicMock(),
        MagicMock(),
        {first_group},
        SharepointPermissionCache(),
    )

    assert result.group_ids == {"First", "Second"}
    assert not result.found_public_group
    assert mock_get_group.call_count == 2


# ---------------------------------------------------------------------------
# _get_azuread_groups
# ---------------------------------------------------------------------------


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


@pytest.mark.parametrize(
    ("role_type_kind", "localized_name"),
    [
        (1, "Beschränkter Zugriff"),
        (9, "Nur Web – beschränkter Zugriff"),
    ],
)
def test_limited_access_detection_uses_numeric_role_type(
    role_type_kind: int,
    localized_name: str,
) -> None:
    binding = MagicMock()
    binding.role_type_kind = role_type_kind
    binding.name = localized_name

    assert _has_only_limited_access([binding])


def test_limited_access_detection_rejects_mixed_roles() -> None:
    limited_access = MagicMock()
    limited_access.role_type_kind = 1
    read_access = MagicMock()
    read_access.role_type_kind = 2

    assert not _has_only_limited_access([limited_access, read_access])


# ---------------------------------------------------------------------------
# get_sharepoint_external_groups
# ---------------------------------------------------------------------------


@patch(f"{MODULE}._get_groups_and_members_recursively")
@patch(f"{MODULE}.sleep_and_retry")
def test_default_skips_ad_enumeration(
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_recursive: MagicMock,
) -> None:
    mock_recursive.return_value = GroupsResult(
        groups_to_emails={"SiteGroup_abc": {"alice@contoso.com"}},
        found_public_group=False,
    )

    results = get_sharepoint_external_groups(
        client_context=MagicMock(),
        graph_client=MagicMock(),
    )

    assert len(results) == 1
    assert results[0].id == "SiteGroup_abc"
    assert results[0].user_emails == ["alice@contoso.com"]


@pytest.mark.parametrize(
    ("node_type", "list_id", "folder_server_relative_path"),
    [
        (HierarchyNodeType.SITE, None, None),
        (HierarchyNodeType.DRIVE, "list-id", None),
        (HierarchyNodeType.FOLDER, None, "/sites/eng/Shared Documents/API"),
    ],
)
@patch(f"{MODULE}._get_external_access_from_securable_object")
def test_hierarchy_node_access_uses_securable_object(
    mock_get_access: MagicMock,
    node_type: HierarchyNodeType,
    list_id: str | None,
    folder_server_relative_path: str | None,
) -> None:
    expected_access = ExternalAccess.empty()
    mock_get_access.return_value = expected_access
    ctx = MagicMock()
    graph_client = MagicMock()

    result = get_hierarchy_node_external_access_from_sharepoint(
        ctx,
        graph_client,
        node_type,
        list_id,
        folder_server_relative_path,
    )

    assert result is expected_access
    securable_object = mock_get_access.call_args.args[2]
    if node_type == HierarchyNodeType.SITE:
        assert securable_object is ctx.web
    elif node_type == HierarchyNodeType.DRIVE:
        ctx.web.lists.get_by_id.assert_called_once_with("list-id")
        ctx.web.lists.get_by_title.assert_not_called()
    else:
        ctx.web.get_folder_by_server_relative_path.assert_called_once_with(
            "/sites/eng/Shared Documents/API"
        )
    assert mock_get_access.call_args.kwargs == {"add_prefix": True}


def test_drive_hierarchy_without_list_id_fails_without_name_lookup() -> None:
    client_context = MagicMock()

    with pytest.raises(ValueError, match="requires a list ID"):
        get_sharepoint_hierarchy_node_external_access(
            client_context,
            MagicMock(),
            SharepointPermissionCache(),
            HierarchyNodeType.DRIVE,
            list_id=None,
        )

    client_context.web.lists.get_by_id.assert_not_called()
    client_context.web.lists.get_by_title.assert_not_called()


@patch(f"{MODULE}._get_groups_and_members_recursively")
@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_sharepoint_group_ids_are_scoped_to_their_site(
    _mock_sleep: MagicMock,
    mock_recursive: MagicMock,
) -> None:
    def resolve_groups(
        client_context: MagicMock,
        _graph_client: MagicMock,
        groups: set[Any],
        is_group_sync: bool = False,
    ) -> GroupsResult:
        assert is_group_sync
        group_name = next(iter(groups)).name
        email = (
            "alice@contoso.com"
            if client_context.base_url.endswith("/first")
            else "bob@contoso.com"
        )
        return GroupsResult(
            groups_to_emails={group_name: {email}},
            found_public_group=False,
        )

    mock_recursive.side_effect = resolve_groups

    def make_site_context(site_url: str) -> MagicMock:
        member = MagicMock()
        member.principal_type = SHAREPOINT_GROUP_PRINCIPAL_TYPE
        member.title = "Project Members"
        member.login_name = "Project Members"
        assignment = MagicMock()
        assignment.role_definition_bindings = None
        assignment.member = member
        assignments = MagicMock()
        assignments.current_page = [assignment]

        def get_all(*, page_size: int, page_loaded: Any) -> MagicMock:
            assert page_size > 0
            page_loaded(assignments)
            return assignments

        client_context = MagicMock()
        client_context.base_url = site_url
        client_context.web.role_assignments.expand.return_value.get_all.side_effect = (
            get_all
        )
        return client_context

    first_site = make_site_context("https://contoso.sharepoint.com/sites/first")
    second_site = make_site_context("https://contoso.sharepoint.com/sites/second")

    first_groups = get_sharepoint_external_groups(
        client_context=first_site,
        graph_client=MagicMock(),
    )
    second_groups = get_sharepoint_external_groups(
        client_context=second_site,
        graph_client=MagicMock(),
    )

    assert first_groups[0].id != second_groups[0].id


@patch(f"{MODULE}.enumerate_entra_groups")
@patch(f"{MODULE}._get_groups_and_members_recursively")
@patch(f"{MODULE}.sleep_and_retry")
def test_enumerate_all_includes_ad_groups(
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_recursive: MagicMock,
    mock_enum: MagicMock,
) -> None:
    from ee.onyx.db.external_perm import ExternalUserGroup

    mock_recursive.return_value = GroupsResult(
        groups_to_emails={"SiteGroup_abc": {"alice@contoso.com"}},
        found_public_group=False,
    )
    mock_enum.return_value = [
        ExternalUserGroup(id="ADGroup_xyz", user_emails=["bob@contoso.com"]),
    ]

    results = get_sharepoint_external_groups(
        client_context=MagicMock(),
        graph_client=MagicMock(),
        graph_api=MagicMock(),
        enumerate_all_ad_groups=True,
    )

    assert len(results) == 2
    ids = {r.id for r in results}
    assert ids == {"SiteGroup_abc", "ADGroup_xyz"}
    mock_enum.assert_called_once()


@patch(f"{MODULE}.enumerate_entra_groups")
@patch(f"{MODULE}._get_groups_and_members_recursively")
@patch(f"{MODULE}.sleep_and_retry")
def test_enumerate_all_without_graph_api_skips(
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_recursive: MagicMock,
    mock_enum: MagicMock,
) -> None:
    """Even if enumerate_all_ad_groups=True, no Graph client means skip."""
    mock_recursive.return_value = GroupsResult(
        groups_to_emails={},
        found_public_group=False,
    )

    results = get_sharepoint_external_groups(
        client_context=MagicMock(),
        graph_client=MagicMock(),
        graph_api=None,
        enumerate_all_ad_groups=True,
    )

    assert results == []
    mock_enum.assert_not_called()


# ---------------------------------------------------------------------------
# get_external_access_from_sharepoint – site page URL handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "site_base_url, web_url, expected_relative_url",
    [
        (
            "https://tenant.sharepoint.com/sites/Evan%27sSite",
            "https://tenant.sharepoint.com/sites/Evan%27sSite/SitePages/Home.aspx",
            "/sites/Evan%27sSite/SitePages/Home.aspx",
        ),
        (
            "https://tenant.sharepoint.com/sites/NormalSite",
            "https://tenant.sharepoint.com/sites/NormalSite/SitePages/Page.aspx",
            "/sites/NormalSite/SitePages/Page.aspx",
        ),
        (
            "https://tenant.sharepoint.com/sites/Site%20With%20Spaces",
            "https://tenant.sharepoint.com/sites/Site%20With%20Spaces/SitePages/Doc.aspx",
            "/sites/Site%20With%20Spaces/SitePages/Doc.aspx",
        ),
    ],
    ids=["apostrophe-encoded", "no-special-chars", "space-encoded"],
)
@patch(f"{MODULE}._get_groups_and_members_recursively")
@patch(f"{MODULE}.sleep_and_retry")
def test_site_page_url_not_duplicated(
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_recursive: MagicMock,
    site_base_url: str,
    web_url: str,
    expected_relative_url: str,
) -> None:
    """Regression: the server-relative URL passed to
    get_file_by_server_relative_url must preserve percent-encoding so the
    Office365 library's SPResPath.create_relative() recognises the site prefix
    and doesn't duplicate it."""
    mock_recursive.return_value = GroupsResult(
        groups_to_emails={},
        found_public_group=False,
    )

    ctx = MagicMock()
    ctx.base_url = site_base_url

    site_page = {"webUrl": web_url}

    get_external_access_from_sharepoint(
        client_context=ctx,
        graph_client=MagicMock(),
        list_id=None,
        drive_item=None,
        site_page=site_page,
    )

    ctx.web.get_file_by_server_relative_url.assert_called_once_with(
        expected_relative_url
    )


# ---------------------------------------------------------------------------
# _is_public_item – sharing link visibility
# ---------------------------------------------------------------------------


def _make_permission(scope: str | None) -> MagicMock:
    perm = MagicMock()
    if scope is None:
        perm.link = None
    else:
        perm.link = MagicMock()
        perm.link.scope = scope
    return perm


def _make_drive_item_with_permissions(
    permissions: list[MagicMock],
) -> MagicMock:
    drive_item = MagicMock()
    drive_item.id = "item-123"
    drive_item.permissions.get_all.return_value = permissions
    return drive_item


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_is_public_item_anonymous_link_when_enabled(
    _mock_sleep: MagicMock,
) -> None:
    drive_item = _make_drive_item_with_permissions([_make_permission("anonymous")])
    assert _is_public_item(drive_item, treat_sharing_link_as_public=True) is True


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_is_public_item_org_link_when_enabled(
    _mock_sleep: MagicMock,
) -> None:
    drive_item = _make_drive_item_with_permissions([_make_permission("organization")])
    assert _is_public_item(drive_item, treat_sharing_link_as_public=True) is True


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_is_public_item_anonymous_link_when_disabled(
    _mock_sleep: MagicMock,
) -> None:
    """When the flag is off, anonymous links do NOT make the item public."""
    drive_item = _make_drive_item_with_permissions([_make_permission("anonymous")])
    assert _is_public_item(drive_item, treat_sharing_link_as_public=False) is False


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_is_public_item_org_link_when_disabled(
    _mock_sleep: MagicMock,
) -> None:
    """When the flag is off, org links do NOT make the item public."""
    drive_item = _make_drive_item_with_permissions([_make_permission("organization")])
    assert _is_public_item(drive_item, treat_sharing_link_as_public=False) is False


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_is_public_item_no_sharing_links(
    _mock_sleep: MagicMock,
) -> None:
    """User-level permissions only — not public even when flag is on."""
    drive_item = _make_drive_item_with_permissions([_make_permission(None)])
    assert _is_public_item(drive_item, treat_sharing_link_as_public=True) is False


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_is_public_item_default_is_false(
    _mock_sleep: MagicMock,
) -> None:
    """Default value of the flag is False, so sharing links are ignored."""
    drive_item = _make_drive_item_with_permissions([_make_permission("anonymous")])
    assert _is_public_item(drive_item) is False


def test_is_public_item_skips_api_call_when_disabled() -> None:
    """When the flag is off, the permissions API is never called."""
    drive_item = MagicMock()
    _is_public_item(drive_item, treat_sharing_link_as_public=False)
    drive_item.permissions.get_all.assert_not_called()


# ---------------------------------------------------------------------------
# get_external_access_from_sharepoint – sharing link integration
# ---------------------------------------------------------------------------


def test_drive_item_without_list_id_fails_without_name_lookup() -> None:
    client_context = MagicMock()

    with pytest.raises(ValueError, match="requires a list ID"):
        get_sharepoint_external_access(
            ctx=client_context,
            graph_client=MagicMock(),
            permission_cache=SharepointPermissionCache(),
            list_id=None,
            drive_item=MagicMock(),
        )

    client_context.web.lists.get_by_id.assert_not_called()
    client_context.web.lists.get_by_title.assert_not_called()


@patch(f"{MODULE}._is_public_item", return_value=True)
@patch(f"{MODULE}.sleep_and_retry")
def test_drive_item_public_when_sharing_link_enabled(
    _mock_sleep: MagicMock,
    _mock_is_public: MagicMock,
) -> None:
    """With treat_sharing_link_as_public=True, a public item returns is_public=True
    and skips role-assignment resolution entirely."""
    drive_item = MagicMock()

    result = get_external_access_from_sharepoint(
        client_context=MagicMock(),
        graph_client=MagicMock(),
        list_id="list-id",
        drive_item=drive_item,
        site_page=None,
        treat_sharing_link_as_public=True,
    )

    assert result.is_public is True
    assert result.external_user_emails == set()
    assert result.external_user_group_ids == set()


@patch(f"{MODULE}._resolve_document_groups")
@patch(f"{MODULE}.sleep_and_retry")
@patch(f"{MODULE}._is_public_item", return_value=False)
def test_drive_item_falls_through_when_sharing_link_disabled(
    _mock_is_public: MagicMock,
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_resolve_groups: MagicMock,
) -> None:
    """With treat_sharing_link_as_public=False, the function falls through to
    role-assignment-based permission resolution."""
    mock_resolve_groups.return_value = DocumentGroupsResult(
        group_ids={"SiteMembers_abc"},
        found_public_group=False,
    )

    client_context = MagicMock()
    result = get_external_access_from_sharepoint(
        client_context=client_context,
        graph_client=MagicMock(),
        list_id="list-id",
        drive_item=MagicMock(),
        site_page=None,
        treat_sharing_link_as_public=False,
    )

    assert result.is_public is False
    assert len(result.external_user_group_ids) > 0
    client_context.web.lists.get_by_id.assert_called_once_with("list-id")
    client_context.web.lists.get_by_title.assert_not_called()
