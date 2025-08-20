import re
from collections import deque
from typing import Any
from urllib.parse import unquote
from urllib.parse import urlparse

from office365.graph_client import GraphClient  # type: ignore[import-untyped]
from office365.onedrive.driveitems.driveItem import DriveItem  # type: ignore[import-untyped]
from office365.runtime.client_request import ClientRequestException  # type: ignore
from office365.sharepoint.client_context import ClientContext  # type: ignore[import-untyped]
from office365.sharepoint.permissions.securable_object import RoleAssignmentCollection  # type: ignore[import-untyped]
from pydantic import BaseModel

from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.sharepoint.connector import sleep_and_retry
from onyx.utils.logger import setup_logger

logger = setup_logger()


# These values represent different types of SharePoint principals used in permission assignments
USER_PRINCIPAL_TYPE = 1  # Individual user accounts
ANONYMOUS_USER_PRINCIPAL_TYPE = 3  # Anonymous/unauthenticated users (public access)
AZURE_AD_GROUP_PRINCIPAL_TYPE = 4  # Azure Active Directory security groups
SHAREPOINT_GROUP_PRINCIPAL_TYPE = 8  # SharePoint site groups (local to the site)
MICROSOFT_DOMAIN = ".onmicrosoft"
# Limited Access role type, limited access is a travel through permission not a actual permission
LIMITED_ACCESS_ROLE_TYPES = [1, 9]
LIMITED_ACCESS_ROLE_NAMES = ["Limited Access", "Web-Only Limited Access"]


class SharepointGroup(BaseModel):
    model_config = {"frozen": True}

    name: str
    login_name: str
    principal_type: int


class GroupsResult(BaseModel):
    groups_to_emails: dict[str, set[str]]
    found_public_group: bool


def _get_azuread_group_guid_by_name(
    graph_client: GraphClient, group_name: str
) -> str | None:
    try:
        # Search for groups by display name
        groups = sleep_and_retry(
            graph_client.groups.filter(f"displayName eq '{group_name}'").get(),
            "get_azuread_group_guid_by_name",
        )

        if groups and len(groups) > 0:
            return groups[0].id

        return None

    except Exception as e:
        logger.error(f"Failed to get Azure AD group GUID for name {group_name}: {e}")
        return None


def _extract_guid_from_claims_token(claims_token: str) -> str | None:

    try:
        # Pattern to match GUID in claims token
        # Claims tokens often have format: c:0o.c|provider|GUID_suffix
        guid_pattern = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"

        match = re.search(guid_pattern, claims_token, re.IGNORECASE)
        if match:
            return match.group(1)

        return None

    except Exception as e:
        logger.error(f"Failed to extract GUID from claims token {claims_token}: {e}")
        return None


def _get_group_guid_from_identifier(
    graph_client: GraphClient, identifier: str
) -> str | None:
    try:
        # Check if it's already a GUID
        guid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        if re.match(guid_pattern, identifier, re.IGNORECASE):
            return identifier

        # Check if it's a SharePoint claims token
        if identifier.startswith("c:0") and "|" in identifier:
            guid = _extract_guid_from_claims_token(identifier)
            if guid:
                logger.info(f"Extracted GUID {guid} from claims token {identifier}")
                return guid

        # Try to search by display name as fallback
        return _get_azuread_group_guid_by_name(graph_client, identifier)

    except Exception as e:
        logger.error(f"Failed to get group GUID from identifier {identifier}: {e}")
        return None


def _get_security_group_owners(graph_client: GraphClient, group_id: str) -> list[str]:
    try:
        # Get group owners using Graph API
        group = graph_client.groups[group_id]
        owners = sleep_and_retry(
            group.owners.get_all(page_loaded=lambda _: None),
            "get_security_group_owners",
        )

        owner_emails: list[str] = []
        logger.info(f"Owners: {owners}")

        for owner in owners:
            owner_data = owner.to_json()

            # Extract email from the JSON data
            mail: str | None = owner_data.get("mail")
            user_principal_name: str | None = owner_data.get("userPrincipalName")

            # Check if owner is a user and has an email
            if mail:
                if MICROSOFT_DOMAIN in mail:
                    mail = mail.replace(MICROSOFT_DOMAIN, "")
                owner_emails.append(mail)
            elif user_principal_name:
                if MICROSOFT_DOMAIN in user_principal_name:
                    user_principal_name = user_principal_name.replace(
                        MICROSOFT_DOMAIN, ""
                    )
                owner_emails.append(user_principal_name)

        logger.info(
            f"Retrieved {len(owner_emails)} owners from security group {group_id}"
        )
        return owner_emails

    except Exception as e:
        logger.error(f"Failed to get security group owners for group {group_id}: {e}")
        return []


def _get_sharepoint_list_item_id(drive_item: DriveItem) -> str | None:

    try:
        # First try to get the list item directly from the drive item
        if hasattr(drive_item, "listItem"):
            list_item = drive_item.listItem
            if list_item:
                # Load the list item properties to get the ID
                sleep_and_retry(list_item.get(), "get_sharepoint_list_item_id")
                if hasattr(list_item, "id") and list_item.id:
                    return str(list_item.id)

        # The SharePoint list item ID is typically available in the sharepointIds property
        sharepoint_ids = getattr(drive_item, "sharepoint_ids", None)
        if sharepoint_ids and hasattr(sharepoint_ids, "listItemId"):
            return sharepoint_ids.listItemId

        # Alternative: try to get it from the properties
        properties = getattr(drive_item, "properties", None)
        if properties:
            # Sometimes the SharePoint list item ID is in the properties
            for prop_name, prop_value in properties.items():
                if "listitemid" in prop_name.lower():
                    return str(prop_value)

        return None
    except Exception as e:
        logger.error(
            f"Error getting SharePoint list item ID for item {drive_item.id}: {e}"
        )
        raise e


def _is_public_item(drive_item: DriveItem) -> bool:
    is_public = False
    try:
        permissions = sleep_and_retry(
            drive_item.permissions.get_all(page_loaded=lambda _: None), "is_public_item"
        )
        for permission in permissions:
            if permission.link and (
                permission.link.scope == "anonymous"
                or permission.link.scope == "organization"
            ):
                is_public = True
                break
        return is_public
    except Exception as e:
        logger.error(f"Failed to check if item {drive_item.id} is public: {e}")
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
            logger.info(f"Login name {login_name} is public")
            return True
    return False


# AD groups allows same display name for multiple groups, so we need to add the GUID to the name
def _get_group_name_with_suffix(
    login_name: str, group_name: str, graph_client: GraphClient
) -> str:
    ad_group_suffix = _get_group_guid_from_identifier(graph_client, login_name)
    return f"{group_name}_{ad_group_suffix}"


def _get_sharepoint_groups(
    client_context: ClientContext, group_name: str, graph_client: GraphClient
) -> tuple[set[SharepointGroup], set[str]]:

    groups: set[SharepointGroup] = set()
    user_emails: set[str] = set()

    def process_users(users: list[Any]) -> None:
        nonlocal groups, user_emails

        for user in users:
            logger.debug(f"User: {user.to_json()}")
            if user.principal_type == USER_PRINCIPAL_TYPE and hasattr(
                user, "user_principal_name"
            ):
                if user.user_principal_name:
                    email = user.user_principal_name
                    if MICROSOFT_DOMAIN in email:
                        email = email.replace(MICROSOFT_DOMAIN, "")
                    user_emails.add(email)
                else:
                    logger.warning(
                        f"User don't have a user principal name: {user.login_name}"
                    )
            elif user.principal_type in [
                AZURE_AD_GROUP_PRINCIPAL_TYPE,
                SHAREPOINT_GROUP_PRINCIPAL_TYPE,
            ]:
                name = user.title
                if user.principal_type == AZURE_AD_GROUP_PRINCIPAL_TYPE:
                    name = _get_group_name_with_suffix(
                        user.login_name, name, graph_client
                    )
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

    group_id = _get_group_guid_from_identifier(graph_client, group_name)
    if not group_id:
        logger.error(f"Failed to get Azure AD group GUID for name {group_name}")
        return set(), set()
    group = graph_client.groups[group_id]
    groups: set[SharepointGroup] = set()
    user_emails: set[str] = set()

    def process_members(members: list[Any]) -> None:
        nonlocal groups, user_emails

        for member in members:
            member_data = member.to_json()
            logger.debug(f"Member: {member_data}")
            # Check for user-specific attributes
            user_principal_name = member_data.get("userPrincipalName")
            mail = member_data.get("mail")
            display_name = member_data.get("displayName") or member_data.get(
                "display_name"
            )

            # Check object attributes directly (if available)
            is_user = False
            is_group = False

            # Users typically have userPrincipalName or mail
            if user_principal_name or (mail and "@" in str(mail)):
                is_user = True
            # Groups typically have displayName but no userPrincipalName
            elif display_name and not user_principal_name:
                # Additional check: try to access group-specific properties
                if (
                    hasattr(member, "groupTypes")
                    or member_data.get("groupTypes") is not None
                ):
                    is_group = True
                # Or check if it has an 'id' field typical for groups
                elif member_data.get("id") and not user_principal_name:
                    is_group = True

            # Check the object type name (fallback)
            if not is_user and not is_group:
                obj_type = type(member).__name__.lower()
                if "user" in obj_type:
                    is_user = True
                elif "group" in obj_type:
                    is_group = True

            # Process based on identification
            if is_user:
                if user_principal_name:
                    email = user_principal_name
                    if MICROSOFT_DOMAIN in email:
                        email = email.replace(MICROSOFT_DOMAIN, "")
                    user_emails.add(email)
                elif mail:
                    email = mail
                    if MICROSOFT_DOMAIN in email:
                        email = email.replace(MICROSOFT_DOMAIN, "")
                    user_emails.add(email)
                logger.info(f"Added user: {user_principal_name or mail}")
            elif is_group:
                if not display_name:
                    logger.error(f"No display name for group: {member_data.get('id')}")
                    continue
                name = _get_group_name_with_suffix(
                    member_data.get("id", ""), display_name, graph_client
                )
                groups.add(
                    SharepointGroup(
                        login_name=member_data.get("id", ""),  # Use ID for groups
                        principal_type=AZURE_AD_GROUP_PRINCIPAL_TYPE,
                        name=name,
                    )
                )
                logger.info(f"Added group: {name}")
            else:
                # Log unidentified members for debugging
                logger.warning(f"Could not identify member type for: {member_data}")

    sleep_and_retry(
        group.members.get_all(page_loaded=process_members), "get_azuread_groups"
    )

    owner_emails = _get_security_group_owners(graph_client, group_id)
    user_emails.update(owner_emails)

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
            f"Processing group: {group.name} principal type: {group.principal_type}"
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
                    logger.warning(f"Group {group.login_name} not found")
                    continue
                raise e

    return GroupsResult(
        groups_to_emails=visited_group_name_to_emails,
        found_public_group=found_public_group,
    )


def get_external_access_from_sharepoint(
    client_context: ClientContext,
    graph_client: GraphClient,
    drive_name: str | None,
    drive_item: DriveItem | None,
    site_page: dict[str, Any] | None,
    add_prefix: bool = False,
) -> ExternalAccess:
    """
    Get external access information from SharePoint.
    """
    groups: set[SharepointGroup] = set()
    user_emails: set[str] = set()
    group_ids: set[str] = set()

    # Add all members to a processing set first
    def add_user_and_group_to_sets(
        role_assignments: RoleAssignmentCollection,
    ) -> None:
        nonlocal user_emails, groups
        for assignment in role_assignments:
            logger.debug(f"Assignment: {assignment.to_json()}")
            if assignment.role_definition_bindings:
                is_limited_access = True
                for role_definition_binding in assignment.role_definition_bindings:
                    if (
                        role_definition_binding.role_type_kind
                        not in LIMITED_ACCESS_ROLE_TYPES
                        or role_definition_binding.name not in LIMITED_ACCESS_ROLE_NAMES
                    ):
                        is_limited_access = False
                        break

                # Skip if the role is only Limited Access, because this is not a actual permission its a travel through permission
                if is_limited_access:
                    logger.info(
                        "Skipping assignment because it has only Limited Access role"
                    )
                    continue
            if assignment.member:
                member = assignment.member
                if member.principal_type == USER_PRINCIPAL_TYPE and hasattr(
                    member, "user_principal_name"
                ):
                    email = member.user_principal_name
                    if MICROSOFT_DOMAIN in email:
                        email = email.replace(MICROSOFT_DOMAIN, "")
                    user_emails.add(email)
                elif member.principal_type in [
                    AZURE_AD_GROUP_PRINCIPAL_TYPE,
                    SHAREPOINT_GROUP_PRINCIPAL_TYPE,
                ]:
                    name = member.title
                    if member.principal_type == AZURE_AD_GROUP_PRINCIPAL_TYPE:
                        name = _get_group_name_with_suffix(
                            member.login_name, name, graph_client
                        )
                    groups.add(
                        SharepointGroup(
                            login_name=member.login_name,
                            principal_type=member.principal_type,
                            name=name,
                        )
                    )

    if drive_item and drive_name:
        # Here we check if the item have have any public links, if so we return early
        is_public = _is_public_item(drive_item)
        if is_public:
            logger.info(f"Item {drive_item.id} is public")
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

        if drive_name == "Shared Documents":
            drive_name = "Documents"

        item = client_context.web.lists.get_by_title(drive_name).items.get_by_id(
            item_id
        )

        sleep_and_retry(
            item.role_assignments.expand(["Member", "RoleDefinitionBindings"]).get_all(
                page_loaded=add_user_and_group_to_sets,
            ),
            "get_external_access_from_sharepoint",
        )
    elif site_page:
        site_url = site_page.get("webUrl")
        # Prefer server-relative URL to avoid OData filters that break on apostrophes
        server_relative_url = unquote(urlparse(site_url).path)
        file_obj = client_context.web.get_file_by_server_relative_url(
            server_relative_url
        )
        item = file_obj.listItemAllFields

        sleep_and_retry(
            item.role_assignments.expand(["Member", "RoleDefinitionBindings"]).get_all(
                page_loaded=add_user_and_group_to_sets,
            ),
            "get_external_access_from_sharepoint",
        )
    else:
        raise RuntimeError("No drive item or site page provided")

    groups_and_members: GroupsResult = _get_groups_and_members_recursively(
        client_context, graph_client, groups
    )

    # If the site is public, w have default groups assigned to it, so we return early
    if groups_and_members.found_public_group:
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        )

    for group_name, _ in groups_and_members.groups_to_emails.items():
        if add_prefix:
            group_name = build_ext_group_name_for_onyx(
                group_name, DocumentSource.SHAREPOINT
            )
        group_ids.add(group_name.lower())

    logger.info(f"User emails: {len(user_emails)}")
    logger.info(f"Group IDs: {len(group_ids)}")

    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_ids,
        is_public=False,
    )


def get_sharepoint_external_groups(
    client_context: ClientContext, graph_client: GraphClient
) -> list[ExternalUserGroup]:

    groups: set[SharepointGroup] = set()

    def add_group_to_sets(role_assignments: RoleAssignmentCollection) -> None:
        nonlocal groups
        for assignment in role_assignments:
            if assignment.role_definition_bindings:
                is_limited_access = True
                for role_definition_binding in assignment.role_definition_bindings:
                    if (
                        role_definition_binding.role_type_kind
                        not in LIMITED_ACCESS_ROLE_TYPES
                        or role_definition_binding.name not in LIMITED_ACCESS_ROLE_NAMES
                    ):
                        is_limited_access = False
                        break

                # Skip if the role assignment is only Limited Access, because this is not a actual permission its
                #  a travel through permission
                if is_limited_access:
                    logger.info(
                        "Skipping assignment because it has only Limited Access role"
                    )
                    continue
            if assignment.member:
                member = assignment.member
                if member.principal_type in [
                    AZURE_AD_GROUP_PRINCIPAL_TYPE,
                    SHAREPOINT_GROUP_PRINCIPAL_TYPE,
                ]:
                    name = member.title
                    if member.principal_type == AZURE_AD_GROUP_PRINCIPAL_TYPE:
                        name = _get_group_name_with_suffix(
                            member.login_name, name, graph_client
                        )

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
        ).get_all(page_loaded=add_group_to_sets),
        "get_sharepoint_external_groups",
    )
    groups_and_members: GroupsResult = _get_groups_and_members_recursively(
        client_context, graph_client, groups, is_group_sync=True
    )

    # get all Azure AD groups because if any group is assigned to the drive item, we don't want to miss them
    # We can't assign sharepoint groups to drive items or drives, so we don't need to get all sharepoint groups
    azure_ad_groups = sleep_and_retry(
        graph_client.groups.get_all(page_loaded=lambda _: None),
        "get_sharepoint_external_groups:get_azure_ad_groups",
    )
    logger.info(f"Azure AD Groups: {len(azure_ad_groups)}")
    identified_groups: set[str] = set(groups_and_members.groups_to_emails.keys())
    ad_groups_to_emails: dict[str, set[str]] = {}
    for group in azure_ad_groups:
        # If the group is already identified, we don't need to get the members
        if group.display_name in identified_groups:
            continue
        # AD groups allows same display name for multiple groups, so we need to add the GUID to the name
        name = group.display_name
        name = _get_group_name_with_suffix(group.id, name, graph_client)

        members = sleep_and_retry(
            group.members.get_all(page_loaded=lambda _: None),
            "get_sharepoint_external_groups:get_azure_ad_groups:get_members",
        )
        for member in members:
            member_data = member.to_json()
            user_principal_name = member_data.get("userPrincipalName")
            mail = member_data.get("mail")
            if not ad_groups_to_emails.get(name):
                ad_groups_to_emails[name] = set()
            if user_principal_name:
                if MICROSOFT_DOMAIN in user_principal_name:
                    user_principal_name = user_principal_name.replace(
                        MICROSOFT_DOMAIN, ""
                    )
                ad_groups_to_emails[name].add(user_principal_name)
            elif mail:
                if MICROSOFT_DOMAIN in mail:
                    mail = mail.replace(MICROSOFT_DOMAIN, "")
                ad_groups_to_emails[name].add(mail)

    external_user_groups: list[ExternalUserGroup] = []
    for group_name, emails in groups_and_members.groups_to_emails.items():
        external_user_group = ExternalUserGroup(
            id=group_name,
            user_emails=list(emails),
        )
        external_user_groups.append(external_user_group)

    for group_name, emails in ad_groups_to_emails.items():
        external_user_group = ExternalUserGroup(
            id=group_name,
            user_emails=list(emails),
        )
        external_user_groups.append(external_user_group)

    return external_user_groups
