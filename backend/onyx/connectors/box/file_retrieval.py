from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime

from box_sdk_gen.client import BoxClient
from box_sdk_gen.schemas import File as BoxFile
from box_sdk_gen.schemas import Folder as BoxFolder

from onyx.connectors.box.constants import BOX_API_MAX_ITEMS_PER_PAGE
from onyx.connectors.box.models import BoxFileType
from onyx.connectors.box.models import BoxRetrievalStage
from onyx.connectors.box.models import RetrievedBoxFile
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _should_include_file_by_time(
    file_dict: BoxFileType,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> bool:
    """Check if a file should be included based on its modified time."""
    if start is None and end is None:
        return True

    modified_time = file_dict.get("modified_at")
    if not modified_time:
        return True  # Include files without timestamps

    try:
        mod_dt = datetime.fromisoformat(modified_time.replace("Z", "+00:00"))
        mod_ts = mod_dt.timestamp()
        if start is not None and mod_ts < start:
            logger.debug(
                f"Skipping file {file_dict.get('name')} - "
                f"modified {mod_ts} < start {start}"
            )
            return False
        if end is not None and mod_ts > end:
            logger.debug(
                f"Skipping file {file_dict.get('name')} - "
                f"modified {mod_ts} > end {end}"
            )
            return False
        return True
    except (ValueError, AttributeError):
        return True  # Include files with invalid timestamps


def _box_file_to_dict(file: BoxFile | BoxFolder) -> BoxFileType:
    """Convert Box SDK file/folder object to dictionary."""

    # Helper to safely convert datetime or string to ISO format
    def to_iso_string(dt_or_str):
        if dt_or_str is None:
            return None
        if isinstance(dt_or_str, str):
            return dt_or_str
        if hasattr(dt_or_str, "isoformat"):
            return dt_or_str.isoformat()
        return str(dt_or_str)

    # Helper to safely get parent ID
    def get_parent_id(parent):
        if parent is None:
            return None
        if isinstance(parent, dict):
            return {"id": parent.get("id")} if parent.get("id") else None
        if hasattr(parent, "id"):
            return {"id": parent.id}
        return None

    return {
        "id": file.id,
        "name": file.name,
        "type": file.type.value if hasattr(file.type, "value") else str(file.type),
        "modified_at": (
            to_iso_string(file.modified_at)
            if hasattr(file, "modified_at") and file.modified_at
            else None
        ),
        "created_at": (
            to_iso_string(file.created_at)
            if hasattr(file, "created_at") and file.created_at
            else None
        ),
        "size": file.size if hasattr(file, "size") and file.size is not None else 0,
        "parent": (
            get_parent_id(file.parent)
            if hasattr(file, "parent") and file.parent
            else None
        ),
        "shared_link": (
            file.shared_link.url
            if hasattr(file, "shared_link") and file.shared_link
            else None
        ),
    }


def _get_folders_in_parent(
    client: BoxClient,
    parent_id: str = "0",  # "0" is root folder in Box
) -> Iterator[BoxFileType]:
    """Get all folders in a parent folder."""
    logger.info(f"Getting folders in parent {parent_id}")
    try:
        limit = BOX_API_MAX_ITEMS_PER_PAGE
        marker: str | None = None
        total_folders = 0
        page_num = 0

        while True:
            page_num += 1
            items = client.folders.get_folder_items(
                folder_id=parent_id,
                fields=["id", "name", "type", "modified_at", "created_at", "parent"],
                limit=limit,
                marker=marker,
            )
            logger.debug(
                f"Box API page {page_num} for parent {parent_id}: {len(items.entries)} items"
            )

            for item in items.entries:
                if item.type.value == "folder":
                    total_folders += 1
                    logger.debug(
                        f"Found folder in parent {parent_id}: {item.name} (id: {item.id})"
                    )
                    yield _box_file_to_dict(item)

            # Box API pagination: check if there are more pages
            # Box markers are opaque tokens and must come from next_marker.
            # Using item IDs as markers can cause duplicates, skipped items, or infinite loops.
            next_marker = getattr(items, "next_marker", None)
            if next_marker:
                marker = next_marker
            elif items.entries and len(items.entries) == limit:
                # Box API should always provide next_marker when there are more pages.
                # If it doesn't, we cannot safely continue pagination.
                logger.error(
                    f"Box API did not return next_marker for parent {parent_id} despite full page. "
                    f"Stopping pagination to avoid duplicates or infinite loops. "
                    f"This may indicate a Box API issue or incomplete data retrieval."
                )
                break
            else:
                break

        logger.info(f"Found {total_folders} folders in parent {parent_id}")
    except Exception as e:
        # Sanitize error message to avoid leaking sensitive data (URLs, tokens, etc.)
        import re

        error_str = str(e)
        # Remove URLs
        error_str = re.sub(r"https?://[^\s]+", "[URL_REDACTED]", error_str)
        # Remove potential tokens (long alphanumeric strings)
        error_str = re.sub(r"\b[a-zA-Z0-9]{32,}\b", "[TOKEN_REDACTED]", error_str)
        logger.warning(f"Error getting folders in parent {parent_id}: {error_str}")
        # Continue on error, similar to Google Drive behavior


def _get_files_in_parent(
    client: BoxClient,
    parent_id: str = "0",
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[BoxFileType]:
    """Get all files in a parent folder."""
    logger.info(f"Getting files in parent {parent_id} (start={start}, end={end})")
    try:
        # Box API pagination: uses limit and marker (last item ID from previous page)
        limit = BOX_API_MAX_ITEMS_PER_PAGE
        marker: str | None = None
        total_files = 0
        page_num = 0

        while True:
            page_num += 1
            items = client.folders.get_folder_items(
                folder_id=parent_id,
                fields=[
                    "id",
                    "name",
                    "type",
                    "modified_at",
                    "created_at",
                    "size",
                    "parent",
                    "shared_link",
                ],
                limit=limit,
                marker=marker,
            )

            logger.debug(
                f"Box API page {page_num} for parent {parent_id}: {len(items.entries)} items"
            )

            for item in items.entries:
                if item.type.value == "file":
                    file_dict = _box_file_to_dict(item)
                    if not _should_include_file_by_time(file_dict, start, end):
                        continue
                    total_files += 1
                    yield file_dict

            # Box API pagination: check if there are more pages
            # The Box API response should have a next_marker field when there are more pages
            # Box markers are opaque tokens and must come from next_marker.
            # Using item IDs as markers can cause duplicates, skipped items, or infinite loops.
            next_marker = getattr(items, "next_marker", None)
            if next_marker:
                # Use the API-provided next_marker token for the next page
                marker = next_marker
            elif items.entries and len(items.entries) == limit:
                # Box API should always provide next_marker when there are more pages.
                # If it doesn't, we cannot safely continue pagination.
                logger.error(
                    f"Box API did not return next_marker for parent {parent_id} despite full page. "
                    f"Stopping pagination to avoid duplicates or infinite loops. "
                    f"This may indicate a Box API issue or incomplete data retrieval."
                )
                break
            else:
                break

        logger.info(f"Found {total_files} files in parent {parent_id}")

    except Exception as e:
        # Sanitize error message to avoid leaking sensitive data (URLs, tokens, etc.)
        import re

        error_str = str(e)
        # Remove URLs
        error_str = re.sub(r"https?://[^\s]+", "[URL_REDACTED]", error_str)
        # Remove potential tokens (long alphanumeric strings)
        error_str = re.sub(r"\b[a-zA-Z0-9]{32,}\b", "[TOKEN_REDACTED]", error_str)
        logger.warning(f"Error getting files in parent {parent_id}: {error_str}")


def crawl_folders_for_files(
    client: BoxClient,
    parent_id: str,
    user_id: str,
    traversed_parent_ids: set[str],
    update_traversed_ids_func: Callable[[str], None],
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> Iterator[RetrievedBoxFile]:
    """
    Recursively crawl folders to get all files.
    This function starts crawling from any folder.
    """
    logger.debug(f"Crawling folder {parent_id}")
    if parent_id not in traversed_parent_ids:
        try:
            files_yielded = 0
            for file_dict in _get_files_in_parent(
                client=client,
                parent_id=parent_id,
                start=start,
                end=end,
            ):
                logger.debug(f"Found file: {file_dict.get('name')}")
                yield RetrievedBoxFile(
                    box_file=file_dict,
                    user_id=user_id,
                    parent_id=parent_id,
                    completion_stage=BoxRetrievalStage.FOLDER_FILES,
                )
                files_yielded += 1
            # Mark folder as traversed only after successfully processing all files
            # (even if no files were found, to avoid re-processing empty folders)
            # Only mark as traversed if we completed without exceptions
            update_traversed_ids_func(parent_id)
            logger.debug(
                f"Successfully traversed folder {parent_id}, found {files_yielded} files"
            )
        except Exception as e:
            # Sanitize error message to avoid leaking sensitive data (URLs, tokens, etc.)
            import re

            error_str = str(e)
            # Remove URLs
            error_str = re.sub(r"https?://[^\s]+", "[URL_REDACTED]", error_str)
            # Remove potential tokens (long alphanumeric strings)
            error_str = re.sub(r"\b[a-zA-Z0-9]{32,}\b", "[TOKEN_REDACTED]", error_str)
            logger.error(
                f"Error getting files in parent {parent_id}: {error_str}. "
                f"Folder will not be marked as traversed and may be retried in future crawls."
            )
            # Do NOT mark folder as traversed when file listing aborts on error
            # This allows the folder to be retried in future crawls
            yield RetrievedBoxFile(
                box_file={},
                user_id=user_id,
                parent_id=parent_id,
                completion_stage=BoxRetrievalStage.FOLDER_FILES,
                error=e,
            )
    else:
        logger.debug(f"Skipping folder {parent_id} (already traversed)")

    # Recursively process subfolders
    for folder_dict in _get_folders_in_parent(client=client, parent_id=parent_id):
        folder_id = folder_dict.get("id")
        if folder_id:
            logger.debug(f"Recursively crawling subfolder: {folder_dict.get('name')}")
            yield from crawl_folders_for_files(
                client=client,
                parent_id=folder_id,
                user_id=user_id,
                traversed_parent_ids=traversed_parent_ids,
                update_traversed_ids_func=update_traversed_ids_func,
                start=start,
                end=end,
            )


def get_all_files_in_folder(
    client: BoxClient,
    folder_id: str = "0",
    user_id: str = "me",
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
    marker: str | None = None,
) -> Iterator[RetrievedBoxFile | str]:
    """
    Get all files in a folder (non-recursive).
    Returns RetrievedBoxFile objects or a marker string for pagination.
    """
    logger.info(
        f"Getting files in folder {folder_id} (user: {user_id}, "
        f"start={start}, end={end}, marker={marker})"
    )
    try:
        limit = BOX_API_MAX_ITEMS_PER_PAGE
        current_marker = marker
        total_files = 0
        page_num = 0

        while True:
            page_num += 1
            items = client.folders.get_folder_items(
                folder_id=folder_id,
                fields=[
                    "id",
                    "name",
                    "type",
                    "modified_at",
                    "created_at",
                    "size",
                    "parent",
                    "shared_link",
                ],
                limit=limit,
                marker=current_marker,
            )

            logger.info(
                f"Box API returned {len(items.entries)} items for folder {folder_id} "
                f"(page {page_num}, marker={current_marker})"
            )

            for item in items.entries:
                logger.debug(
                    f"Found item in folder {folder_id}: type={item.type.value}, "
                    f"name={item.name if hasattr(item, 'name') else 'N/A'}"
                )
                if item.type.value == "file":
                    file_dict = _box_file_to_dict(item)
                    # Apply time filter
                    if not _should_include_file_by_time(file_dict, start, end):
                        continue

                    total_files += 1
                    logger.debug(f"Yielding file: {file_dict.get('name')}")
                    yield RetrievedBoxFile(
                        box_file=file_dict,
                        user_id=user_id,
                        parent_id=folder_id,
                        completion_stage=BoxRetrievalStage.FOLDER_FILES,
                    )

            # Box API pagination: check if there are more pages
            # The Box API response should have a next_marker field when there are more pages
            # Box markers are opaque tokens and must come from next_marker.
            # Using item IDs as markers can cause duplicates, skipped items, or infinite loops.
            next_marker = getattr(items, "next_marker", None)
            if next_marker:
                # Use the API-provided next_marker token for the next page
                current_marker = next_marker
                logger.debug(
                    f"More pages available for folder {folder_id}, next_marker: {current_marker}"
                )
                yield current_marker  # Yield marker for checkpoint resumption
                break
            elif items.entries and len(items.entries) == limit:
                # Box API should always provide next_marker when there are more pages.
                # If it doesn't, we cannot safely continue pagination.
                logger.error(
                    f"Box API did not return next_marker for folder {folder_id} despite full page. "
                    f"Stopping pagination to avoid duplicates or infinite loops. "
                    f"This may indicate a Box API issue or incomplete data retrieval."
                )
                # Don't yield a marker - we can't safely continue
                break
            else:
                # No more pages
                break

        logger.info(f"Found {total_files} files in folder {folder_id}")

    except Exception as e:
        # Sanitize error message to avoid leaking sensitive data (URLs, tokens, etc.)
        error_str = str(e)
        # Remove potential URLs and tokens from error message
        import re

        # Remove URLs
        error_str = re.sub(r"https?://[^\s]+", "[URL_REDACTED]", error_str)
        # Remove potential tokens (long alphanumeric strings)
        error_str = re.sub(r"\b[a-zA-Z0-9]{32,}\b", "[TOKEN_REDACTED]", error_str)
        logger.error(f"Error getting all files in folder {folder_id}: {error_str}")
        yield RetrievedBoxFile(
            box_file={},
            user_id=user_id,
            parent_id=folder_id,
            completion_stage=BoxRetrievalStage.FOLDER_FILES,
            error=e,
        )
