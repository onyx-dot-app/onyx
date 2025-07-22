from collections.abc import Generator

from googleapiclient.errors import HttpError  # type: ignore
from pydantic import BaseModel

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.google_drive.folder_retrieval import (
    get_folder_permissions_by_ids,
)
from ee.onyx.external_permissions.google_drive.folder_retrieval import (
    get_modified_folders,
)
from ee.onyx.external_permissions.google_drive.models import GoogleDrivePermission
from ee.onyx.external_permissions.google_drive.models import PermissionType
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
from onyx.connectors.google_utils.resources import AdminService
from onyx.connectors.google_utils.resources import get_admin_service
from onyx.connectors.google_utils.resources import get_drive_service
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


"""
Folder Permission Sync.

Each folder is treated as a group. Each file has all ancestor folders
as groups.
"""


class FolderInfo(BaseModel):
    id: str
    permissions: list[GoogleDrivePermission]


def _get_all_folders(
    google_drive_connector: GoogleDriveConnector, skip_folders_without_permissions: bool
) -> list[FolderInfo]:
    """Have to get all folders since the group syncing system assumes all groups
    are returned every time.

    TODO: tweak things so we can fetch deltas.
    """
    MAX_FAILED_PERCENTAGE = 0.5

    all_folders: list[FolderInfo] = []
    seen_folder_ids: set[str] = set()

    def _get_all_folders_for_user(
        google_drive_connector: GoogleDriveConnector,
        skip_folders_without_permissions: bool,
        user_email: str,
    ) -> None:
        """Helper to get folders for a specific user + update shared seen_folder_ids"""
        drive_service = get_drive_service(
            google_drive_connector.creds,
            user_email,
        )

        for folder in get_modified_folders(
            service=drive_service,
        ):
            folder_id = folder["id"]
            if folder_id in seen_folder_ids:
                logger.debug(f"Folder {folder_id} has already been seen. Skipping.")
                continue

            seen_folder_ids.add(folder_id)

            # Check if the folder has permission IDs but no permissions
            permission_ids = folder.get("permissionIds", [])
            raw_permissions = folder.get("permissions", [])

            if not raw_permissions and permission_ids:
                # Fetch permissions using the IDs
                permissions = get_folder_permissions_by_ids(
                    drive_service, folder_id, permission_ids
                )
            else:
                permissions = [
                    GoogleDrivePermission.from_drive_permission(permission)
                    for permission in raw_permissions
                ]

            # Don't include inherited permissions, those will be captured
            # by the folder/shared drive itself
            permissions = [
                permission
                for permission in permissions
                if permission.inherited_from is None
            ]

            if not permissions and skip_folders_without_permissions:
                logger.debug(f"Folder {folder_id} has no permissions. Skipping.")
                continue

            all_folders.append(
                FolderInfo(
                    id=folder_id,
                    permissions=permissions,
                )
            )

    failed_count = 0
    user_emails = google_drive_connector._get_all_user_emails()
    for user_email in user_emails:
        try:
            _get_all_folders_for_user(
                google_drive_connector, skip_folders_without_permissions, user_email
            )
        except Exception:
            logger.exception(f"Error getting folders for user {user_email}")
            failed_count += 1

            if failed_count > MAX_FAILED_PERCENTAGE * len(user_emails):
                raise RuntimeError("Too many failed folder fetches during group sync")

    return all_folders


def _drive_folder_to_onyx_group(
    folder: FolderInfo,
    group_email_to_member_emails_map: dict[str, list[str]],
) -> ExternalUserGroup:
    """
    Converts a folder into an Onyx group.
    """
    anyone_can_access = False
    folder_member_emails: set[str] = set()

    for permission in folder.permissions:
        if permission.type == PermissionType.USER:
            if permission.email_address is None:
                logger.warning(
                    f"User email is None for folder {folder.id} permission {permission}"
                )
                continue
            folder_member_emails.add(permission.email_address)
        elif permission.type == PermissionType.GROUP:
            if permission.email_address not in group_email_to_member_emails_map:
                logger.warning(
                    f"Group email {permission.email_address} for folder {folder.id} "
                    "not found in group_email_to_member_emails_map"
                )
                continue
            folder_member_emails.update(
                group_email_to_member_emails_map[permission.email_address]
            )
        elif permission.type == PermissionType.ANYONE:
            anyone_can_access = True

    return ExternalUserGroup(
        id=folder.id,
        user_emails=list(folder_member_emails),
        gives_anyone_access=anyone_can_access,
    )


"""Individual Shared Drive / My Drive Permission Sync"""


def _get_drive_members(
    google_drive_connector: GoogleDriveConnector,
    admin_service: AdminService,
) -> dict[str, tuple[set[str], set[str]]]:
    """
    This builds a map of drive ids to their members (group and user emails).
    E.g. {
        "drive_id_1": ({"group_email_1"}, {"user_email_1", "user_email_2"}),
        "drive_id_2": ({"group_email_3"}, {"user_email_3"}),
    }
    """

    # fetches shared drives only
    drive_ids = google_drive_connector.get_all_drive_ids()

    drive_id_to_members_map: dict[str, tuple[set[str], set[str]]] = {}
    drive_service = get_drive_service(
        google_drive_connector.creds,
        google_drive_connector.primary_admin_email,
    )

    admin_user_info = (
        admin_service.users()
        .get(userKey=google_drive_connector.primary_admin_email)
        .execute()
    )
    is_admin = admin_user_info.get("isAdmin", False) or admin_user_info.get(
        "isDelegatedAdmin", False
    )

    for drive_id in drive_ids:
        group_emails: set[str] = set()
        user_emails: set[str] = set()

        try:
            for permission in execute_paginated_retrieval(
                drive_service.permissions().list,
                list_key="permissions",
                fileId=drive_id,
                fields="permissions(emailAddress, type),nextPageToken",
                supportsAllDrives=True,
                # can only set `useDomainAdminAccess` to true if the user
                # is an admin
                useDomainAdminAccess=is_admin,
            ):
                # NOTE: don't need to check for PermissionType.ANYONE since
                # you can't share a drive with the internet
                if permission["type"] == PermissionType.GROUP:
                    group_emails.add(permission["emailAddress"])
                elif permission["type"] == PermissionType.USER:
                    user_emails.add(permission["emailAddress"])
        except HttpError as e:
            if e.status_code == 404:
                logger.warning(
                    f"Error getting permissions for drive id {drive_id}. "
                    f"User '{google_drive_connector.primary_admin_email}' likely "
                    f"does not have access to this drive. Exception: {e}"
                )
            else:
                raise e

        drive_id_to_members_map[drive_id] = (group_emails, user_emails)
    return drive_id_to_members_map


def _drive_member_map_to_onyx_groups(
    drive_id_to_members_map: dict[str, tuple[set[str], set[str]]],
    group_email_to_member_emails_map: dict[str, list[str]],
) -> Generator[ExternalUserGroup, None, None]:
    """The `user_emails` for the Shared Drive should be all individuals in the
    Shared Drive + the union of all flattened group emails."""
    for drive_id, (group_emails, user_emails) in drive_id_to_members_map.items():
        drive_member_emails: set[str] = user_emails
        for group_email in group_emails:
            if group_email not in group_email_to_member_emails_map:
                logger.warning(
                    f"Group email {group_email} for drive {drive_id} not found in "
                    "group_email_to_member_emails_map"
                )
                continue
            drive_member_emails.update(group_email_to_member_emails_map[group_email])
        yield ExternalUserGroup(
            id=drive_id,
            user_emails=list(drive_member_emails),
        )


def _get_all_google_groups(
    admin_service: AdminService,
    google_domain: str,
) -> set[str]:
    """
    This gets all the group emails.
    """
    group_emails: set[str] = set()
    for group in execute_paginated_retrieval(
        admin_service.groups().list,
        list_key="groups",
        domain=google_domain,
        fields="groups(email),nextPageToken",
    ):
        group_emails.add(group["email"])
    return group_emails


def _google_group_to_onyx_group(
    admin_service: AdminService,
    group_email: str,
) -> ExternalUserGroup:
    """
    This maps google group emails to their member emails.
    """
    group_member_emails: set[str] = set()
    for member in execute_paginated_retrieval(
        admin_service.members().list,
        list_key="members",
        groupKey=group_email,
        fields="members(email),nextPageToken",
    ):
        group_member_emails.add(member["email"])

    return ExternalUserGroup(
        id=group_email,
        user_emails=list(group_member_emails),
    )


def _map_group_email_to_member_emails(
    admin_service: AdminService,
    group_emails: set[str],
) -> dict[str, set[str]]:
    """
    This maps group emails to their member emails.
    """
    group_to_member_map: dict[str, set[str]] = {}
    for group_email in group_emails:
        group_member_emails: set[str] = set()
        for member in execute_paginated_retrieval(
            admin_service.members().list,
            list_key="members",
            groupKey=group_email,
            fields="members(email),nextPageToken",
        ):
            group_member_emails.add(member["email"])

        group_to_member_map[group_email] = group_member_emails
    return group_to_member_map


def _build_onyx_groups(
    drive_id_to_members_map: dict[str, tuple[set[str], set[str]]],
    group_email_to_member_emails_map: dict[str, set[str]],
    folder_info: list[FolderInfo],
) -> list[ExternalUserGroup]:
    onyx_groups: list[ExternalUserGroup] = []

    # Convert all drive member definitions to onyx groups
    # This is because having drive level access means you have
    # irrevocable access to all the files in the drive.
    for drive_id, (group_emails, user_emails) in drive_id_to_members_map.items():
        drive_member_emails: set[str] = user_emails
        for group_email in group_emails:
            if group_email not in group_email_to_member_emails_map:
                logger.warning(
                    f"Group email {group_email} for drive {drive_id} not found in "
                    "group_email_to_member_emails_map"
                )
                continue
            drive_member_emails.update(group_email_to_member_emails_map[group_email])
        onyx_groups.append(
            ExternalUserGroup(
                id=drive_id,
                user_emails=list(drive_member_emails),
            )
        )

    # Convert all folder permissions to onyx groups
    for folder in folder_info:
        anyone_can_access = False
        folder_member_emails: set[str] = set()
        for permission in folder.permissions:
            if permission.type == PermissionType.USER:
                if permission.email_address is None:
                    logger.warning(
                        f"User email is None for folder {folder.id} permission {permission}"
                    )
                    continue
                folder_member_emails.add(permission.email_address)
            elif permission.type == PermissionType.GROUP:
                if permission.email_address not in group_email_to_member_emails_map:
                    logger.warning(
                        f"Group email {permission.email_address} for folder {folder.id} "
                        "not found in group_email_to_member_emails_map"
                    )
                    continue
                folder_member_emails.update(
                    group_email_to_member_emails_map[permission.email_address]
                )
            elif permission.type == PermissionType.ANYONE:
                anyone_can_access = True

        onyx_groups.append(
            ExternalUserGroup(
                id=folder.id,
                user_emails=list(folder_member_emails),
                gives_anyone_access=anyone_can_access,
            )
        )

    # Convert all group member definitions to onyx groups
    for group_email, member_emails in group_email_to_member_emails_map.items():
        onyx_groups.append(
            ExternalUserGroup(
                id=group_email,
                user_emails=list(member_emails),
            )
        )

    return onyx_groups


def gdrive_group_sync(
    tenant_id: str,
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    # Initialize connector and build credential/service objects
    google_drive_connector = GoogleDriveConnector(
        **cc_pair.connector.connector_specific_config
    )
    google_drive_connector.load_credentials(cc_pair.credential.credential_json)
    admin_service = get_admin_service(
        google_drive_connector.creds, google_drive_connector.primary_admin_email
    )

    # Get all drive members
    drive_id_to_members_map = _get_drive_members(google_drive_connector, admin_service)

    # Get all group emails
    all_group_emails = _get_all_google_groups(
        admin_service, google_drive_connector.google_domain
    )

    # Each google group is an Onyx group, yield those
    group_email_to_member_emails_map: dict[str, list[str]] = {}
    for group_email in all_group_emails:
        onyx_group = _google_group_to_onyx_group(admin_service, group_email)
        group_email_to_member_emails_map[group_email] = onyx_group.user_emails
        yield onyx_group

    # Each drive is a group, yield those
    for onyx_group in _drive_member_map_to_onyx_groups(
        drive_id_to_members_map, group_email_to_member_emails_map
    ):
        yield onyx_group

    # Get all folder permissions
    folder_info = _get_all_folders(
        google_drive_connector=google_drive_connector,
        skip_folders_without_permissions=True,
    )
    for folder in folder_info:
        yield _drive_folder_to_onyx_group(folder, group_email_to_member_emails_map)
