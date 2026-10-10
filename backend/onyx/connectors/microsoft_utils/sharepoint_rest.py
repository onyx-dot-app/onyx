"""SharePoint permission reads as plain data.

SharePoint permission sync reads role assignments over SharePoint REST and
expands the Entra groups they name over Graph. The permission logic in EE works
on the models here through :class:`SharepointPermissionReader`, so it never
holds an office365 object. The SharePoint and Teams connectors serve the reader
from the same :class:`SharepointRestReads`.
"""

from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import quote, urlparse

from office365.directory.object import DirectoryObject
from office365.directory.object_collection import DirectoryObjectCollection
from office365.graph_client import GraphClient
from office365.onedrive.permissions.collection import PermissionCollection
from office365.runtime.http.request_options import RequestOptions
from office365.runtime.paths.resource_path import ResourcePath
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.folders.folder import Folder
from office365.sharepoint.permissions.securable_object import (
    RoleAssignmentCollection,
    SecurableObject,
)
from office365.sharepoint.principal.principal import Principal
from office365.sharepoint.principal.users.collection import UserCollection

from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.entra import (
    ENTRA_GROUP_MEMBER_SELECT,
    ENTRA_NAMED_GROUP_SELECT,
    EntraDirectoryObject,
    EntraGroup,
    EntraPage,
    fetch_entra_page,
)
from onyx.connectors.microsoft_utils.graph_client import (
    GraphApiClient,
    sleep_and_retry,
)
from onyx.connectors.microsoft_utils.graph_errors import raise_microsoft_errors
from onyx.connectors.microsoft_utils.models import (
    EntraMember,
    EntraMemberKind,
    SharepointPrincipal,
    SharepointRoleAssignment,
    SharepointSecurable,
    SharepointSecurableKind,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Without an explicit $top, SharePoint can stream every assignment in one chunked
# response, which gateways cut off mid-stream (ChunkedEncodingError). 100 keeps
# pages small without many round trips.
ROLE_ASSIGNMENTS_PAGE_SIZE = 100
_ROLE_ASSIGNMENT_EXPAND = ["Member", "RoleDefinitionBindings"]
# A read collects a whole collection before the permission logic sees it. Past
# this many rows the collection is not a readable ACL, and a partial list would
# grant fewer readers than the source does, so the read fails instead.
MAX_READ_ROWS = 1_000_000
GET_SHAREPOINT_LIST_ITEM_ID_LABEL = "get_sharepoint_list_item_id"


class EntraGroupReader(Protocol):
    """The Graph reads behind Entra group expansion. A refusal raises
    ``MicrosoftGraphError``."""

    def find_entra_group_id(self, *, display_name: str) -> str | None: ...

    def list_entra_group_members(self, *, group_id: str) -> list[EntraMember]: ...

    def list_nested_entra_groups(
        self, *, group_id: str, max_rows: int | None = None
    ) -> list[EntraGroup]: ...

    def list_entra_groups(
        self, *, next_link: str | None = None
    ) -> EntraPage[EntraGroup]: ...

    def list_entra_group_member_page(
        self, *, group_id: str, next_link: str | None = None
    ) -> EntraPage[EntraDirectoryObject]: ...


class SharepointPermissionReader(EntraGroupReader, Protocol):
    """The reads behind SharePoint permission sync."""

    def list_role_assignments(
        self,
        *,
        site_url: str,
        securable: SharepointSecurable,
        max_rows: int | None = None,
    ) -> list[SharepointRoleAssignment]: ...

    def list_site_group_users(
        self, *, site_url: str, group_name: str, max_rows: int | None = None
    ) -> list[SharepointPrincipal]: ...

    def get_folder_unique_id(
        self, *, site_url: str, server_relative_path: str
    ) -> str: ...

    def get_list_item_id(self, *, item: DriveItemData) -> int | None: ...

    def list_sharing_link_scopes(self, *, item: DriveItemData) -> list[str]: ...


def _principal(member: Principal) -> SharepointPrincipal | None:
    """None for a principal SharePoint sent without its type, login or title,
    which names no one the permission logic can match."""
    principal_type: int | None = member.principal_type
    login_name: str | None = member.login_name
    title: str | None = member.title
    if principal_type is None or login_name is None or title is None:
        logger.warning("Skipping incomplete SharePoint principal: %s", member)
        return None
    return SharepointPrincipal(
        principal_type=principal_type,
        login_name=login_name,
        title=title,
        user_principal_name=member.user_principal_name,
    )


def _securable_object(
    context: ClientContext, securable: SharepointSecurable
) -> SecurableObject:
    web = context.web
    if securable.kind == SharepointSecurableKind.SITE:
        return web
    if securable.kind == SharepointSecurableKind.LIBRARY and securable.list_id:
        return web.lists.get_by_id(securable.list_id)
    if (
        securable.kind == SharepointSecurableKind.LIST_ITEM
        and securable.list_id
        and securable.item_id is not None
    ):
        return web.lists.get_by_id(securable.list_id).items.get_by_id(securable.item_id)
    if securable.kind == SharepointSecurableKind.PAGE and securable.page_url:
        # Keep the percent-encoding: the SDK compares the path with the encoded
        # site path, and a decoded path (%27 as ') duplicates the site prefix.
        server_relative_url = urlparse(securable.page_url).path
        return web.get_file_by_server_relative_url(
            server_relative_url
        ).listItemAllFields
    if securable.kind == SharepointSecurableKind.FOLDER and securable.folder_unique_id:
        return web.get_folder_by_id(securable.folder_unique_id).list_item_all_fields
    raise ValueError(f"Incomplete SharePoint securable: {securable}")


def _check_read_size(rows: list[Any], label: str) -> None:
    if len(rows) > MAX_READ_ROWS:
        raise RuntimeError(f"{label} exceeds {MAX_READ_ROWS} rows.")


def read_role_assignments(
    context: ClientContext,
    securable: SharepointSecurable,
    max_rows: int | None = None,
) -> list[SharepointRoleAssignment]:
    """Every assignment, or with ``max_rows`` one page of at most that many,
    for a probe that must not walk a large permission list."""
    assignments: list[SharepointRoleAssignment] = []

    def collect(page: RoleAssignmentCollection) -> None:
        # Iterate current_page, not the collection: iterating the collection
        # walks pages through _get_next().execute_query(), which fires this
        # callback again and recurses until Python's limit.
        for assignment in page.current_page:
            bindings = assignment.role_definition_bindings or []
            assignments.append(
                SharepointRoleAssignment(
                    member=_principal(assignment.member) if assignment.member else None,
                    role_type_kinds=[
                        kind
                        for binding in bindings
                        if (kind := binding.role_type_kind) is not None
                    ],
                )
            )
        _check_read_size(assignments, "Role assignments")

    role_assignments = _securable_object(context, securable).role_assignments.expand(
        _ROLE_ASSIGNMENT_EXPAND
    )
    if max_rows is not None:
        page: RoleAssignmentCollection = sleep_and_retry(
            role_assignments.top(max_rows).get(), "list_role_assignments"
        )
        collect(page)
        return assignments
    sleep_and_retry(
        role_assignments.get_all(
            page_size=ROLE_ASSIGNMENTS_PAGE_SIZE, page_loaded=collect
        ),
        "list_role_assignments",
    )
    return assignments


def read_site_group_users(
    context: ClientContext, group_name: str, max_rows: int | None = None
) -> list[SharepointPrincipal]:
    """Every member, or with ``max_rows`` one page of at most that many, for
    a probe that must not walk a large group."""
    users: list[SharepointPrincipal] = []

    def collect(page: UserCollection) -> None:
        # Iterating the collection re-fires this callback and recurses.
        for user in page.current_page:
            logger.debug("User: %s", user.to_json())
            if principal := _principal(user):
                users.append(principal)
        _check_read_size(users, f"Site group `{group_name}`")

    group = context.web.site_groups.get_by_name(group_name)
    if max_rows is not None:
        page: UserCollection = sleep_and_retry(
            group.users.top(max_rows).get(), "list_site_group_users"
        )
        collect(page)
        return users
    sleep_and_retry(group.users.get_all(page_loaded=collect), "list_site_group_users")
    return users


def read_folder_unique_id(context: ClientContext, server_relative_path: str) -> str:
    """Look up a folder by its decoded server-relative path, e.g.
    "/sites/eng/RD Docs/API", and return its GUID.

    The path goes in an OData parameter alias in the query string. SharePoint
    answers 401 when an inline path makes the URL path too long, which happens
    for folder paths of about 290 characters. The by-path lookup also accepts
    "%" and "#", which the by-URL lookup rejects.
    """
    odata_literal = "'" + server_relative_path.replace("'", "''") + "'"
    alias_param = f"@a={quote(odata_literal, safe='')}"

    def add_alias(request: RequestOptions) -> None:
        separator = "&" if "?" in request.url else "?"
        request.url = f"{request.url}{separator}{alias_param}"

    # Returns the SDK's untyped query object, like the other sleep_and_retry callers.
    def build_query() -> Any:
        folder = Folder(
            context,
            ResourcePath(
                "getFolderByServerRelativePath(DecodedUrl=@a)",
                context.web.resource_path,
            ),
        )
        context.before_execute(add_alias)
        return folder.select(["UniqueId"]).get()

    folder: Folder = sleep_and_retry(
        build_query(), "get_folder_unique_id", rebuild=build_query
    )
    if not folder.unique_id:
        raise RuntimeError(
            f"Failed to get SharePoint folder ID for {server_relative_path}"
        )
    return folder.unique_id


def read_list_item_id(graph_client: GraphClient, item: DriveItemData) -> int | None:
    """The item's id in its SharePoint list. The delta and children listings
    usually carry it, so Graph is asked only when they did not."""
    if item.list_item_id:
        return int(item.list_item_id)
    list_item = item.to_sdk_driveitem(graph_client).listItem
    sleep_and_retry(list_item.get(), GET_SHAREPOINT_LIST_ITEM_ID_LABEL)
    return int(list_item.id) if list_item.id else None


def read_sharing_link_scopes(
    graph_client: GraphClient, item: DriveItemData
) -> list[str]:
    scopes: list[str] = []

    def collect(page: PermissionCollection) -> None:
        # Iterating the collection re-fires this callback and recurses.
        scopes.extend(
            permission.link.scope
            for permission in page.current_page
            if permission.link and permission.link.scope
        )
        _check_read_size(scopes, f"Sharing links of `{item.id}`")

    sleep_and_retry(
        item.to_sdk_driveitem(graph_client).permissions.get_all(page_loaded=collect),
        "list_sharing_link_scopes",
    )
    return scopes


def find_entra_group_id(graph_client: GraphClient, display_name: str) -> str | None:
    groups = sleep_and_retry(
        graph_client.groups.filter(f"displayName eq '{display_name}'").get(),
        "find_group_id_by_name",
    )
    return groups[0].id if groups and len(groups) > 0 else None


def _entra_member(member: DirectoryObject) -> EntraMember:
    """Classify the SDK's untyped directory object. Users carry a principal name
    or a mail address, groups a display name without one."""
    member_data: dict[str, Any] = member.to_json()
    user_principal_name: str | None = member_data.get("userPrincipalName")
    mail: str | None = member_data.get("mail")
    display_name: str | None = member_data.get("displayName") or member_data.get(
        "display_name"
    )

    kind: EntraMemberKind = EntraMemberKind.UNKNOWN
    if user_principal_name or (mail and "@" in str(mail)):
        kind = EntraMemberKind.USER
    elif display_name and (
        member_data.get("groupTypes") is not None or member_data.get("id")
    ):
        kind = EntraMemberKind.GROUP
    else:
        type_name: str = type(member).__name__.lower()
        if "user" in type_name:
            kind = EntraMemberKind.USER
        elif "group" in type_name:
            kind = EntraMemberKind.GROUP

    return EntraMember(
        kind=kind,
        id=member_data.get("id") or "",
        display_name=display_name,
        user_principal_name=user_principal_name,
        mail=mail,
    )


def read_entra_group_members(
    graph_client: GraphClient, group_id: str
) -> list[EntraMember]:
    members: list[EntraMember] = []

    def collect(page: DirectoryObjectCollection) -> None:
        # Iterating the collection re-fires this callback and recurses.
        for member in page.current_page:
            logger.debug("Member: %s", member.to_json())
            members.append(_entra_member(member))
        _check_read_size(members, f"Entra group `{group_id}` members")

    sleep_and_retry(
        graph_client.groups[group_id].members.get_all(page_loaded=collect),
        "expand_entra_group",
    )
    return members


def read_nested_entra_groups(
    graph_client: GraphClient, group_id: str, max_rows: int | None = None
) -> list[EntraGroup]:
    """One group's direct member groups, or with ``max_rows`` one page of at
    most that many. Graph filters to groups server side, so a group of
    thousands of users costs one page instead of every member."""
    groups: list[EntraGroup] = []

    def collect(page: DirectoryObjectCollection) -> None:
        # Iterating the collection re-fires this callback and recurses.
        for member in page.current_page:
            member_data = member.to_json()
            if not member_data.get("id") or not member_data.get("displayName"):
                logger.error("Nested group without an id or name: %s", member_data)
                continue
            groups.append(EntraGroup.model_validate(member_data))
        _check_read_size(groups, f"Entra group `{group_id}` nested groups")

    member_groups = DirectoryObjectCollection(
        graph_client,
        ResourcePath(
            "microsoft.graph.group", graph_client.groups[group_id].members.resource_path
        ),
    )
    selected = member_groups.select(["id", "displayName"])
    if max_rows is not None:
        page: DirectoryObjectCollection = sleep_and_retry(
            selected.top(max_rows).get(), "list_nested_entra_groups"
        )
        collect(page)
        return groups
    sleep_and_retry(selected.get_all(page_loaded=collect), "list_nested_entra_groups")
    return groups


class SharepointRestReads(SharepointPermissionReader):
    """Serves :class:`SharepointPermissionReader` from a REST context per site
    and a Graph client."""

    def __init__(
        self,
        rest_context: Callable[[str], ClientContext],
        graph_client: GraphClient,
        graph_api: GraphApiClient,
    ) -> None:
        self._rest_context = rest_context
        self._graph_client = graph_client
        self._graph_api = graph_api

    def list_role_assignments(
        self,
        *,
        site_url: str,
        securable: SharepointSecurable,
        max_rows: int | None = None,
    ) -> list[SharepointRoleAssignment]:
        with raise_microsoft_errors():
            return read_role_assignments(
                self._rest_context(site_url), securable, max_rows
            )

    def list_site_group_users(
        self, *, site_url: str, group_name: str, max_rows: int | None = None
    ) -> list[SharepointPrincipal]:
        with raise_microsoft_errors():
            return read_site_group_users(
                self._rest_context(site_url), group_name, max_rows
            )

    def get_folder_unique_id(self, *, site_url: str, server_relative_path: str) -> str:
        with raise_microsoft_errors():
            return read_folder_unique_id(
                self._rest_context(site_url), server_relative_path
            )

    def get_list_item_id(self, *, item: DriveItemData) -> int | None:
        with raise_microsoft_errors():
            return read_list_item_id(self._graph_client, item)

    def list_sharing_link_scopes(self, *, item: DriveItemData) -> list[str]:
        with raise_microsoft_errors():
            return read_sharing_link_scopes(self._graph_client, item)

    def find_entra_group_id(self, *, display_name: str) -> str | None:
        with raise_microsoft_errors():
            return find_entra_group_id(self._graph_client, display_name)

    def list_entra_group_members(self, *, group_id: str) -> list[EntraMember]:
        with raise_microsoft_errors():
            return read_entra_group_members(self._graph_client, group_id)

    def list_nested_entra_groups(
        self, *, group_id: str, max_rows: int | None = None
    ) -> list[EntraGroup]:
        with raise_microsoft_errors():
            return read_nested_entra_groups(self._graph_client, group_id, max_rows)

    def list_entra_groups(
        self, *, next_link: str | None = None
    ) -> EntraPage[EntraGroup]:
        with raise_microsoft_errors():
            return fetch_entra_page(
                self._graph_api.get_json,
                url=f"{self._graph_api.graph_api_base}/groups",
                item_model=EntraGroup,
                select_fields=ENTRA_NAMED_GROUP_SELECT,
                next_link=next_link,
            )

    def list_entra_group_member_page(
        self, *, group_id: str, next_link: str | None = None
    ) -> EntraPage[EntraDirectoryObject]:
        with raise_microsoft_errors():
            return fetch_entra_page(
                self._graph_api.get_json,
                url=f"{self._graph_api.graph_api_base}/groups/{quote(group_id)}/members",
                item_model=EntraDirectoryObject,
                select_fields=ENTRA_GROUP_MEMBER_SELECT,
                next_link=next_link,
            )
