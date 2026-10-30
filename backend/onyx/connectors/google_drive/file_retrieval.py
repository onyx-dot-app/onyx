from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from enum import Enum
from typing import cast
from urllib.parse import parse_qs, urlparse

from onyx.access.models import ExternalAccess
from onyx.connectors.google_drive.constants import (
    DRIVE_FOLDER_TYPE,
    DRIVE_SHORTCUT_TYPE,
)
from onyx.connectors.google_drive.models import (
    DriveBatchResult,
    DriveRetrievalStage,
    GoogleDriveFileType,
    RetrievedDriveFile,
)
from onyx.connectors.google_drive.source_operations import (
    DriveCorpus,
    GoogleDriveHttpError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.google_utils.google_utils import GoogleFields
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
    noop_fallback,
)

logger = setup_logger()


class DriveFileFieldType(Enum):
    """Enum to specify which fields to retrieve from Google Drive files"""

    SLIM = "slim"  # Minimal fields for basic file info
    STANDARD = "standard"  # Standard fields including content metadata
    WITH_PERMISSIONS = "with_permissions"  # Full fields including permissions


# `role` is needed to pick a shared drive organizer, who is the one principal
# guaranteed to see every item in that drive.
PERMISSION_FULL_DESCRIPTION = (
    "permissions(id, emailAddress, type, domain, allowFileDiscovery, role, "
    "permissionDetails)"
)
FILE_FIELDS = (
    "nextPageToken, files(mimeType, id, name, driveId, parents, "
    "createdTime, modifiedTime, webViewLink, shortcutDetails, owners(emailAddress), size)"
)
FILE_FIELDS_WITH_PERMISSIONS = (
    f"nextPageToken, files(mimeType, id, name, driveId, parents, {PERMISSION_FULL_DESCRIPTION}, permissionIds, "
    "createdTime, modifiedTime, webViewLink, shortcutDetails, owners(emailAddress), size)"
)
SLIM_FILE_FIELDS = (
    f"nextPageToken, files(mimeType, driveId, id, name, parents, {PERMISSION_FULL_DESCRIPTION}, "
    "permissionIds, webViewLink, owners(emailAddress), createdTime, modifiedTime)"
)
FOLDER_FIELDS = (
    "nextPageToken, files(id, name, mimeType, permissions, modifiedTime, webViewLink, "
    "shortcutDetails)"
)
SHORTCUT_FIELDS = (
    "id, name, mimeType, shortcutDetails(targetId,targetMimeType,targetResourceKey)"
)

HIERARCHY_FIELDS = "id, name, parents, webViewLink, mimeType, driveId"

HIERARCHY_FIELDS_WITH_PERMISSIONS = (
    "id, name, parents, webViewLink, mimeType, permissionIds, driveId"
)


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


LINK_ONLY_PERMISSION_TYPES = {"domain", "anyone"}


def has_link_only_permission(file: GoogleDriveFileType) -> bool:
    """
    Return True if any permission requires a direct link to access
    (allowFileDiscovery is explicitly false for supported types).
    """
    permissions = file.get("permissions") or []
    for permission in permissions:
        if permission.get("type") not in LINK_ONLY_PERMISSION_TYPES:
            continue
        if permission.get("allowFileDiscovery") is False:
            return True
    return False


def files_only(
    items: Iterator[GoogleDriveFileType | str],
) -> Iterator[GoogleDriveFileType]:
    """The files of a listing made without ``max_num_pages``, which yields no
    page token."""
    for item in items:
        if isinstance(item, str):
            raise RuntimeError("Bug: an unbounded listing yielded a page token.")
        yield item


def _get_folders_in_parent(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    parent_id: str | None = None,
) -> Iterator[GoogleDriveFileType]:
    query = f"(mimeType = '{DRIVE_FOLDER_TYPE}' or mimeType = '{DRIVE_SHORTCUT_TYPE}')"
    query += " and trashed = false"

    if parent_id:
        query += f" and '{parent_id}' in parents"

    for file in files_only(
        ops.list_files(
            variant=DriveCorpus.ALL_DRIVES,
            user_email=user_email,
            query=query,
            fields=FOLDER_FIELDS,
            continue_on_404_or_403=True,
        )
    ):
        folder = _resolve_folder_or_shortcut(ops, user_email, file)
        if folder:
            yield folder


def get_folder_metadata(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    folder_id: str,
    field_type: DriveFileFieldType,
) -> GoogleDriveFileType | None:
    """Fetch metadata for a folder by ID, or None if the user cannot see it."""
    return ops.get_file(
        user_email=user_email,
        file_id=folder_id,
        fields=_get_hierarchy_fields_for_file_type(field_type),
    )


def _get_hierarchy_fields_for_file_type(field_type: DriveFileFieldType) -> str:
    if field_type == DriveFileFieldType.WITH_PERMISSIONS:
        return HIERARCHY_FIELDS_WITH_PERMISSIONS
    else:
        return HIERARCHY_FIELDS


def get_external_access_for_folder(
    folder: GoogleDriveFileType,
    google_domain: str,
    ops: GoogleDriveSourceOperations,
    user_email: str,
    add_prefix: bool = False,
) -> ExternalAccess:
    """
    Extract ExternalAccess from a folder's permissions.

    This fetches permissions using the Drive API (via permissionIds) and extracts
    user emails, group emails, and public access status.

    Uses the EE implementation if available, otherwise returns public access
    (fallback for non-EE deployments).

    Args:
        folder: The folder metadata from Google Drive API (must include permissionIds field)
        google_domain: The company's Google Workspace domain (e.g., "company.com")
        ops: The gateway that fetches the permission details
        user_email: The user to read the permissions as
        add_prefix: When True, prefix group IDs with source type (for indexing path).
                   When False (default), leave unprefixed (for permission sync path
                   where upsert_document_external_perms handles prefixing).

    Returns:
        ExternalAccess with extracted permission info
    """
    # Try to get the EE implementation
    get_folder_access_fn = cast(
        Callable[
            [GoogleDriveFileType, str, GoogleDriveSourceOperations, str, bool],
            ExternalAccess,
        ],
        fetch_versioned_implementation_with_fallback(
            "onyx.external_permissions.google_drive.doc_sync",
            "get_external_access_for_folder",
            noop_fallback,
        ),
    )

    return get_folder_access_fn(folder, google_domain, ops, user_email, add_prefix)


def _get_fields_for_file_type(field_type: DriveFileFieldType) -> str:
    """Get the appropriate fields string for files().list() based on the field type enum."""
    if field_type == DriveFileFieldType.SLIM:
        return SLIM_FILE_FIELDS
    elif field_type == DriveFileFieldType.WITH_PERMISSIONS:
        return FILE_FIELDS_WITH_PERMISSIONS
    else:  # DriveFileFieldType.STANDARD
        return FILE_FIELDS


def _extract_single_file_fields(list_fields: str) -> str:
    """Convert a files().list() fields string to one suitable for files().get().

    List fields look like "nextPageToken, files(field1, field2, ...)"
    Single-file fields should be just "field1, field2, ..."
    """
    start = list_fields.find("files(")
    if start == -1:
        return list_fields
    inner_start = start + len("files(")
    inner_end = list_fields.rfind(")")
    return list_fields[inner_start:inner_end]


def _get_single_file_fields(field_type: DriveFileFieldType) -> str:
    """Get the appropriate fields string for files().get() based on the field type enum."""
    return _extract_single_file_fields(_get_fields_for_file_type(field_type))


# Set on a shortcut's resolved target, holding the shortcut's id.
RESOLVED_FROM_SHORTCUT_KEY = "onyxResolvedFromShortcutId"


def _is_drive_shortcut(file: GoogleDriveFileType) -> bool:
    return file.get("mimeType") == DRIVE_SHORTCUT_TYPE


def _get_shortcut_details(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    shortcut: GoogleDriveFileType,
) -> dict[str, str] | None:
    existing_details = shortcut.get("shortcutDetails")
    if isinstance(existing_details, dict) and existing_details.get("targetId"):
        return cast(dict[str, str], existing_details)

    shortcut_id = shortcut.get("id")
    if not isinstance(shortcut_id, str):
        logger.debug("Skipping shortcut without id: %s", shortcut.get("name"))
        return None

    shortcut_file = ops.get_file(
        user_email=user_email, file_id=shortcut_id, fields=SHORTCUT_FIELDS
    )
    if not shortcut_file:
        return None

    shortcut_details = shortcut_file.get("shortcutDetails")
    if isinstance(shortcut_details, dict) and shortcut_details.get("targetId"):
        return cast(dict[str, str], shortcut_details)

    logger.debug("Skipping shortcut without target metadata: %s", shortcut_id)
    return None


def _resolve_shortcut_target(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    shortcut: GoogleDriveFileType,
    target_fields: str,
) -> GoogleDriveFileType | None:
    details = _get_shortcut_details(ops, user_email, shortcut)
    if details is None:
        return None

    return ops.get_file(
        user_email=user_email,
        file_id=details["targetId"],
        fields=target_fields,
        resource_key=details.get("targetResourceKey"),
    )


def _resolve_file_or_shortcut(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    file: GoogleDriveFileType,
    field_type: DriveFileFieldType,
) -> GoogleDriveFileType | None:
    if not _is_drive_shortcut(file):
        return file

    target = _resolve_shortcut_target(
        ops=ops,
        user_email=user_email,
        shortcut=file,
        target_fields=_get_single_file_fields(field_type),
    )
    if target is None or target.get("mimeType") == DRIVE_FOLDER_TYPE:
        return None

    logger.debug(
        "Resolved Drive shortcut %s to target %s", file.get("id"), target.get("id")
    )
    # Use the shortcut's own modifiedTime: listings are filtered and ordered by
    # it, so this preserves the invariant that a retrieved item's modifiedTime
    # lies within the requested time range — the target's can sit far outside
    # it, which would corrupt the checkpoint frontier and re-poll windows.
    listing_modified_time = file.get(GoogleFields.MODIFIED_TIME.value)
    if listing_modified_time is not None:
        target[GoogleFields.MODIFIED_TIME.value] = listing_modified_time
    # The target now looks like any listed file; record where it came from so
    # partitioned retrieval does not count it as part of the listing's scope.
    target[RESOLVED_FROM_SHORTCUT_KEY] = file.get("id")
    return target


def _resolve_folder_or_shortcut(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    file: GoogleDriveFileType,
) -> GoogleDriveFileType | None:
    if not _is_drive_shortcut(file):
        return file

    target = _resolve_shortcut_target(
        ops=ops,
        user_email=user_email,
        shortcut=file,
        target_fields=HIERARCHY_FIELDS,
    )
    if target is None or target.get("mimeType") != DRIVE_FOLDER_TYPE:
        return None

    logger.debug(
        "Resolved Drive folder shortcut %s to target %s",
        file.get("id"),
        target.get("id"),
    )
    return target


def _resolve_file_shortcuts(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    files: Iterator[GoogleDriveFileType | str],
    field_type: DriveFileFieldType,
) -> Iterator[GoogleDriveFileType | str]:
    for file in files:
        if isinstance(file, str):
            yield file
            continue

        resolved_file = _resolve_file_or_shortcut(ops, user_email, file, field_type)
        if resolved_file is not None:
            yield resolved_file


def _get_files_in_parent(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    parent_id: str,
    field_type: DriveFileFieldType,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[GoogleDriveFileType]:
    query = f"mimeType != '{DRIVE_FOLDER_TYPE}' and '{parent_id}' in parents"
    query += " and trashed = false"
    query += generate_time_range_filter(start, end)

    for file in files_only(
        ops.list_files(
            variant=DriveCorpus.ALL_DRIVES,
            user_email=user_email,
            query=query,
            fields=_get_fields_for_file_type(field_type),
            order_by=GoogleFields.MODIFIED_TIME.value,
            continue_on_404_or_403=True,
        )
    ):
        resolved_file = _resolve_file_or_shortcut(ops, user_email, file, field_type)
        if resolved_file is not None:
            yield resolved_file


def crawl_folders_for_files(
    ops: GoogleDriveSourceOperations,
    parent_id: str,
    field_type: DriveFileFieldType,
    user_email: str,
    traversed_parent_ids: set[str],
    update_traversed_ids_func: Callable[[str], None],
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
    active_parent_ids: set[str] | None = None,
) -> Iterator[RetrievedDriveFile]:
    """
    This function starts crawling from any folder. It is slower though.
    """
    logger.info("Entered crawl_folders_for_files with parent_id: " + parent_id)
    if active_parent_ids is None:
        active_parent_ids = set()
    if parent_id in active_parent_ids:
        logger.info("Skipping folder cycle at parent_id: %s", parent_id)
        return

    active_parent_ids.add(parent_id)
    try:
        if parent_id not in traversed_parent_ids:
            logger.info("Parent id not in traversed parent ids, getting files")
            found_files = False
            file = {}
            try:
                for file in _get_files_in_parent(
                    ops=ops,
                    user_email=user_email,
                    parent_id=parent_id,
                    field_type=field_type,
                    start=start,
                    end=end,
                ):
                    logger.info(
                        "Found file: %s, user email: %s", file["name"], user_email
                    )
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
                if isinstance(e, GoogleDriveHttpError) and e.status_code == 403:
                    # don't yield an error here because this is expected behavior
                    # when a user doesn't have access to a folder
                    logger.debug("Error getting files in parent %s: %s", parent_id, e)
                else:
                    logger.error("Error getting files in parent %s: %s", parent_id, e)
                    yield RetrievedDriveFile(
                        drive_file=file,
                        user_email=user_email,
                        parent_id=parent_id,
                        completion_stage=DriveRetrievalStage.FOLDER_FILES,
                        error=e,
                    )
        else:
            logger.info(
                "Skipping files since parent is already traversed: %s", parent_id
            )

        for subfolder in _get_folders_in_parent(
            ops=ops,
            user_email=user_email,
            parent_id=parent_id,
        ):
            logger.info("Fetching all files in subfolder: " + subfolder["name"])
            yield from crawl_folders_for_files(
                ops=ops,
                parent_id=subfolder["id"],
                field_type=field_type,
                user_email=user_email,
                traversed_parent_ids=traversed_parent_ids,
                update_traversed_ids_func=update_traversed_ids_func,
                start=start,
                end=end,
                active_parent_ids=active_parent_ids,
            )
    finally:
        active_parent_ids.remove(parent_id)


def get_files_in_shared_drive(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    drive_id: str,
    field_type: DriveFileFieldType,
    max_num_pages: int,
    update_traversed_ids_func: Callable[[str], None] = lambda _: None,
    cache_folders: bool = True,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
    page_token: str | None = None,
) -> Iterator[GoogleDriveFileType | str]:
    if page_token:
        logger.info("Using page token: %s", page_token)

    if cache_folders:
        # If we know we are going to folder crawl later, we can cache the folders here
        # Get all folders being queried and add them to the traversed set
        folder_query = f"mimeType = '{DRIVE_FOLDER_TYPE}'"
        folder_query += " and trashed = false"
        for folder in files_only(
            ops.list_files(
                variant=DriveCorpus.DRIVE,
                user_email=user_email,
                drive_id=drive_id,
                query=folder_query,
                fields="nextPageToken, files(id)",
                continue_on_404_or_403=True,
            )
        ):
            update_traversed_ids_func(folder["id"])

    # Get all files in the shared drive
    file_query = f"mimeType != '{DRIVE_FOLDER_TYPE}'"
    file_query += " and trashed = false"
    file_query += generate_time_range_filter(start, end)

    for file in ops.list_files(
        variant=DriveCorpus.DRIVE,
        user_email=user_email,
        drive_id=drive_id,
        query=file_query,
        fields=_get_fields_for_file_type(field_type),
        order_by=GoogleFields.MODIFIED_TIME.value,
        page_token=page_token,
        max_num_pages=max_num_pages,
        continue_on_404_or_403=True,
    ):
        if isinstance(file, str):
            yield file
            continue

        resolved_file = _resolve_file_or_shortcut(ops, user_email, file, field_type)
        if resolved_file is None:
            continue
        # If we found any files, mark this drive as traversed. When a user has access to a drive,
        # they have access to all the files in the drive. Also not a huge deal if we re-traverse
        # empty drives.
        # NOTE: ^^ the above is not actually true due to folder restrictions:
        # https://support.google.com/a/users/answer/12380484?hl=en
        # So we may have to change this logic for people who use folder restrictions.
        update_traversed_ids_func(drive_id)
        yield resolved_file


def get_all_files_in_my_drive_and_shared(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    update_traversed_ids_func: Callable,
    field_type: DriveFileFieldType,
    include_shared_with_me: bool,
    max_num_pages: int,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
    cache_folders: bool = True,
    page_token: str | None = None,
) -> Iterator[GoogleDriveFileType | str]:
    if page_token:
        logger.info("Using page token: %s", page_token)

    if cache_folders:
        # If we know we are going to folder crawl later, we can cache the folders here
        # Get all folders being queried and add them to the traversed set
        folder_query = f"mimeType = '{DRIVE_FOLDER_TYPE}'"
        folder_query += " and trashed = false"
        if not include_shared_with_me:
            folder_query += " and 'me' in owners"
        found_folders = False
        for folder in files_only(
            ops.list_files(
                variant=DriveCorpus.USER,
                user_email=user_email,
                query=folder_query,
                fields=_get_fields_for_file_type(field_type),
            )
        ):
            update_traversed_ids_func(folder[GoogleFields.ID])
            found_folders = True
        if found_folders:
            update_traversed_ids_func(ops.get_root_folder_id(user_email=user_email))

    # Then get the files
    file_query = f"mimeType != '{DRIVE_FOLDER_TYPE}'"
    file_query += " and trashed = false"
    if not include_shared_with_me:
        file_query += " and 'me' in owners"
    file_query += generate_time_range_filter(start, end)
    yield from _resolve_file_shortcuts(
        ops,
        user_email,
        ops.list_files(
            variant=DriveCorpus.USER,
            user_email=user_email,
            query=file_query,
            fields=_get_fields_for_file_type(field_type),
            order_by=GoogleFields.MODIFIED_TIME.value,
            page_token=page_token,
            max_num_pages=max_num_pages,
        ),
        field_type,
    )


def get_all_files_for_oauth(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    include_files_shared_with_me: bool,
    include_my_drives: bool,
    # One of the above 2 should be true
    include_shared_drives: bool,
    field_type: DriveFileFieldType,
    max_num_pages: int,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
    page_token: str | None = None,
) -> Iterator[GoogleDriveFileType | str]:
    if page_token:
        logger.info("Using page token: %s", page_token)

    should_get_all = (
        include_shared_drives and include_my_drives and include_files_shared_with_me
    )
    corpus = DriveCorpus.ALL_DRIVES if should_get_all else DriveCorpus.USER

    file_query = f"mimeType != '{DRIVE_FOLDER_TYPE}'"
    file_query += " and trashed = false"
    file_query += generate_time_range_filter(start, end)

    if not should_get_all:
        if include_files_shared_with_me and not include_my_drives:
            file_query += " and not 'me' in owners"
        if not include_files_shared_with_me and include_my_drives:
            file_query += " and 'me' in owners"

    yield from _resolve_file_shortcuts(
        ops,
        user_email,
        ops.list_files(
            variant=corpus,
            user_email=user_email,
            query=file_query,
            fields=_get_fields_for_file_type(field_type),
            order_by=GoogleFields.MODIFIED_TIME.value,
            page_token=page_token,
            max_num_pages=max_num_pages,
        ),
        field_type,
    )


def _extract_file_id_from_web_view_link(web_view_link: str) -> str:
    parsed = urlparse(web_view_link)
    path_parts = [part for part in parsed.path.split("/") if part]

    if "d" in path_parts:
        idx = path_parts.index("d")
        if idx + 1 < len(path_parts):
            return path_parts[idx + 1]

    query_params = parse_qs(parsed.query)
    for key in ("id", "fileId"):
        value = query_params.get(key)
        if value and value[0]:
            return value[0]

    raise ValueError(
        f"Unable to extract Drive file id from webViewLink: {web_view_link}"
    )


def get_files_by_web_view_links_batch(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    web_view_links: list[str],
    field_type: DriveFileFieldType,
) -> DriveBatchResult:
    """Retrieve Google Drive files by webViewLink using the batch API.

    Returns the files that were read and an error for each link that could
    not be read.
    """
    file_ids_by_link: dict[str, str] = {}
    link_errors: dict[str, Exception] = {}
    for web_view_link in web_view_links:
        try:
            file_ids_by_link[web_view_link] = _extract_file_id_from_web_view_link(
                web_view_link
            )
        except ValueError as e:
            logger.warning("Failed to extract file ID from %s: %s", web_view_link, e)
            link_errors[web_view_link] = e

    result = ops.batch_get_files(
        user_email=user_email,
        file_ids_by_key=file_ids_by_link,
        fields=_get_single_file_fields(field_type),
    )
    result.errors.update(link_errors)
    return result
