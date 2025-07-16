import re
import time
from collections import deque
from typing import Any

from office365.graph_client import GraphClient
from office365.onedrive.driveitems.driveItem import DriveItem
from office365.runtime.client_request_exception import ClientRequestException
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.permissions.securable_object import RoleAssignmentCollection
from pydantic import BaseModel

from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.access.models import ExternalAccess
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SharepointGroup(BaseModel):
    model_config = {"frozen": True}

    name: str
    login_name: str
    principal_type: int


def _sleep_and_retry(query_obj: Any, method_name: str, max_retries: int = 3) -> Any:
    """
    Execute a SharePoint query with retry logic for rate limiting.
    """
    retries = 0
    try:
        return query_obj.execute_query()
    except ClientRequestException as e:
        if e.response and e.response.status_code == 429 and retries < max_retries:
            logger.warning("Rate limit exceeded, sleeping and retrying query execution")
            retry_after = e.response.headers.get("Retry-After")
            if retry_after:
                time.sleep(int(retry_after))
            else:
                # Default sleep if no retry-after header
                time.sleep(30)
            retries += 1
            return _sleep_and_retry(query_obj, method_name, max_retries)
        raise e


def _get_azuread_group_guid_by_name(
    graph_client: GraphClient, group_name: str
) -> str | None:

    try:
        # Search for groups by display name
        groups = _sleep_and_retry(
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
        owners = _sleep_and_retry(
            group.owners.get_all(page_loaded=lambda _: None),
            "get_security_group_owners",
        )

        owner_emails: list[str] = []
        logger.info(f"Owners: {owners}")

        for owner in owners:
            owner_data = owner.to_json()
            logger.info(f"Owner: {owner_data}")

            # Extract email from the JSON data
            mail: str | None = owner_data.get("mail")
            user_principal_name: str | None = owner_data.get("userPrincipalName")

            # Check if owner is a user and has an email
            if mail:
                if ".onmicrosoft" in mail:
                    mail = mail.replace(".onmicrosoft", "")
                owner_emails.append(mail)
            elif user_principal_name:
                if ".onmicrosoft" in user_principal_name:
                    user_principal_name = user_principal_name.replace(
                        ".onmicrosoft", ""
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
                _sleep_and_retry(list_item.get(), "get_sharepoint_list_item_id")
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
        permissions = _sleep_and_retry(
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


def _is_public_site(client_context: ClientContext) -> bool:
    """
    Check if a SharePoint site is public by examining site-level permissions.
    Detects various patterns of public access including anonymous users and public groups.
    """
    try:
        # Get site role assignments to check for public access
        web = client_context.web

        # Patterns that indicate public access
        public_login_patterns: list[str] = [
            "everyone except external users",
            "everyone",
            "anonymous",
            "nt authority\\authenticated users",
            "c:0(.s|true",  # Claims-based anonymous
        ]

        # Flag to track if we found public access
        is_public = False

        def check_for_public_access(role_assignments: RoleAssignmentCollection) -> None:
            nonlocal is_public

            for assignment in role_assignments:
                if not assignment.member:
                    continue

                member = assignment.member

                # Check for anonymous users (principal_type 3)
                if hasattr(member, "principal_type") and member.principal_type == 3:
                    logger.info("Site has anonymous user access (principal_type=3)")
                    is_public = True
                    return

                # Check login_name for public patterns
                if hasattr(member, "login_name") and member.login_name:
                    login_name = member.login_name.lower()
                    for pattern in public_login_patterns:
                        if pattern in login_name:
                            logger.info(
                                f"Site has public group access: {member.login_name}"
                            )
                            is_public = True
                            return

                # Check title for public patterns as fallback
                if hasattr(member, "title") and member.title:
                    title = member.title.lower()
                    for pattern in public_login_patterns:
                        if pattern in title:
                            logger.info(
                                f"Site has public group access via title: {member.title}"
                            )
                            is_public = True
                            return

        _sleep_and_retry(
            web.role_assignments.expand(["Member", "RoleDefinitionBindings"]).get_all(
                page_loaded=check_for_public_access
            ),
            "is_public_site",
        )

        return is_public

    except Exception as e:
        logger.error(f"Failed to check if site is public: {e}")
        return False


def _get_sharepoint_groups(
    client_context: ClientContext, group_name: str
) -> tuple[set[SharepointGroup], set[str]]:

    try:
        groups: set[SharepointGroup] = set()
        user_emails: set[str] = set()

        def process_users(users) -> None:
            nonlocal groups, user_emails

            for user in users:
                logger.info(f"User: {user.to_json()}")
                if user.principal_type == 1 and hasattr(user, "user_principal_name"):
                    if user.user_principal_name:
                        email = user.user_principal_name
                        if ".onmicrosoft" in email:
                            email = email.replace(".onmicrosoft", "")
                        user_emails.add(email)
                    else:
                        logger.warning(
                            f"User don't have a user principal name: {user.login_name}"
                        )
                elif user.principal_type in [4, 8]:
                    groups.add(
                        SharepointGroup(
                            login_name=user.login_name,
                            principal_type=user.principal_type,
                            name=user.title,
                        )
                    )

        group = client_context.web.site_groups.get_by_name(group_name)
        _sleep_and_retry(
            group.users.get_all(page_loaded=process_users), "get_sharepoint_groups"
        )

        return groups, user_emails
    except Exception as e:
        logger.error(f"Failed to get SharePoint group info for group {group_name}: {e}")
        return set(), set()


def _get_azuread_groups(
    graph_client: GraphClient, group_name: str
) -> tuple[set[SharepointGroup], set[str]]:
    group_id = _get_group_guid_from_identifier(graph_client, group_name)
    if not group_id:
        logger.error(f"Failed to get Azure AD group GUID for name {group_name}")
        return set(), set()
    try:
        group = graph_client.groups[group_id]
        groups: set[SharepointGroup] = set()
        user_emails: set[str] = set()

        def process_members(members) -> None:
            nonlocal groups, user_emails

            for member in members:
                member_data = member.to_json()
                logger.info(f"Member: {member_data}")

                # Check for user-specific attributes
                user_principal_name = member_data.get(
                    "userPrincipalName"
                ) or member_data.get("user_principal_name")
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
                        if ".onmicrosoft" in email:
                            email = email.replace(".onmicrosoft", "")
                        user_emails.add(email)
                    elif mail:
                        email = mail
                        if ".onmicrosoft" in email:
                            email = email.replace(".onmicrosoft", "")
                        user_emails.add(email)
                    logger.info(f"Added user: {user_principal_name or mail}")
                elif is_group:
                    if not display_name:
                        logger.error(
                            f"No display name for group: {member_data.get('id')}"
                        )
                        continue
                    groups.add(
                        SharepointGroup(
                            login_name=member_data.get("id", ""),  # Use ID for groups
                            principal_type=4,
                            name=display_name,
                        )
                    )
                    logger.info(f"Added group: {display_name}")
                else:
                    # Log unidentified members for debugging
                    logger.warning(f"Could not identify member type for: {member_data}")

        _sleep_and_retry(
            group.members.get_all(page_loaded=process_members), "get_azuread_groups"
        )

        owner_emails = _get_security_group_owners(graph_client, group_id)
        user_emails.update(owner_emails)

        return groups, user_emails
    except Exception as e:
        logger.error(f"Failed to get Azure AD group info for group {group_name}: {e}")
        return set(), set()


def _get_groups_and_members_recursively(
    client_context: ClientContext,
    graph_client: GraphClient,
    groups: set[SharepointGroup],
) -> dict[str, set[str]]:
    """
    Get all groups and their members recursively.
    """
    group_queue: deque[SharepointGroup] = deque(groups)
    visited_groups: set[str] = set()
    visited_group_name_to_emails: dict[str, set[str]] = {}
    try:
        while group_queue:
            group = group_queue.popleft()
            if group.login_name in visited_groups:
                continue
            visited_groups.add(group.login_name)
            visited_group_name_to_emails[group.name] = set()
            logger.info(
                f"Processing group: {group.name} principal type: {group.principal_type}"
            )
            if group.principal_type == 8:
                group_info, user_emails = _get_sharepoint_groups(
                    client_context, group.login_name
                )
                visited_group_name_to_emails[group.name].update(user_emails)
                if group_info:
                    group_queue.extend(group_info)
            if group.principal_type == 4:
                group_info, user_emails = _get_azuread_groups(
                    graph_client, group.login_name
                )
                visited_group_name_to_emails[group.name].update(user_emails)
                if group_info:
                    group_queue.extend(group_info)
    except Exception as e:
        logger.error(f"Failed to get groups and members recursively: {e}")

    return visited_group_name_to_emails


def get_external_access_from_sharepoint(
    client_context: ClientContext,
    graph_client: GraphClient,
    drive_name: str,
    drive_item: DriveItem,
) -> ExternalAccess:
    """
    Get external access information from SharePoint.
    """

    is_public = _is_public_item(drive_item)
    if is_public:
        logger.info(f"Item {drive_item.id} is public")
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=is_public,
        )
    groups: set[SharepointGroup] = set()
    user_emails: set[str] = set()
    group_ids: set[str] = set()

    item_id = _get_sharepoint_list_item_id(drive_item)

    if not item_id:
        raise RuntimeError(
            f"Failed to get SharePoint list item ID for item {drive_item.id}"
        )

    if drive_name == "Shared Documents":
        drive_name = "Documents"

    item = client_context.web.lists.get_by_title(drive_name).items.get_by_id(item_id)

    # Add all members to a processing set first
    def add_user_and_group_to_sets(
        role_assignments: RoleAssignmentCollection,
    ) -> None:
        nonlocal user_emails, groups
        for assignment in role_assignments:
            if assignment.member:
                member = assignment.member
                if hasattr(member, "principal_type"):
                    if member.principal_type == 1 and hasattr(
                        member, "user_principal_name"
                    ):
                        email = member.user_principal_name
                        if ".onmicrosoft" in email:
                            email = email.replace(".onmicrosoft", "")
                        user_emails.add(email)
                    elif member.principal_type in [
                        4,
                        8,
                    ]:  # Both Azure AD Groups and SharePoint Groups
                        groups.add(
                            SharepointGroup(
                                login_name=member.login_name,
                                principal_type=member.principal_type,
                                name=member.title,
                            )
                        )

    _sleep_and_retry(
        item.role_assignments.expand(["Member"]).get_all(
            page_loaded=add_user_and_group_to_sets
        ),
        "get_external_access_from_sharepoint",
    )
    groups_and_members: dict[str, set[str]] = _get_groups_and_members_recursively(
        client_context, graph_client, groups
    )
    for group_name, _ in groups_and_members.items():
        group_ids.add(group_name.lower())

    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_ids,
        is_public=is_public,
    )


def get_sharepoint_external_groups(
    client_context: ClientContext, graph_client: GraphClient
) -> list[ExternalUserGroup]:

    # Check if site is public first
    if _is_public_site(client_context):
        logger.info("Site is public, returning empty external groups list")
        return []

    groups: set[SharepointGroup] = set()

    def add_group_to_sets(role_assignments: RoleAssignmentCollection) -> None:
        nonlocal groups
        for assignment in role_assignments:
            if assignment.member:
                member = assignment.member
                if hasattr(member, "principal_type"):
                    if member.principal_type in [
                        4,
                        8,
                    ]:  # Both Azure AD Groups and SharePoint Groups
                        groups.add(
                            SharepointGroup(
                                login_name=member.login_name,
                                principal_type=member.principal_type,
                                name=member.title,
                            )
                        )

    _sleep_and_retry(
        client_context.web.role_assignments.expand(["Member"]).get_all(
            page_loaded=add_group_to_sets
        ),
        "get_sharepoint_external_groups",
    )
    groups_and_members: dict[str, set[str]] = _get_groups_and_members_recursively(
        client_context, graph_client, groups
    )
    external_user_groups: list[ExternalUserGroup] = []
    for group_name, emails in groups_and_members.items():
        external_user_group = ExternalUserGroup(
            id=group_name,
            user_emails=list(emails),
        )
        external_user_groups.append(external_user_group)
    return external_user_groups
