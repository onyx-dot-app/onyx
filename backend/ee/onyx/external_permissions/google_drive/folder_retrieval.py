from collections.abc import Iterator

from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
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
