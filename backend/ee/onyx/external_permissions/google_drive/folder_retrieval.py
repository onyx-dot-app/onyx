from collections.abc import Iterator

from googleapiclient.discovery import Resource  # type: ignore

from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.file_retrieval import generate_time_range_filter
from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Only include fields we need - folder ID and permissions
FOLDER_PERMISSION_FIELDS = (
    "nextPageToken, "
    "files("
    "id, "
    "name, "
    "permissions("
    "id, "
    "emailAddress, "
    "type, "
    "domain, "
    "permissionDetails"
    ")"
    ")"
)


def get_modified_folders(
    service: Resource,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[dict]:
    """
    Retrieves all folders that were modified within the specified time range.
    Only includes folder ID and permission information, not any contained files.

    Args:
        service: The Google Drive service instance
        start: The start time as seconds since Unix epoch (inclusive)
        end: The end time as seconds since Unix epoch (inclusive)

    Returns:
        An iterator yielding folder information including ID and permissions
    """
    # Build query for folders
    query = f"mimeType = '{DRIVE_FOLDER_TYPE}'"
    query += " and trashed = false"
    query += generate_time_range_filter(start, end)

    # Retrieve and yield folders
    for folder in execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        continue_on_404_or_403=True,
        corpora="allDrives",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields=FOLDER_PERMISSION_FIELDS,
        q=query,
    ):
        yield folder
