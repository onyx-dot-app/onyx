from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from googleapiclient.discovery import Resource  # type: ignore

from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.constants import DRIVE_SHORTCUT_TYPE
from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.utils.logger import setup_logger

logger = setup_logger()

FILE_FIELDS = (
    "nextPageToken, files(mimeType, id, name, permissions, modifiedTime, webViewLink, "
    "shortcutDetails, owners(emailAddress), size)"
)
SLIM_FILE_FIELDS = (
    "nextPageToken, files(mimeType, driveId, id, name, permissions(emailAddress, type), "
    "permissionIds, webViewLink, owners(emailAddress))"
)
FOLDER_FIELDS = "nextPageToken, files(id, name, permissions, modifiedTime, webViewLink, shortcutDetails)"


def _generate_time_range_filter(
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> str:
    time_range_filter = ""
    if start is not None:
        time_start = datetime.utcfromtimestamp(start).isoformat() + "Z"
        time_range_filter += f" and modifiedTime >= '{time_start}'"
    if end is not None:
        time_stop = datetime.utcfromtimestamp(end).isoformat() + "Z"
        time_range_filter += f" and modifiedTime <= '{time_stop}'"
    return time_range_filter


def _get_folders_in_parent(
    service: Resource,
    parent_id: str | None = None,
) -> Iterator[GoogleDriveFileType]:
    # Follow shortcuts to folders
    query = f"(mimeType = '{DRIVE_FOLDER_TYPE}' or mimeType = '{DRIVE_SHORTCUT_TYPE}')"
    query += " and trashed = false"

    if parent_id:
        query += f" and '{parent_id}' in parents"

    for file in execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        continue_on_404_or_403=True,
        corpora="allDrives",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields=FOLDER_FIELDS,
        q=query,
    ):
        yield file


def _get_files_in_parent(
    service: Resource,
    parent_id: str,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
    is_slim: bool = False,
) -> Iterator[GoogleDriveFileType]:
    query = f"mimeType != '{DRIVE_FOLDER_TYPE}' and '{parent_id}' in parents"
    query += " and trashed = false"
    query += _generate_time_range_filter(start, end)

    for file in execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        continue_on_404_or_403=True,
        corpora="allDrives",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields=SLIM_FILE_FIELDS if is_slim else FILE_FIELDS,
        q=query,
    ):
        yield file


def crawl_folders_for_files(
    service: Resource,
    parent_id: str,
    traversed_parent_ids: set[str],
    update_traversed_ids_func: Callable[[str], None],
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[GoogleDriveFileType]:
    """
    This function starts crawling from any folder. It is slower though.
    """
    if parent_id in traversed_parent_ids:
        logger.info(f"Skipping subfolder since already traversed: {parent_id}")
        return

    found_files = False
    for file in _get_files_in_parent(
        service=service,
        start=start,
        end=end,
        parent_id=parent_id,
    ):
        found_files = True
        yield file

    if found_files:
        update_traversed_ids_func(parent_id)

    for subfolder in _get_folders_in_parent(
        service=service,
        parent_id=parent_id,
    ):
        logger.info("Fetching all files in subfolder: " + subfolder["name"])
        yield from crawl_folders_for_files(
            service=service,
            parent_id=subfolder["id"],
            traversed_parent_ids=traversed_parent_ids,
            update_traversed_ids_func=update_traversed_ids_func,
            start=start,
            end=end,
        )


def get_files_in_shared_drive(
    service: Resource,
    drive_id: str,
    is_slim: bool = False,
    update_traversed_ids_func: Callable[[str], None] = lambda _: None,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[GoogleDriveFileType]:
    # If we know we are going to folder crawl later, we can cache the folders here
    # Get all folders being queried and add them to the traversed set
    folder_query = f"mimeType = '{DRIVE_FOLDER_TYPE}'"
    folder_query += " and trashed = false"
    found_folders = False
    for file in execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        continue_on_404_or_403=True,
        corpora="drive",
        driveId=drive_id,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields="nextPageToken, files(id)",
        q=folder_query,
    ):
        update_traversed_ids_func(file["id"])
        found_folders = True
    if found_folders:
        update_traversed_ids_func(drive_id)

    # Get all files in the shared drive
    file_query = f"mimeType != '{DRIVE_FOLDER_TYPE}'"
    file_query += " and trashed = false"
    file_query += _generate_time_range_filter(start, end)
    yield from execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        continue_on_404_or_403=True,
        corpora="drive",
        driveId=drive_id,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields=SLIM_FILE_FIELDS if is_slim else FILE_FIELDS,
        q=file_query,
    )


def get_all_files_in_my_drive(
    service: Any,
    update_traversed_ids_func: Callable,
    is_slim: bool = False,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[GoogleDriveFileType]:
    # If we know we are going to folder crawl later, we can cache the folders here
    # Get all folders being queried and add them to the traversed set
    folder_query = f"mimeType = '{DRIVE_FOLDER_TYPE}'"
    folder_query += " and trashed = false"
    folder_query += " and 'me' in owners"
    found_folders = False
    for file in execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        corpora="user",
        fields=SLIM_FILE_FIELDS if is_slim else FILE_FIELDS,
        q=folder_query,
    ):
        update_traversed_ids_func(file["id"])
        found_folders = True
    if found_folders:
        update_traversed_ids_func(get_root_folder_id(service))

    # Then get the files
    file_query = f"mimeType != '{DRIVE_FOLDER_TYPE}'"
    file_query += " and trashed = false"
    file_query += " and 'me' in owners"
    file_query += _generate_time_range_filter(start, end)
    yield from execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        corpora="user",
        fields=SLIM_FILE_FIELDS if is_slim else FILE_FIELDS,
        q=file_query,
    )


def get_all_files_for_oauth(
    service: Any,
    include_files_shared_with_me: bool,
    include_my_drives: bool,
    # One of the above 2 should be true
    include_shared_drives: bool,
    is_slim: bool = False,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[GoogleDriveFileType]:
    should_get_all = (
        include_shared_drives and include_my_drives and include_files_shared_with_me
    )
    corpora = "allDrives" if should_get_all else "user"

    file_query = f"mimeType != '{DRIVE_FOLDER_TYPE}'"
    file_query += " and trashed = false"
    file_query += _generate_time_range_filter(start, end)

    if not should_get_all:
        if include_files_shared_with_me and not include_my_drives:
            file_query += " and not 'me' in owners"
        if not include_files_shared_with_me and include_my_drives:
            file_query += " and 'me' in owners"

    yield from execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        corpora=corpora,
        includeItemsFromAllDrives=should_get_all,
        supportsAllDrives=should_get_all,
        fields=SLIM_FILE_FIELDS if is_slim else FILE_FIELDS,
        q=file_query,
    )


# Just in case we need to get the root folder id
def get_root_folder_id(service: Resource) -> str:
    # we dont paginate here because there is only one root folder per user
    # https://developers.google.com/drive/api/guides/v2-to-v3-reference
    return service.files().get(fileId="root", fields="id").execute()["id"]
