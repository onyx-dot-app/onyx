from collections import deque
from typing import Any

from pydantic import BaseModel

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.microsoft_utils.entra_groups import (
    ResolvedEntraGroup,
    enumerate_entra_groups,
    expand_entra_group,
    extract_guid,
    list_nested_entra_groups,
    normalize_email,
    resolve_entra_group_name,
)
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.microsoft_utils.models import (
    SharepointPrincipal,
    SharepointRoleAssignment,
    SharepointSecurable,
    SharepointSecurableKind,
)
from onyx.connectors.microsoft_utils.sharepoint_rest import (
    SharepointPermissionReader,
)
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
# PnP RoleType defines Guest=1 and RestrictedGuest=9:
# https://github.com/pnp/pnpcore/blob/4e4f58fcac797f2957bfcd14fedcecd690dfe7ee/src/sdk/PnP.Core/Model/SharePoint/Core/Public/Enums/RoleType.cs
LIMITED_ACCESS_ROLE_TYPES = frozenset({1, 9})
PUBLIC_SHARING_LINK_SCOPES = frozenset({"anonymous", "organization"})
_GROUP_PRINCIPAL_TYPES = frozenset(
    {AZURE_AD_GROUP_PRINCIPAL_TYPE, SHAREPOINT_GROUP_PRINCIPAL_TYPE}
)


def _has_only_limited_access(assignment: SharepointRoleAssignment) -> bool:
    return bool(assignment.role_type_kinds) and all(
        kind in LIMITED_ACCESS_ROLE_TYPES for kind in assignment.role_type_kinds
    )


class GroupsResult(BaseModel):
    groups_to_emails: dict[str, set[str]]
    found_public_group: bool


class DocumentGroupsResult(BaseModel):
    group_ids: set[str]
    found_public_group: bool


class _AssignedPrincipals(BaseModel):
    groups: set[SharepointGroup]
    user_emails: set[str]


def _is_public_item(
    reader: SharepointPermissionReader,
    drive_item: DriveItemData,
    treat_sharing_link_as_public: bool = False,
) -> bool:
    if not treat_sharing_link_as_public:
        return False

    try:
        scopes = reader.list_sharing_link_scopes(item=drive_item)
    except Exception as e:
        logger.error("Failed to check if item %s is public: %s", drive_item.id, e)
        return False
    return any(scope in PUBLIC_SHARING_LINK_SCOPES for scope in scopes)


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


def _get_site_scoped_group_name(site_url: str, group_name: str) -> str:
    return f"{site_url.rstrip('/')}{SHAREPOINT_GROUP_SCOPE_SEPARATOR}{group_name}"


def _assigned_group(
    reader: SharepointPermissionReader,
    site_url: str,
    principal: SharepointPrincipal,
) -> SharepointGroup:
    """A group principal, named the way its external group is stored."""
    if principal.principal_type == AZURE_AD_GROUP_PRINCIPAL_TYPE:
        name = resolve_entra_group_name(reader, principal.login_name, principal.title)
    else:
        name = _get_site_scoped_group_name(site_url, principal.title)
    return SharepointGroup(
        login_name=principal.login_name,
        principal_type=principal.principal_type,
        name=name,
    )


def _collect_principals(
    reader: SharepointPermissionReader,
    site_url: str,
    principals: list[SharepointPrincipal],
) -> _AssignedPrincipals:
    groups: set[SharepointGroup] = set()
    user_emails: set[str] = set()
    for principal in principals:
        if principal.principal_type == USER_PRINCIPAL_TYPE:
            if principal.user_principal_name:
                user_emails.add(normalize_email(principal.user_principal_name))
            else:
                logger.warning(
                    "User don't have a user principal name: %s", principal.login_name
                )
        elif principal.principal_type in _GROUP_PRINCIPAL_TYPES:
            groups.add(_assigned_group(reader, site_url, principal))
    return _AssignedPrincipals(groups=groups, user_emails=user_emails)


def _granting_members(
    assignments: list[SharepointRoleAssignment],
) -> list[SharepointPrincipal]:
    """The members of assignments that grant more than Limited Access."""
    members: list[SharepointPrincipal] = []
    for assignment in assignments:
        logger.debug("Assignment: %s", assignment)
        if _has_only_limited_access(assignment):
            logger.info("Skipping Limited Access-only assignment")
            continue
        if assignment.member:
            members.append(assignment.member)
    return members


def _get_sharepoint_groups(
    reader: SharepointPermissionReader, site_url: str, group_name: str
) -> tuple[set[SharepointGroup], set[str]]:
    users = reader.list_site_group_users(site_url=site_url, group_name=group_name)
    principals = _collect_principals(reader, site_url, users)
    return principals.groups, principals.user_emails


def _as_sharepoint_groups(groups: set[ResolvedEntraGroup]) -> set[SharepointGroup]:
    return {
        SharepointGroup(
            login_name=group.id,
            principal_type=AZURE_AD_GROUP_PRINCIPAL_TYPE,
            name=group.name,
        )
        for group in groups
    }


def _get_azuread_groups(
    reader: SharepointPermissionReader, group_name: str
) -> tuple[set[SharepointGroup], set[str]]:
    """Wrap the shared Entra expansion in SharePoint's principal model.

    The permission cache is keyed and serialized on SharepointGroup, so the
    principal type is attached here rather than in the shared code.
    """
    nested, user_emails = expand_entra_group(reader, group_name)
    return _as_sharepoint_groups(nested), user_emails


def _get_nested_azuread_groups(
    reader: SharepointPermissionReader, group_name: str
) -> set[SharepointGroup]:
    """The groups inside an Entra group, without its users. A document's readers
    name groups, not people, so listing every member would be wasted work."""
    return _as_sharepoint_groups(list_nested_entra_groups(reader, group_name))


def _get_groups_and_members_recursively(
    reader: SharepointPermissionReader,
    site_url: str,
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
                reader, site_url, group.login_name
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
                group_info, user_emails = _get_azuread_groups(reader, group.login_name)
                visited_group_name_to_emails[group.name].update(user_emails)
                if group_info:
                    group_queue.extend(group_info)
            except MicrosoftGraphError as e:
                # If the group is not found, we skip it. There is a chance that group is still referenced
                # in sharepoint but it is removed from Azure AD. There is no actual documentation on this, but based on
                # our testing we have seen this happen.
                if e.status == 404:
                    logger.warning("Group %s not found", group.login_name)
                    continue
                raise e

    return GroupsResult(
        groups_to_emails=visited_group_name_to_emails,
        found_public_group=found_public_group,
    )


def _group_cache_key(site_url: str, group: SharepointGroup) -> str:
    identity = group.login_name
    if group.principal_type == SHAREPOINT_GROUP_PRINCIPAL_TYPE:
        identity = _get_site_scoped_group_name(site_url, identity)
    elif guid := extract_guid(identity):
        identity = guid
    return f"{group.principal_type}{GROUP_CACHE_KEY_SEPARATOR}{identity}"


def _get_cached_group_expansion(
    reader: SharepointPermissionReader,
    site_url: str,
    group: SharepointGroup,
    permission_cache: SharepointPermissionCache,
) -> SharepointGroupExpansion:
    cache_key = _group_cache_key(site_url, group)
    cached_expansion = permission_cache.group_expansions.get(cache_key)
    if cached_expansion is not None:
        return cached_expansion

    try:
        if group.principal_type == SHAREPOINT_GROUP_PRINCIPAL_TYPE:
            nested_groups, _ = _get_sharepoint_groups(
                reader, site_url, group.login_name
            )
        else:
            nested_groups = _get_nested_azuread_groups(reader, group.login_name)
    except MicrosoftGraphError as e:
        if group.principal_type != AZURE_AD_GROUP_PRINCIPAL_TYPE or e.status != 404:
            raise
        logger.warning("Group %s not found", group.login_name)
        nested_groups = set()

    expansion = SharepointGroupExpansion(nested_groups=nested_groups)
    permission_cache.group_expansions[cache_key] = expansion
    return expansion


def _resolve_document_groups(
    reader: SharepointPermissionReader,
    site_url: str,
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
        cache_key = _group_cache_key(site_url, group)
        if cache_key in visited_group_keys:
            continue
        visited_group_keys.add(cache_key)

        expansion = _get_cached_group_expansion(
            reader, site_url, group, permission_cache
        )
        group_queue.extend(expansion.nested_groups)

    return DocumentGroupsResult(
        group_ids=group_ids,
        found_public_group=False,
    )


def _get_external_access_from_securable(
    reader: SharepointPermissionReader,
    site_url: str,
    securable: SharepointSecurable,
    permission_cache: SharepointPermissionCache,
    add_prefix: bool = False,
) -> ExternalAccess:
    assignments = reader.list_role_assignments(site_url=site_url, securable=securable)
    principals = _collect_principals(reader, site_url, _granting_members(assignments))

    resolved_groups = _resolve_document_groups(
        reader,
        site_url,
        principals.groups,
        permission_cache,
    )
    if resolved_groups.found_public_group:
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        )

    group_ids: set[str] = set()
    for group_name in resolved_groups.group_ids:
        if add_prefix:
            group_name = build_ext_group_name_for_onyx(
                group_name, DocumentSource.SHAREPOINT
            )
        group_ids.add(group_name.lower())

    logger.info("User emails: %s", len(principals.user_emails))
    logger.info("Group IDs: %s", len(group_ids))
    return ExternalAccess(
        external_user_emails=principals.user_emails,
        external_user_group_ids=group_ids,
        is_public=False,
    )


def get_external_access_from_sharepoint(
    reader: SharepointPermissionReader,
    site_url: str,
    list_id: str | None,
    drive_item: DriveItemData | None,
    site_page: dict[str, Any] | None,
    add_prefix: bool = False,
    treat_sharing_link_as_public: bool = False,
    permission_cache: SharepointPermissionCache | None = None,
) -> ExternalAccess:
    permission_cache = permission_cache or SharepointPermissionCache()
    if drive_item and list_id:
        if _is_public_item(reader, drive_item, treat_sharing_link_as_public):
            logger.info("Item %s is public", drive_item.id)
            return ExternalAccess(
                external_user_emails=set(),
                external_user_group_ids=set(),
                is_public=True,
            )

        item_id = reader.get_list_item_id(item=drive_item)
        if not item_id:
            raise RuntimeError(
                f"Failed to get SharePoint list item ID for item {drive_item.id}"
            )
        securable = SharepointSecurable(
            kind=SharepointSecurableKind.LIST_ITEM, list_id=list_id, item_id=item_id
        )
    elif site_page:
        securable = SharepointSecurable(
            kind=SharepointSecurableKind.PAGE, page_url=site_page.get("webUrl")
        )
    else:
        raise RuntimeError("No drive item or site page provided")

    return _get_external_access_from_securable(
        reader,
        site_url,
        securable,
        permission_cache,
        add_prefix,
    )


def get_hierarchy_node_external_access_from_sharepoint(
    reader: SharepointPermissionReader,
    site_url: str,
    node_type: HierarchyNodeType,
    list_id: str | None,
    folder_server_relative_path: str | None,
    permission_cache: SharepointPermissionCache | None = None,
) -> ExternalAccess:
    """``folder_server_relative_path`` is decoded, e.g. "/sites/eng/RD Docs/API"."""
    permission_cache = permission_cache or SharepointPermissionCache()
    if node_type == HierarchyNodeType.SITE:
        securable = SharepointSecurable(kind=SharepointSecurableKind.SITE)
    elif node_type == HierarchyNodeType.DRIVE and list_id:
        securable = SharepointSecurable(
            kind=SharepointSecurableKind.LIBRARY, list_id=list_id
        )
    elif node_type == HierarchyNodeType.FOLDER and folder_server_relative_path:
        securable = SharepointSecurable(
            kind=SharepointSecurableKind.FOLDER,
            folder_unique_id=reader.get_folder_unique_id(
                site_url=site_url,
                server_relative_path=folder_server_relative_path,
            ),
        )
    else:
        raise ValueError(f"Unsupported SharePoint hierarchy node: {node_type}")

    return _get_external_access_from_securable(
        reader,
        site_url,
        securable,
        permission_cache,
        add_prefix=True,
    )


def get_sharepoint_external_groups(
    reader: SharepointPermissionReader,
    site_url: str,
    enumerate_all_ad_groups: bool = False,
) -> list[ExternalUserGroup]:
    assignments = reader.list_role_assignments(
        site_url=site_url,
        securable=SharepointSecurable(kind=SharepointSecurableKind.SITE),
    )
    groups = {
        _assigned_group(reader, site_url, member)
        for member in _granting_members(assignments)
        if member.principal_type in _GROUP_PRINCIPAL_TYPES
    }
    groups_and_members: GroupsResult = _get_groups_and_members_recursively(
        reader, site_url, groups, is_group_sync=True
    )

    external_user_groups: list[ExternalUserGroup] = [
        ExternalUserGroup(id=group_name, user_emails=list(emails))
        for group_name, emails in groups_and_members.groups_to_emails.items()
    ]

    if not enumerate_all_ad_groups:
        logger.info(
            "Skipping exhaustive Azure AD group enumeration. Only groups found in site role assignments are included."
        )
        return external_user_groups

    already_resolved = set(groups_and_members.groups_to_emails.keys())
    external_user_groups.extend(enumerate_entra_groups(reader, already_resolved))

    return external_user_groups
