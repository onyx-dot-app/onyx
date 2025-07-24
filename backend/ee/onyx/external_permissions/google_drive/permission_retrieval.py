from retry import retry

from ee.onyx.external_permissions.google_drive.models import GoogleDrivePermission
from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
from onyx.connectors.google_utils.resources import GoogleDriveService
from onyx.utils.logger import setup_logger

logger = setup_logger()


@retry(tries=3, delay=2, backoff=2)
def get_permissions_by_ids(
    drive_service: GoogleDriveService,
    doc_id: str,
    permission_ids: list[str],
) -> list[GoogleDrivePermission]:
    """
    Fetches permissions for a document based on a list of permission IDs.

    Args:
        drive_service: The Google Drive service instance
        doc_id: The ID of the document to fetch permissions for
        permission_ids: A list of permission IDs to filter by

    Returns:
        A list of GoogleDrivePermission objects matching the provided permission IDs
    """
    if not permission_ids:
        return []

    # Create a set for faster lookup
    permission_id_set = set(permission_ids)

    # Fetch all permissions for the document
    fetched_permissions = execute_paginated_retrieval(
        retrieval_function=drive_service.permissions().list,
        list_key="permissions",
        fileId=doc_id,
        fields="permissions(id, emailAddress, type, domain, permissionDetails),nextPageToken",
        supportsAllDrives=True,
        continue_on_404_or_403=True,
    )

    # Filter permissions by ID and convert to GoogleDrivePermission objects
    filtered_permissions = []
    for permission in fetched_permissions:
        permission_id = permission.get("id")
        if permission_id in permission_id_set:
            google_drive_permission = GoogleDrivePermission.from_drive_permission(
                permission
            )
            filtered_permissions.append(google_drive_permission)

    # Log if we couldn't find all requested permission IDs
    if len(filtered_permissions) < len(permission_ids):
        missing_ids = permission_id_set - {p.id for p in filtered_permissions if p.id}
        logger.warning(
            f"Could not find all requested permission IDs for document {doc_id}. "
            f"Missing IDs: {missing_ids}"
        )

    return filtered_permissions
