"""The SharePoint permission reads address the right SDK objects and hand back
plain data, with refusals as MicrosoftGraphError."""

import json
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from office365.graph_client import GraphClient
from office365.runtime.auth.token_response import TokenResponse
from office365.runtime.client_request import ClientRequestException
from office365.sharepoint.client_context import ClientContext

from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.entra import EntraGroup
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.microsoft_utils.models import (
    EntraMember,
    EntraMemberKind,
    SharepointPrincipal,
    SharepointRoleAssignment,
    SharepointSecurable,
    SharepointSecurableKind,
)
from onyx.connectors.microsoft_utils.sharepoint_rest import (
    SharepointRestReads,
    _securable_object,
    read_entra_group_members,
    read_folder_unique_id,
    read_list_item_id,
    read_nested_entra_groups,
    read_role_assignments,
    read_sharing_link_scopes,
    read_site_group_users,
)

MODULE = "onyx.connectors.microsoft_utils.sharepoint_rest"
SITE_URL = "https://contoso.sharepoint.com/sites/eng"


def _drive_item(list_item_id: str | None = None) -> DriveItemData:
    payload: dict[str, Any] = {
        "id": "drive-item-id",
        "name": "document.pdf",
        "webUrl": f"{SITE_URL}/document.pdf",
        "parentReference": {"driveId": "drive-id"},
    }
    if list_item_id:
        payload["sharepointIds"] = {"listItemId": list_item_id}
    return DriveItemData.from_graph_json(payload)


def _paged(items: list[Any]) -> MagicMock:
    """An SDK collection whose get_all hands one page to page_loaded."""
    page = MagicMock()
    page.current_page = items

    def get_all(*, page_loaded: Any, page_size: int | None = None) -> MagicMock:
        assert page_size is None or page_size > 0
        page_loaded(page)
        return page

    collection = MagicMock()
    collection.get_all.side_effect = get_all
    collection.expand.return_value = collection
    return collection


@patch(f"{MODULE}.sleep_and_retry")
def test_sharepoint_ids_avoid_list_item_lookup(mock_sleep_and_retry: MagicMock) -> None:
    assert read_list_item_id(MagicMock(), _drive_item(list_item_id="42")) == 42
    mock_sleep_and_retry.assert_not_called()


def test_list_item_securable_builds_numeric_sdk_resource_path() -> None:
    context = ClientContext(SITE_URL)

    item = _securable_object(
        context,
        SharepointSecurable(
            kind=SharepointSecurableKind.LIST_ITEM,
            list_id="11111111-1111-1111-1111-111111111111",
            item_id=42,
        ),
    )

    assert item.resource_path.to_url().endswith("/items/GetById(42)")


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
def test_site_page_url_keeps_its_encoding(
    site_base_url: str, web_url: str, expected_relative_url: str
) -> None:
    """The SDK compares the path with the encoded site path, so a decoded path
    duplicates the site prefix."""
    context = MagicMock(base_url=site_base_url)

    _securable_object(
        context,
        SharepointSecurable(kind=SharepointSecurableKind.PAGE, page_url=web_url),
    )

    context.web.get_file_by_server_relative_url.assert_called_once_with(
        expected_relative_url
    )


def test_incomplete_securable_is_rejected() -> None:
    with pytest.raises(ValueError, match="Incomplete"):
        _securable_object(
            MagicMock(), SharepointSecurable(kind=SharepointSecurableKind.LIBRARY)
        )


def test_folder_id_lookup_sends_path_as_query_alias() -> None:
    """A long path inline in the URL path makes SharePoint answer 401."""
    folder_path = "/sites/eng/Shared Documents/" + "/".join(["R&D #1's"] * 40)
    ctx = ClientContext(SITE_URL).with_access_token(
        lambda: TokenResponse(access_token="token", token_type="Bearer")
    )
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps({"UniqueId": "folder-guid"}).encode()

    with patch(
        "office365.runtime.client_request.requests.get", return_value=response
    ) as mock_get:
        folder_id = read_folder_unique_id(ctx, folder_path)

    assert folder_id == "folder-guid"
    url = urlparse(mock_get.call_args.kwargs["url"])
    assert url.path == (
        "/sites/eng/_api/Web/getFolderByServerRelativePath(DecodedUrl=@a)"
    )
    query = parse_qs(url.query)
    assert query["@a"] == ["'" + folder_path.replace("'", "''") + "'"]
    assert query["$select"] == ["UniqueId"]


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_role_assignments_come_back_as_plain_data(_mock_sleep: MagicMock) -> None:
    binding = MagicMock(role_type_kind=1)
    member = MagicMock(
        principal_type=1,
        login_name="i:0#.f|membership|ada@contoso.com",
        title="Ada",
        user_principal_name="ada@contoso.com",
    )
    with_member = MagicMock(member=member, role_definition_bindings=[binding])
    without_member = MagicMock(member=None, role_definition_bindings=None)
    context = MagicMock()
    context.web.role_assignments = _paged([with_member, without_member])

    assignments = read_role_assignments(
        context, SharepointSecurable(kind=SharepointSecurableKind.SITE)
    )

    assert assignments == [
        SharepointRoleAssignment(
            member=SharepointPrincipal(
                principal_type=1,
                login_name="i:0#.f|membership|ada@contoso.com",
                title="Ada",
                user_principal_name="ada@contoso.com",
            ),
            role_type_kinds=[1],
        ),
        SharepointRoleAssignment(member=None, role_type_kinds=[]),
    ]
    context.web.role_assignments.expand.assert_called_once_with(
        ["Member", "RoleDefinitionBindings"]
    )


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_role_assignments_read_one_page_under_max_rows(_mock_sleep: MagicMock) -> None:
    context = MagicMock()
    expanded = context.web.role_assignments.expand.return_value
    page = MagicMock()
    page.current_page = []
    expanded.top.return_value.get.return_value = page

    assignments = read_role_assignments(
        context, SharepointSecurable(kind=SharepointSecurableKind.SITE), max_rows=100
    )

    expanded.top.assert_called_once_with(100)
    expanded.get_all.assert_not_called()
    assert assignments == []


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_site_group_users_read_one_page_under_max_rows(_mock_sleep: MagicMock) -> None:
    context = MagicMock()
    users = context.web.site_groups.get_by_name.return_value.users
    page = MagicMock()
    page.current_page = [
        MagicMock(
            principal_type=1,
            login_name="i:0#.f|membership|a@x.com",
            title="A",
            user_principal_name="a@x.com",
        )
    ]
    users.top.return_value.get.return_value = page

    principals = read_site_group_users(context, "Members", max_rows=50)

    users.top.assert_called_once_with(50)
    users.get_all.assert_not_called()
    assert [principal.title for principal in principals] == ["A"]


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_incomplete_principals_are_skipped(_mock_sleep: MagicMock) -> None:
    complete = MagicMock(
        principal_type=8,
        login_name="Members",
        title="Members",
        user_principal_name=None,
    )
    no_title = MagicMock(principal_type=8, login_name="Ghost", title=None)
    context = MagicMock()
    context.web.site_groups.get_by_name.return_value.users = _paged(
        [complete, no_title]
    )

    users = read_site_group_users(context, "Owners")

    assert [user.login_name for user in users] == ["Members"]


@patch(f"{MODULE}.sleep_and_retry")
def test_link_scopes_skip_permissions_without_a_link(_mock_sleep: MagicMock) -> None:
    with patch.object(DriveItemData, "to_sdk_driveitem") as to_sdk:
        to_sdk.return_value.permissions = _paged(
            [
                MagicMock(link=MagicMock(scope="anonymous")),
                MagicMock(link=None),
                MagicMock(link=MagicMock(scope="organization")),
            ]
        )
        scopes = read_sharing_link_scopes(MagicMock(), _drive_item())

    assert scopes == ["anonymous", "organization"]


def _directory_object(data: dict[str, Any], type_name: str = "DirectoryObject") -> Any:
    """The classifier falls back on the SDK class name, so the fake is named."""
    return type(type_name, (), {"to_json": lambda _self: data})()


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_entra_members_are_classified(_mock_sleep: MagicMock) -> None:
    graph_client = MagicMock()
    graph_client.groups.__getitem__.return_value.members = _paged(
        [
            _directory_object({"id": "u1", "userPrincipalName": "ada@contoso.com"}),
            _directory_object({"id": "u2", "mail": "bob@contoso.com"}),
            _directory_object({"id": "g1", "displayName": "Nested", "groupTypes": []}),
            _directory_object({"displayName": "Typed"}, type_name="Group"),
            _directory_object({}, type_name="Device"),
        ]
    )

    members = read_entra_group_members(graph_client, "parent")

    assert [member.kind for member in members] == [
        EntraMemberKind.USER,
        EntraMemberKind.USER,
        EntraMemberKind.GROUP,
        EntraMemberKind.GROUP,
        EntraMemberKind.UNKNOWN,
    ]
    assert members[2] == EntraMember(
        kind=EntraMemberKind.GROUP, id="g1", display_name="Nested"
    )


def test_reads_raise_refusals_as_microsoft_errors() -> None:
    response = requests.Response()
    response.status_code = 404
    response._content = json.dumps({"error": {"code": "itemNotFound"}}).encode()
    context = MagicMock()
    context.web.site_groups.get_by_name.return_value.users.get_all.return_value.execute_query.side_effect = ClientRequestException(
        response=response
    )
    reads = SharepointRestReads(lambda _url: context, MagicMock(), MagicMock())

    with pytest.raises(MicrosoftGraphError) as raised:
        reads.list_site_group_users(site_url=SITE_URL, group_name="Missing")

    assert raised.value.status == 404


def _graph_page(body: dict[str, Any]) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(body).encode()
    return response


def test_nested_groups_are_listed_through_the_group_cast() -> None:
    """Only member groups are requested and every page is read, so a large
    group's users are never paged."""
    parent_id = "11111111-1111-1111-1111-111111111111"
    nested_id = "22222222-2222-2222-2222-222222222222"
    second_id = "33333333-3333-3333-3333-333333333333"
    members_url = (
        "https://graph.microsoft.com/v1.0/groups/"
        f"{parent_id}/members/microsoft.graph.group"
    )
    pages = [
        _graph_page(
            {
                "value": [
                    {"id": nested_id, "displayName": "Platform"},
                    {"id": "nameless"},
                ],
                "@odata.nextLink": f"{members_url}?$skiptoken=next",
            }
        ),
        _graph_page({"value": [{"id": second_id, "displayName": "Infra"}]}),
    ]
    client = GraphClient(lambda: {"access_token": "token", "token_type": "Bearer"})

    with patch(
        "office365.runtime.client_request.requests.get", side_effect=pages
    ) as mock_get:
        groups = read_nested_entra_groups(client, parent_id)

    requested: list[str] = [call.kwargs["url"] for call in mock_get.call_args_list]
    assert requested == [
        f"{members_url}?$select=id,displayName",
        f"{members_url}?$skiptoken=next",
    ]
    assert groups == [
        EntraGroup(id=nested_id, displayName="Platform"),
        EntraGroup(id=second_id, displayName="Infra"),
    ]
