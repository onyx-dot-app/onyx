from ee.onyx.external_permissions.google_drive.models import GoogleDrivePermission
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveHttpError,
    GoogleDriveSourceOperations,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

_PERMISSION_FIELDS = (
    "permissions(id, emailAddress, type, domain, allowFileDiscovery, "
    "permissionDetails),nextPageToken"
)


@retry_builder(tries=3, delay=2, backoff=2)
def get_permissions_by_ids(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    doc_id: str,
    permission_ids: list[str],
) -> list[GoogleDrivePermission]:
    """
    Fetches permissions for a document based on a list of permission IDs.

    Args:
        ops: The Google Drive source operations
        user_email: The user to read the permissions as
        doc_id: The ID of the document to fetch permissions for
        permission_ids: A list of permission IDs to filter by

    Returns:
        A list of GoogleDrivePermission objects matching the provided permission
        IDs. Empty when the user cannot read the permissions (403 or 404).
    """
    if not permission_ids:
        return []

    # Create a set for faster lookup
    permission_id_set = set(permission_ids)

    # Fetch all permissions for the document
    try:
        fetched_permissions = list(
            ops.list_file_permissions(
                user_email=user_email, file_id=doc_id, fields=_PERMISSION_FIELDS
            )
        )
    except GoogleDriveHttpError as e:
        if e.status_code not in (403, 404):
            raise
        logger.debug("Cannot read the permissions of %s: %s", doc_id, e)
        fetched_permissions = []

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
            "Could not find all requested permission IDs for document %s. Missing IDs: %s",
            doc_id,
            missing_ids,
        )

    return filtered_permissions
