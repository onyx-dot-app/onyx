from collections.abc import Callable
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
    GoogleDriveFileType,
)
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
)
from onyx.connectors.google_utils.google_utils import GoogleFields
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
    "permissionIds, webViewLink, owners(emailAddress), createdTime, modifiedTime, size)"
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


def owner_email(drive_file: GoogleDriveFileType) -> str | None:
    """Lowercased owner of a My Drive file. Drive allows one owner; shared
    drive files have none."""
    owners = drive_file.get("owners") or []
    if not owners:
        return None
    email = owners[0].get("emailAddress")
    return email.lower() if isinstance(email, str) else None


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


def get_fields_for_file_type(field_type: DriveFileFieldType) -> str:
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
    return _extract_single_file_fields(get_fields_for_file_type(field_type))


# Set on a shortcut's resolved target, holding the shortcut's id.
RESOLVED_FROM_SHORTCUT_KEY = "onyxResolvedFromShortcutId"
# Set on a shortcut's resolved target, holding the target's own modifiedTime.
# The target's modifiedTime field holds the shortcut's time.
TARGET_MODIFIED_TIME_KEY = "onyxTargetModifiedTime"


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


def resolve_file_or_shortcut(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    file: GoogleDriveFileType,
    field_type: DriveFileFieldType,
) -> GoogleDriveFileType | None:
    if not _is_drive_shortcut(file):
        return file

    target = resolve_shortcut(ops, user_email, file, field_type)
    if target is None or target.get("mimeType") == DRIVE_FOLDER_TYPE:
        return None
    return target


def resolve_shortcut(
    ops: GoogleDriveSourceOperations,
    user_email: str,
    shortcut: GoogleDriveFileType,
    field_type: DriveFileFieldType,
) -> GoogleDriveFileType | None:
    """The target of a shortcut, a file or a folder, read with the fields of
    ``field_type``. None when the user cannot read it. A file target gets
    the shortcut's modifiedTime and a mark that a shortcut reached it."""
    target = _resolve_shortcut_target(
        ops=ops,
        user_email=user_email,
        shortcut=shortcut,
        target_fields=_get_single_file_fields(field_type),
    )
    if target is None or target.get("mimeType") == DRIVE_FOLDER_TYPE:
        return target

    logger.debug(
        "Resolved Drive shortcut %s to target %s",
        shortcut.get("id"),
        target.get("id"),
    )
    # Use the shortcut's own modifiedTime: listings are filtered and ordered by
    # it, so this preserves the invariant that a retrieved item's modifiedTime
    # lies within the requested time range — the target's can sit far outside
    # it, which would corrupt the checkpoint frontier and re-poll windows.
    # The target's own time stays under a separate key: it says if the
    # listing of the target's own partition returns the target.
    target[TARGET_MODIFIED_TIME_KEY] = target.get(GoogleFields.MODIFIED_TIME.value)
    listing_modified_time = shortcut.get(GoogleFields.MODIFIED_TIME.value)
    if listing_modified_time is not None:
        target[GoogleFields.MODIFIED_TIME.value] = listing_modified_time
    # The target now looks like any listed file; record where it came from so
    # partitioned retrieval does not count it as part of the listing's scope.
    target[RESOLVED_FROM_SHORTCUT_KEY] = shortcut.get("id")
    return target


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
