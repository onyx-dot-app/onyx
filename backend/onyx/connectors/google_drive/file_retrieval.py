from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone

from googleapiclient.discovery import Resource  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore

from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.constants import DRIVE_SHORTCUT_TYPE
from onyx.connectors.google_drive.models import DriveRetrievalStage
from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_drive.models import RetrievedDriveFile
from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
from onyx.connectors.google_utils.google_utils import GoogleFields
from onyx.connectors.google_utils.google_utils import ORDER_BY_KEY
from onyx.connectors.google_utils.resources import GoogleDriveService
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.utils.logger import setup_logger


logger = setup_logger()

PERMISSION_FULL_DESCRIPTION = (
    "permissions(id, emailAddress, type, domain, permissionDetails)"
)
FILE_FIELDS = (
    "nextPageToken, files(mimeType, id, name, permissions, modifiedTime, webViewLink, "
    "shortcutDetails, owners(emailAddress), size)"
)
SLIM_FILE_FIELDS = (
    f"nextPageToken, files(mimeType, driveId, id, name, {PERMISSION_FULL_DESCRIPTION}, "
    "permissionIds, webViewLink, owners(emailAddress))"
)
FOLDER_FIELDS = "nextPageToken, files(id, name, permissions, modifiedTime, webViewLink, shortcutDetails)"


def generate_time_range_filter(
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> str:
    time_range_filter = ""
    if start is not None:
        time_start = datetime.fromtimestamp(start, tz=timezone.utc).isoformat()
        time_range_filter += (
            f" and {GoogleFields.MODIFIED_TIME.value} >= '{time_start}'"
        )
    if end is not None:
        time_stop = datetime.fromtimestamp(end, tz=timezone.utc).isoformat()
        time_range_filter += f" and {GoogleFields.MODIFIED_TIME.value} <= '{time_stop}'"
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
    is_slim: bool,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[GoogleDriveFileType]:
    query = f"mimeType != '{DRIVE_FOLDER_TYPE}' and '{parent_id}' in parents"
    query += " and trashed = false"
    query += generate_time_range_filter(start, end)

    for file in execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        continue_on_404_or_403=True,
        corpora="allDrives",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields=SLIM_FILE_FIELDS if is_slim else FILE_FIELDS,
        q=query,
        **({} if is_slim else {ORDER_BY_KEY: GoogleFields.MODIFIED_TIME.value}),
    ):
        yield file


def crawl_folders_for_files(
    service: Resource,
    parent_id: str,
    is_slim: bool,
    user_email: str,
    traversed_parent_ids: set[str],
    update_traversed_ids_func: Callable[[str], None],
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[RetrievedDriveFile]:
    """
    This function starts crawling from any folder. It is slower though.
    """
    logger.info("Entered crawl_folders_for_files with parent_id: " + parent_id)
    if parent_id not in traversed_parent_ids:
        logger.info("Parent id not in traversed parent ids, getting files")
        found_files = False
        file = {}
        try:
            for file in _get_files_in_parent(
                service=service,
                parent_id=parent_id,
                is_slim=is_slim,
                start=start,
                end=end,
            ):
                logger.info(f"Found file: {file['name']}, user email: {user_email}")
                found_files = True
                yield RetrievedDriveFile(
                    drive_file=file,
                    user_email=user_email,
                    parent_id=parent_id,
                    completion_stage=DriveRetrievalStage.FOLDER_FILES,
                )
            # Only mark a folder as done if it was fully traversed without errors
            # This usually indicates that the owner of the folder was impersonated.
            # In cases where this never happens, most likely the folder owner is
            # not part of the google workspace in question (or for oauth, the authenticated
            # user doesn't own the folder)
            if found_files:
                update_traversed_ids_func(parent_id)
        except Exception as e:
            if isinstance(e, HttpError) and e.status_code == 403:
                # don't yield an error here because this is expected behavior
                # when a user doesn't have access to a folder
                logger.debug(f"Error getting files in parent {parent_id}: {e}")
            else:
                logger.error(f"Error getting files in parent {parent_id}: {e}")
                yield RetrievedDriveFile(
                    drive_file=file,
                    user_email=user_email,
                    parent_id=parent_id,
                    completion_stage=DriveRetrievalStage.FOLDER_FILES,
                    error=e,
                )
    else:
        logger.info(f"Skipping subfolder files since already traversed: {parent_id}")

    for subfolder in _get_folders_in_parent(
        service=service,
        parent_id=parent_id,
    ):
        logger.info("Fetching all files in subfolder: " + subfolder["name"])
        yield from crawl_folders_for_files(
            service=service,
            parent_id=subfolder["id"],
            is_slim=is_slim,
            user_email=user_email,
            traversed_parent_ids=traversed_parent_ids,
            update_traversed_ids_func=update_traversed_ids_func,
            start=start,
            end=end,
        )


def get_files_in_shared_drive(
    service: Resource,
    drive_id: str,
    is_slim: bool,
    update_traversed_ids_func: Callable[[str], None] = lambda _: None,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[GoogleDriveFileType]:
    kwargs = {}
    if not is_slim:
        kwargs[ORDER_BY_KEY] = GoogleFields.MODIFIED_TIME.value

    # If we know we are going to folder crawl later, we can cache the folders here
    # Get all folders being queried and add them to the traversed set
    folder_query = f"mimeType = '{DRIVE_FOLDER_TYPE}'"
    folder_query += " and trashed = false"
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

    # Get all files in the shared drive
    file_query = f"mimeType != '{DRIVE_FOLDER_TYPE}'"
    file_query += " and trashed = false"
    file_query += generate_time_range_filter(start, end)

    for file in execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        continue_on_404_or_403=True,
        corpora="drive",
        driveId=drive_id,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields=SLIM_FILE_FIELDS if is_slim else FILE_FIELDS,
        q=file_query,
        **kwargs,
    ):
        # If we found any files, mark this drive as traversed. When a user has access to a drive,
        # they have access to all the files in the drive. Also not a huge deal if we re-traverse
        # empty drives.
        # NOTE: ^^ the above is not actually true due to folder restrictions:
        # https://support.google.com/a/users/answer/12380484?hl=en
        # So we may have to change this logic for people who use folder restrictions.
        update_traversed_ids_func(drive_id)
        yield file


def get_all_files_in_my_drive_and_shared(
    service: GoogleDriveService,
    update_traversed_ids_func: Callable,
    is_slim: bool,
    include_shared_with_me: bool,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[GoogleDriveFileType]:
    kwargs = {}
    if not is_slim:
        kwargs[ORDER_BY_KEY] = GoogleFields.MODIFIED_TIME.value

    # If we know we are going to folder crawl later, we can cache the folders here
    # Get all folders being queried and add them to the traversed set
    folder_query = f"mimeType = '{DRIVE_FOLDER_TYPE}'"
    folder_query += " and trashed = false"
    if not include_shared_with_me:
        folder_query += " and 'me' in owners"
    found_folders = False
    for folder in execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        corpora="user",
        fields=SLIM_FILE_FIELDS if is_slim else FILE_FIELDS,
        q=folder_query,
    ):
        update_traversed_ids_func(folder[GoogleFields.ID])
        found_folders = True
    if found_folders:
        update_traversed_ids_func(get_root_folder_id(service))

    # Then get the files
    file_query = f"mimeType != '{DRIVE_FOLDER_TYPE}'"
    file_query += " and trashed = false"
    if not include_shared_with_me:
        file_query += " and 'me' in owners"
    file_query += generate_time_range_filter(start, end)
    yield from execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        continue_on_404_or_403=False,
        corpora="user",
        fields=SLIM_FILE_FIELDS if is_slim else FILE_FIELDS,
        q=file_query,
        **kwargs,
    )


def get_all_files_for_oauth(
    service: GoogleDriveService,
    include_files_shared_with_me: bool,
    include_my_drives: bool,
    # One of the above 2 should be true
    include_shared_drives: bool,
    is_slim: bool,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[GoogleDriveFileType]:
    kwargs = {}
    if not is_slim:
        kwargs[ORDER_BY_KEY] = GoogleFields.MODIFIED_TIME.value

    should_get_all = (
        include_shared_drives and include_my_drives and include_files_shared_with_me
    )
    corpora = "allDrives" if should_get_all else "user"

    file_query = f"mimeType != '{DRIVE_FOLDER_TYPE}'"
    file_query += " and trashed = false"
    file_query += generate_time_range_filter(start, end)

    if not should_get_all:
        if include_files_shared_with_me and not include_my_drives:
            file_query += " and not 'me' in owners"
        if not include_files_shared_with_me and include_my_drives:
            file_query += " and 'me' in owners"

    yield from execute_paginated_retrieval(
        retrieval_function=service.files().list,
        list_key="files",
        continue_on_404_or_403=False,
        corpora=corpora,
        includeItemsFromAllDrives=should_get_all,
        supportsAllDrives=should_get_all,
        fields=SLIM_FILE_FIELDS if is_slim else FILE_FIELDS,
        q=file_query,
        **kwargs,
    )


# Just in case we need to get the root folder id
def get_root_folder_id(service: Resource) -> str:
    # we dont paginate here because there is only one root folder per user
    # https://developers.google.com/drive/api/guides/v2-to-v3-reference
    return (
        service.files()
        .get(fileId="root", fields=GoogleFields.ID.value)
        .execute()[GoogleFields.ID.value]
    )
