from collections.abc import Iterator

from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_drive.source_operations import (
    DriveFolderScope,
    GoogleDriveSourceOperations,
)


def get_folders(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    scope: DriveFolderScope,
    drive_id: str | None = None,
) -> Iterator[GoogleDriveFileType]:
    """
    Retrieves the folders in ``scope`` as ``user_email``. Only includes folder
    ID and permission information, not any contained files.
    """
    yield from ops.list_folders_with_permissions(
        user_email=user_email, scope=scope, drive_id=drive_id
    )
