from collections.abc import Iterator

from ee.onyx.external_permissions.google_drive.models import GoogleDrivePermission
from ee.onyx.external_permissions.google_drive.permission_retrieval import (
    get_permissions_by_ids,
)
from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
)


def get_folder_permissions_by_ids(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    folder_id: str,
    permission_ids: list[str],
) -> list[GoogleDrivePermission]:
    """
    Retrieves permissions for a specific folder filtered by permission IDs.

    Args:
        ops: The Google Drive source operations
        user_email: The user to read the permissions as
        folder_id: The ID of the folder to fetch permissions for
        permission_ids: A list of permission IDs to filter by

    Returns:
        A list of permissions matching the provided permission IDs
    """
    return get_permissions_by_ids(
        ops=ops,
        user_email=user_email,
        doc_id=folder_id,
        permission_ids=permission_ids,
    )


def get_modified_folders(
    ops: GoogleDriveSourceOperations,
    user_email: str,
) -> Iterator[GoogleDriveFileType]:
    """
    Retrieves every folder the user can see. Only includes folder ID and
    permission information, not any contained files.
    """
    yield from ops.list_folders_with_permissions(user_email=user_email)
