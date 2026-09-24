from collections import deque
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from office365.graph_client import GraphClient
from office365.onedrive.driveitems.driveItem import DriveItem
from office365.runtime.client_request import ClientRequestException
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.permissions.roles.definitions.definition import RoleDefinition
from office365.sharepoint.permissions.securable_object import (
    RoleAssignmentCollection,
    SecurableObject,
)
from office365.sharepoint.principal.users.collection import UserCollection
from pydantic import BaseModel

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.microsoft_utils.entra_groups import (
    enumerate_entra_groups,
    expand_entra_group,
    extract_guid,
    normalize_email,
    resolve_entra_group_name,
)
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.microsoft_utils.drive_items import (
    LIST_ITEM_ID_PROPERTY,
    SHAREPOINT_IDS_PROPERTY,
)
from onyx.connectors.microsoft_utils.graph_client import (
    GraphApiClient,
    sleep_and_retry,
)
from onyx.connectors.sharepoint.connector import SHARED_DOCUMENTS_MAP_REVERSE
from onyx.connectors.sharepoint.connector_utils import (
    SharepointGroup,
    SharepointGroupExpansion,
    SharepointPermissionCache,
)
from onyx.db.enums import HierarchyNodeType
from onyx.utils.logger import setup_logger

logger = setup_logger()


# These values represent different types of SharePoint principals used in permission assignments
USER_PRINCIPAL_TYPE = 1  # Individual user accounts
ANONYMOUS_USER_PRINCIPAL_TYPE = 3  # Anonymous/unauthenticated users (public access)
AZURE_AD_GROUP_PRINCIPAL_TYPE = 4  # Azure Active Directory security groups
SHAREPOINT_GROUP_PRINCIPAL_TYPE = 8  # SharePoint site groups (local to the site)
SHAREPOINT_GROUP_SCOPE_SEPARATOR = "::"
GROUP_CACHE_KEY_SEPARATOR = ":"
GET_SHAREPOINT_LIST_ITEM_ID_LABEL = "get_sharepoint_list_item_id"
# PnP RoleType defines Guest=1 and RestrictedGuest=9:
# https://github.com/pnp/pnpcore/blob/4e4f58fcac797f2957bfcd14fedcecd690dfe7ee/src/sdk/PnP.Core/Model/SharePoint/Core/Public/Enums/RoleType.cs
LIMITED_ACCESS_ROLE_TYPES = frozenset({1, 9})


# Page size for SharePoint REST RoleAssignments queries with
# $expand=Member,RoleDefinitionBindings. Without an explicit $top, SharePoint
# can stream the entire collection in one chunked response which has been
# observed to be terminated mid-stream by upstream gateways
# (ChunkedEncodingError: Response ended prematurely) on items with many
# assignments. 100 matches Microsoft Graph / SharePoint UI defaults for
# paged collections and keeps each page well under typical proxy buffer
# limits while not making the round-trip count overwhelming.
ROLE_ASSIGNMENTS_PAGE_SIZE = 100


def _has_only_limited_access(
    role_definition_bindings: Iterable[RoleDefinition],
) -> bool:
    return all(
        binding.role_type_kind in LIMITED_ACCESS_ROLE_TYPES
        for binding in role_definition_bindings
    )


class GroupsResult(BaseModel):
    groups_to_emails: dict[str, set[str]]
    found_public_group: bool


class DocumentGroupsResult(BaseModel):
    group_ids: set[str]
    found_public_group: bool


def _get_sharepoint_list_item_id(drive_item: DriveItem) -> str | None:
    try:
        properties = getattr(drive_item, "properties", None)  # ods: ignore[getattr]
        sharepoint_ids = properties.get(SHAREPOINT_IDS_PROPERTY) if properties else None
        if isinstance(sharepoint_ids, dict):
            if list_item_id := sharepoint_ids.get(LIST_ITEM_ID_PROPERTY):
                return str(list_item_id)

        if hasattr(drive_item, "listItem"):
            list_item = drive_item.listItem
            if list_item:
                sleep_and_retry(list_item.get(), GET_SHAREPOINT_LIST_ITEM_ID_LABEL)
                if hasattr(list_item, "id") and list_item.id:
                    return str(list_item.id)

        if properties:
            for prop_name, prop_value in properties.items():
                if "listitemid" in prop_name.lower():
                    return str(prop_value)

        return None
    except Exception as e:
        logger.error(
            "Error getting SharePoint list item ID for item %s: %s", drive_item.id, e
        )
        raise e


def _is_public_item(
    drive_item: DriveItem,
    treat_sharing_link_as_public: bool = False,
) -> bool:
    if not treat_sharing_link_as_public:
        return False

    try:
        permissions = sleep_and_retry(
            drive_item.permissions.get_all(page_loaded=lambda _: None), "is_public_item"
        )
        for permission in permissions:
            if permission.link and permission.link.scope in (
                "anonymous",
                "organization",
            ):
                return True
        return False
    except Exception as e:
        logger.error("Failed to check if item %s is public: %s", drive_item.id, e)
        return False


def _is_public_login_name(login_name: str) -> bool:
    # Patterns that indicate public access
    # This list is derived from the below link
    # https://learn.microsoft.com/en-us/answers/questions/2085339/guid-in-the-loginname-of-site-user-everyone-except
    public_login_patterns: list[str] = [
        "c:0-.f|rolemanager|spo-grid-all-users/",
        "c:0(.s|true",
    ]
    for pattern in public_login_patterns:
        if pattern in login_name:
            logger.info("Login name %s is public", login_name)
            return True
    return False


def _get_site_scoped_group_name(
    client_context: ClientContext,
    group_name: str,
) -> str:
    site_url = client_context.base_url.rstrip("/")
    return f"{site_url}{SHAREPOINT_GROUP_SCOPE_SEPARATOR}{group_name}"


def _get_sharepoint_groups(
    client_context: ClientContext, group_name: str, graph_client: GraphClient
) -> tuple[set[SharepointGroup], set[str]]:
    groups: set[SharepointGroup] = set()
    user_emails: set[str] = set()

    def process_users(users: UserCollection) -> None:
        nonlocal groups, user_emails

        # iterate `current_page` (the items just loaded by this page) instead of
        # `users` directly: iterating the collection itself walks pages via
        # `_get_next().execute_query()`, which re-fires this `page_loaded` callback
        # and recurses until Python hits its max recursion depth.
        for user in users.current_page:
            logger.debug("User: %s", user.to_json())
            if user.principal_type == USER_PRINCIPAL_TYPE and hasattr(
                user, "user_principal_name"
            ):
                if user.user_principal_name:
                    email = user.user_principal_name
                    email = normalize_email(email)
                    user_emails.add(email)
                else:
                    logger.warning(
                        "User don't have a user principal name: %s", user.login_name
                    )
            elif user.principal_type in [
                AZURE_AD_GROUP_PRINCIPAL_TYPE,
                SHAREPOINT_GROUP_PRINCIPAL_TYPE,
            ]:
                name = user.title
                if user.principal_type == AZURE_AD_GROUP_PRINCIPAL_TYPE:
                    name = resolve_entra_group_name(graph_client, user.login_name, name)
                else:
                    name = _get_site_scoped_group_name(client_context, name)
                groups.add(
                    SharepointGroup(
                        login_name=user.login_name,
                        principal_type=user.principal_type,
                        name=name,
                    )
                )

    group = client_context.web.site_groups.get_by_name(group_name)
    sleep_and_retry(
        group.users.get_all(page_loaded=process_users), "get_sharepoint_groups"
    )

    return groups, user_emails


def _get_azuread_groups(
    graph_client: GraphClient, group_name: str
) -> tuple[set[SharepointGroup], set[str]]:
    """Wrap the shared Entra expansion in SharePoint's principal model.

    The permission cache is keyed and serialized on SharepointGroup, so the
    principal type is attached here rather than in the shared code.
    """
    nested, user_emails = expand_entra_group(graph_client, group_name)
    groups = {
        SharepointGroup(
            login_name=group.id,
            principal_type=AZURE_AD_GROUP_PRINCIPAL_TYPE,
            name=group.name,
        )
        for group in nested
    }
    return groups, user_emails


def _get_groups_and_members_recursively(
    client_context: ClientContext,
    graph_client: GraphClient,
    groups: set[SharepointGroup],
    is_group_sync: bool = False,
) -> GroupsResult:
    """
    Get all groups and their members recursively.
    """
    group_queue: deque[SharepointGroup] = deque(groups)
    visited_groups: set[str] = set()
    visited_group_name_to_emails: dict[str, set[str]] = {}
    found_public_group = False
    while group_queue:
        group = group_queue.popleft()
        if group.login_name in visited_groups:
            continue
        visited_groups.add(group.login_name)
        visited_group_name_to_emails[group.name] = set()
        logger.info(
            "Processing group: %s principal type: %s", group.name, group.principal_type
        )
        if group.principal_type == SHAREPOINT_GROUP_PRINCIPAL_TYPE:
            group_info, user_emails = _get_sharepoint_groups(
                client_context, group.login_name, graph_client
            )
            visited_group_name_to_emails[group.name].update(user_emails)
            if group_info:
                group_queue.extend(group_info)
        if group.principal_type == AZURE_AD_GROUP_PRINCIPAL_TYPE:
            try:
                # if the site is public, we have default groups assigned to it, so we return early
                if _is_public_login_name(group.login_name):
                    found_public_group = True
                    if not is_group_sync:
                        return GroupsResult(
                            groups_to_emails={}, found_public_group=True
                        )
                    else:
                        # we don't want to sync public groups, so we skip them
                        continue
                group_info, user_emails = _get_azuread_groups(
                    graph_client, group.login_name
                )
                visited_group_name_to_emails[group.name].update(user_emails)
                if group_info:
                    group_queue.extend(group_info)
            except ClientRequestException as e:
                # If the group is not found, we skip it. There is a chance that group is still referenced
                # in sharepoint but it is removed from Azure AD. There is no actual documentation on this, but based on
                # our testing we have seen this happen.
                if e.response is not None and e.response.status_code == 404:
                    logger.warning("Group %s not found", group.login_name)
                    continue
                raise e

    return GroupsResult(
        groups_to_emails=visited_group_name_to_emails,
        found_public_group=found_public_group,
    )


def _group_cache_key(
    client_context: ClientContext,
    group: SharepointGroup,
) -> str:
    identity = group.login_name
    if group.principal_type == SHAREPOINT_GROUP_PRINCIPAL_TYPE:
        identity = _get_site_scoped_group_name(client_context, identity)
    elif guid := extract_guid(identity):
        identity = guid
    return f"{group.principal_type}{GROUP_CACHE_KEY_SEPARATOR}{identity}"


def _get_cached_group_expansion(
    client_context: ClientContext,
    graph_client: GraphClient,
    group: SharepointGroup,
    permission_cache: SharepointPermissionCache,
) -> SharepointGroupExpansion:
    cache_key = _group_cache_key(client_context, group)
    cached_expansion = permission_cache.group_expansions.get(cache_key)
    if cached_expansion is not None:
        return cached_expansion

    try:
        if group.principal_type == SHAREPOINT_GROUP_PRINCIPAL_TYPE:
            nested_groups, _ = _get_sharepoint_groups(
                client_context, group.login_name, graph_client
            )
        else:
            nested_groups, _ = _get_azuread_groups(graph_client, group.login_name)
    except ClientRequestException as e:
        if (
            group.principal_type != AZURE_AD_GROUP_PRINCIPAL_TYPE
            or e.response is None
            or e.response.status_code != 404
        ):
            raise
        logger.warning("Group %s not found", group.login_name)
        nested_groups = set()

    expansion = SharepointGroupExpansion(nested_groups=nested_groups)
    permission_cache.group_expansions[cache_key] = expansion
    return expansion


def _resolve_document_groups(
    client_context: ClientContext,
    graph_client: GraphClient,
    groups: set[SharepointGroup],
    permission_cache: SharepointPermissionCache,
) -> DocumentGroupsResult:
    group_queue: deque[SharepointGroup] = deque(groups)
    visited_group_keys: set[str] = set()
    group_ids: set[str] = set()

    while group_queue:
        group = group_queue.popleft()
        if _is_public_login_name(group.login_name):
            return DocumentGroupsResult(group_ids=set(), found_public_group=True)

        group_ids.add(group.name)
        cache_key = _group_cache_key(client_context, group)
        if cache_key in visited_group_keys:
            continue
        visited_group_keys.add(cache_key)

        expansion = _get_cached_group_expansion(
            client_context, graph_client, group, permission_cache
        )
        group_queue.extend(expansion.nested_groups)

    return DocumentGroupsResult(
        group_ids=group_ids,
        found_public_group=False,
    )


def _get_external_access_from_securable_object(
    client_context: ClientContext,
    graph_client: GraphClient,
    securable_object: SecurableObject,
    permission_cache: SharepointPermissionCache,
    add_prefix: bool = False,
) -> ExternalAccess:
    groups: set[SharepointGroup] = set()
    user_emails: set[str] = set()
    group_ids: set[str] = set()

    def add_user_and_group_to_sets(
        role_assignments: RoleAssignmentCollection,
    ) -> None:
        nonlocal user_emails, groups
        # iterate `current_page` (the items just loaded by this page) instead of
        # `role_assignments` directly: iterating the collection itself walks pages
        # via `_get_next().execute_query()`, which re-fires this `page_loaded`
        # callback and recurses until Python hits its max recursion depth.
        for assignment in role_assignments.current_page:
            logger.debug("Assignment: %s", assignment.to_json())
            if assignment.role_definition_bindings and _has_only_limited_access(
                assignment.role_definition_bindings
            ):
                logger.info("Skipping Limited Access-only assignment")
                continue
            if assignment.member:
                member = assignment.member
                if member.principal_type == USER_PRINCIPAL_TYPE and hasattr(
                    member, "user_principal_name"
                ):
                    email = member.user_principal_name
                    email = normalize_email(email)
                    user_emails.add(email)
                elif member.principal_type in [
                    AZURE_AD_GROUP_PRINCIPAL_TYPE,
                    SHAREPOINT_GROUP_PRINCIPAL_TYPE,
                ]:
                    name = member.title
                    if member.principal_type == AZURE_AD_GROUP_PRINCIPAL_TYPE:
                        name = resolve_entra_group_name(
                            graph_client, member.login_name, name
                        )
                    else:
                        name = _get_site_scoped_group_name(client_context, name)
                    groups.add(
                        SharepointGroup(
                            login_name=member.login_name,
                            principal_type=member.principal_type,
                            name=name,
                        )
                    )

    sleep_and_retry(
        securable_object.role_assignments.expand(
            ["Member", "RoleDefinitionBindings"]
        ).get_all(
            page_size=ROLE_ASSIGNMENTS_PAGE_SIZE,
            page_loaded=add_user_and_group_to_sets,
        ),
        "get_external_access_from_sharepoint",
    )

    resolved_groups = _resolve_document_groups(
        client_context,
        graph_client,
        groups,
        permission_cache,
    )
    if resolved_groups.found_public_group:
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        )

    for group_name in resolved_groups.group_ids:
        if add_prefix:
            group_name = build_ext_group_name_for_onyx(
                group_name, DocumentSource.SHAREPOINT
            )
        group_ids.add(group_name.lower())

    logger.info("User emails: %s", len(user_emails))
    logger.info("Group IDs: %s", len(group_ids))
    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_ids,
        is_public=False,
    )


def get_external_access_from_sharepoint(
    client_context: ClientContext,
    graph_client: GraphClient,
    drive_name: str | None,
    drive_item: DriveItem | None,
    site_page: dict[str, Any] | None,
    add_prefix: bool = False,
    treat_sharing_link_as_public: bool = False,
    permission_cache: SharepointPermissionCache | None = None,
) -> ExternalAccess:
    permission_cache = permission_cache or SharepointPermissionCache()
    if drive_item and drive_name:
        is_public = _is_public_item(drive_item, treat_sharing_link_as_public)
        if is_public:
            logger.info("Item %s is public", drive_item.id)
            return ExternalAccess(
                external_user_emails=set(),
                external_user_group_ids=set(),
                is_public=True,
            )

        item_id = _get_sharepoint_list_item_id(drive_item)

        if not item_id:
            raise RuntimeError(
                f"Failed to get SharePoint list item ID for item {drive_item.id}"
            )

        if drive_name in SHARED_DOCUMENTS_MAP_REVERSE:
            drive_name = SHARED_DOCUMENTS_MAP_REVERSE[drive_name]

        item = client_context.web.lists.get_by_title(drive_name).items.get_by_id(
            item_id
        )
    elif site_page:
        site_url = site_page.get("webUrl")
        # Keep percent-encoding intact so the path matches the encoding
        # used by the Office365 library's SPResPath.create_relative(),
        # which compares against urlparse(context.base_url).path.
        # Decoding (e.g. %27 → ') causes a mismatch that duplicates
        # the site prefix in the constructed URL.
        server_relative_url = urlparse(site_url).path
        file_obj = client_context.web.get_file_by_server_relative_url(
            server_relative_url
        )
        item = file_obj.listItemAllFields
    else:
        raise RuntimeError("No drive item or site page provided")

    return _get_external_access_from_securable_object(
        client_context,
        graph_client,
        item,
        permission_cache,
        add_prefix,
    )


def get_hierarchy_node_external_access_from_sharepoint(
    client_context: ClientContext,
    graph_client: GraphClient,
    node_type: HierarchyNodeType,
    drive_name: str | None,
    folder_server_relative_path: str | None,
    permission_cache: SharepointPermissionCache | None = None,
) -> ExternalAccess:
    """``folder_server_relative_path`` is decoded, e.g. "/sites/eng/RD Docs/API".

    The by-path lookup is used because the by-URL one rejects "%" and "#".
    """
    permission_cache = permission_cache or SharepointPermissionCache()
    if node_type == HierarchyNodeType.SITE:
        securable_object = client_context.web
    elif node_type == HierarchyNodeType.DRIVE and drive_name:
        list_name = SHARED_DOCUMENTS_MAP_REVERSE.get(drive_name, drive_name)
        securable_object = client_context.web.lists.get_by_title(list_name)
    elif node_type == HierarchyNodeType.FOLDER and folder_server_relative_path:
        securable_object = client_context.web.get_folder_by_server_relative_path(
            folder_server_relative_path
        ).list_item_all_fields
    else:
        raise ValueError(f"Unsupported SharePoint hierarchy node: {node_type}")

    return _get_external_access_from_securable_object(
        client_context,
        graph_client,
        securable_object,
        permission_cache,
        add_prefix=True,
    )


def get_sharepoint_external_groups(
    client_context: ClientContext,
    graph_client: GraphClient,
    graph_api: GraphApiClient | None = None,
    enumerate_all_ad_groups: bool = False,
) -> list[ExternalUserGroup]:
    groups: set[SharepointGroup] = set()

    def add_group_to_sets(role_assignments: RoleAssignmentCollection) -> None:
        nonlocal groups
        # iterate `current_page` (the items just loaded by this page) instead of
        # `role_assignments` directly: iterating the collection itself walks pages
        # via `_get_next().execute_query()`, which re-fires this `page_loaded`
        # callback and recurses until Python hits its max recursion depth.
        for assignment in role_assignments.current_page:
            if assignment.role_definition_bindings and _has_only_limited_access(
                assignment.role_definition_bindings
            ):
                logger.info("Skipping Limited Access-only assignment")
                continue
            if assignment.member:
                member = assignment.member
                if member.principal_type in [
                    AZURE_AD_GROUP_PRINCIPAL_TYPE,
                    SHAREPOINT_GROUP_PRINCIPAL_TYPE,
                ]:
                    name = member.title
                    if member.principal_type == AZURE_AD_GROUP_PRINCIPAL_TYPE:
                        name = resolve_entra_group_name(
                            graph_client, member.login_name, name
                        )
                    else:
                        name = _get_site_scoped_group_name(client_context, name)

                    groups.add(
                        SharepointGroup(
                            login_name=member.login_name,
                            principal_type=member.principal_type,
                            name=name,
                        )
                    )

    sleep_and_retry(
        client_context.web.role_assignments.expand(
            ["Member", "RoleDefinitionBindings"]
        ).get_all(page_size=ROLE_ASSIGNMENTS_PAGE_SIZE, page_loaded=add_group_to_sets),
        "get_sharepoint_external_groups",
    )
    groups_and_members: GroupsResult = _get_groups_and_members_recursively(
        client_context, graph_client, groups, is_group_sync=True
    )

    external_user_groups: list[ExternalUserGroup] = [
        ExternalUserGroup(id=group_name, user_emails=list(emails))
        for group_name, emails in groups_and_members.groups_to_emails.items()
    ]

    if not enumerate_all_ad_groups or graph_api is None:
        logger.info(
            "Skipping exhaustive Azure AD group enumeration. Only groups found in site role assignments are included."
        )
        return external_user_groups

    already_resolved = set(groups_and_members.groups_to_emails.keys())
    external_user_groups.extend(enumerate_entra_groups(graph_api, already_resolved))

    return external_user_groups
