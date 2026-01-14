import io
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from typing import cast
from urllib.parse import urlparse
from urllib.parse import urlunparse

from box_sdk_gen.client import BoxClient
from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.box.constants import BOX_DOWNLOAD_CHUNK_SIZE
from onyx.connectors.box.constants import BOX_FOLDER_TYPE
from onyx.connectors.box.constants import BOX_WEBLINK_BASE
from onyx.connectors.box.models import BoxFileType
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.extract_file_text import pptx_to_text
from onyx.file_processing.extract_file_text import read_docx_file
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.extract_file_text import xlsx_to_text
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)
from onyx.utils.variable_functionality import noop_fallback

logger = setup_logger()

CHUNK_SIZE_BUFFER = 64  # extra bytes past the limit to read


def _handle_box_download_error(file_id: str, error: Exception) -> bytes:
    """Handle Box download errors, logging appropriately based on error type."""
    from box_sdk_gen.box import BoxAPIError

    is_403 = False
    status_code = None

    # Check if it's a BoxAPIError with status code
    if isinstance(error, BoxAPIError):
        status_code = getattr(error, "status_code", None)
        if status_code == 403:
            is_403 = True
    else:
        # Check error message for 403 indicators
        error_message = str(error).lower()
        if (
            "403" in str(error)
            or "access_denied" in error_message
            or "insufficient permission" in error_message
        ):
            is_403 = True

    # Sanitize error message to avoid leaking sensitive data (URLs, tokens, etc.)
    error_str = str(error)
    # Remove potential URLs and tokens from error message
    import re

    # Remove URLs
    error_str = re.sub(r"https?://[^\s]+", "[URL_REDACTED]", error_str)
    # Remove potential tokens (long alphanumeric strings)
    error_str = re.sub(r"\b[a-zA-Z0-9]{32,}\b", "[TOKEN_REDACTED]", error_str)

    # Log based on error type
    if is_403:
        logger.warning(
            f"Permission denied (403) downloading Box file {file_id}. "
            f"This may be due to file-level permissions or Box app scope limitations. "
            f"Error: {error_str}"
        )
    else:
        logger.error(
            f"Failed to download Box file {file_id}"
            + (f" (status={status_code})" if status_code else "")
            + f": {error_str}"
        )

    return bytes()


class PermissionSyncContext(BaseModel):
    """
    This is the information that is needed to sync permissions for a document.
    """

    primary_user_id: str
    box_domain: str | None = None


def onyx_document_id_from_box_file(file: BoxFileType) -> str:
    """Generate Onyx document ID from Box file."""
    file_id = file.get("id")
    if not file_id:
        raise KeyError("Box file missing 'id' field.")

    # Construct Box web link
    # shared_link may be a string URL or an object with a 'url' attribute/key
    shared_link = file.get("shared_link")
    link = None
    if shared_link:
        if isinstance(shared_link, str):
            link = shared_link
        elif isinstance(shared_link, dict):
            # Extract URL from object
            link = shared_link.get("url")
        elif hasattr(shared_link, "url"):
            # Handle object with url attribute
            link = shared_link.url
        else:
            # Fallback: treat as string
            link = str(shared_link)

    if not link:
        link = f"{BOX_WEBLINK_BASE}{file_id}"

    # Normalize the URL
    parsed_url = urlparse(link)
    parsed_url = parsed_url._replace(query="")  # remove query parameters
    # Remove trailing slashes and normalize
    path = parsed_url.path.rstrip("/")
    parsed_url = parsed_url._replace(path=path)
    return urlunparse(parsed_url)


def download_box_file(client: BoxClient, file_id: str, size_threshold: int) -> bytes:
    """
    Download the file from Box.
    """
    download_stream = None
    try:
        # Box SDK v10 downloads files using download_file method
        # This returns a stream that we need to read
        download_stream = client.downloads.download_file(file_id=file_id)
        # Use list to collect chunks for O(n) performance instead of O(n²) with +=
        chunks: list[bytes] = []
        total_size = 0
        chunk_size = BOX_DOWNLOAD_CHUNK_SIZE

        # Read the stream in chunks
        while True:
            chunk = download_stream.read(chunk_size)
            if not chunk:
                break
            if isinstance(chunk, bytes):
                chunks.append(chunk)
                total_size += len(chunk)
            else:
                # Handle string chunks (shouldn't happen but be safe)
                chunk_bytes = chunk.encode("utf-8")
                chunks.append(chunk_bytes)
                total_size += len(chunk)

            if total_size > size_threshold:
                logger.warning(
                    f"File {file_id} exceeds size threshold of {size_threshold}. Skipping."
                )
                return bytes()

        # Join all chunks at once for O(n) performance
        return b"".join(chunks)
    except Exception as e:
        return _handle_box_download_error(file_id, e)
    finally:
        # Ensure stream is closed on all paths (success, exception, early return)
        if download_stream is not None:
            try:
                download_stream.close()
            except Exception as close_error:
                logger.warning(
                    f"Error closing download stream for file {file_id}: {close_error}"
                )


def _download_and_extract_sections(
    file: BoxFileType,
    client: BoxClient,
    allow_images: bool,
    size_threshold: int,
) -> list[TextSection | ImageSection]:
    """Extract text and images from a Box file."""
    file_id = file.get("id", "")
    file_name = file.get("name", "")
    file_type = file.get("type", "")
    # Handle shared_link as string or object
    shared_link = file.get("shared_link")
    if shared_link:
        if isinstance(shared_link, str):
            link = shared_link
        elif isinstance(shared_link, dict):
            link = shared_link.get("url")
        elif hasattr(shared_link, "url"):
            link = shared_link.url
        else:
            link = str(shared_link) if shared_link else None
    else:
        link = None
    if not link:
        link = f"{BOX_WEBLINK_BASE}{file_id}"

    # Skip folders
    if file_type == BOX_FOLDER_TYPE:
        logger.info("Skipping folder.")
        return []

    # Lazy evaluation to only download the file if necessary
    def response_call() -> bytes:
        return download_box_file(client, file_id, size_threshold)

    # Check file size
    file_size = file.get("size", 0)
    if file_size and file_size > size_threshold:
        logger.warning(
            f"{file_name} exceeds size threshold of {size_threshold}. Skipping."
        )
        return []

    # Get file extension for mime type detection
    file_ext = get_file_ext(file_name)

    # Handle images
    if file_ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]:
        if not allow_images:
            return []

        sections: list[TextSection | ImageSection] = []
        try:
            section, embedded_id = store_image_and_create_section(
                image_data=response_call(),
                file_id=file_id,
                display_name=file_name,
                media_type=f"image/{file_ext[1:]}",
                file_origin=FileOrigin.CONNECTOR,
                link=link,
            )
            sections.append(section)
        except Exception as e:
            logger.error(f"Failed to process image {file_name}: {e}")
        return sections

    # Process based on file extension
    try:
        file_bytes = response_call()
        if not file_bytes:
            logger.warning(f"Failed to download {file_name}")
            return []

        file_io = io.BytesIO(file_bytes)

        if file_ext == ".pdf":
            text, _pdf_meta, images = read_pdf_file(file_io)
            pdf_sections: list[TextSection | ImageSection] = [
                TextSection(link=link, text=text)
            ]

            # Process embedded images in the PDF only if images are allowed
            if allow_images:
                try:
                    for idx, (img_data, img_name) in enumerate(images):
                        section, embedded_id = store_image_and_create_section(
                            image_data=img_data,
                            file_id=f"{file_id}_img_{idx}",
                            display_name=img_name or f"{file_name} - image {idx}",
                            file_origin=FileOrigin.CONNECTOR,
                        )
                        pdf_sections.append(section)
                except Exception as e:
                    logger.error(f"Failed to process PDF images in {file_name}: {e}")
            return pdf_sections

        elif file_ext in [".docx", ".doc"]:
            text, _ = read_docx_file(file_io)
            return [TextSection(link=link, text=text)]

        elif file_ext == ".xlsx":
            text = xlsx_to_text(file_io, file_name=file_name)
            return [TextSection(link=link, text=text)] if text else []

        elif file_ext == ".xls":
            # Legacy Excel format - use generic extractor which can handle via unstructured API
            text = extract_file_text(file_io, file_name)
            return [TextSection(link=link, text=text)] if text else []

        elif file_ext == ".pptx":
            text = pptx_to_text(file_io, file_name=file_name)
            return [TextSection(link=link, text=text)] if text else []

        elif file_ext == ".ppt":
            # Legacy PowerPoint format - use generic extractor which can handle via unstructured API
            text = extract_file_text(file_io, file_name)
            return [TextSection(link=link, text=text)] if text else []

        elif file_ext == ".txt":
            text = file_bytes.decode("utf-8", errors="ignore")
            return [TextSection(link=link, text=text)]

        # Final attempt at extracting text using generic extractor
        if file_ext not in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS:
            logger.warning(f"Skipping file {file_name} due to extension.")
            return []

        try:
            text = extract_file_text(file_io, file_name)
            return [TextSection(link=link, text=text)]
        except Exception as e:
            logger.warning(f"Failed to extract text from {file_name}: {e}")
            return []

    except Exception as e:
        logger.error(f"Error processing file {file_name}: {e}")
        return []


def _get_external_access_for_raw_box_file(
    file: BoxFileType,
    company_domain: str | None,
    retriever_box_client: BoxClient | None,
    admin_box_client: BoxClient,
) -> ExternalAccess:
    """
    Get the external access for a raw Box file.
    """
    external_access_fn = cast(
        Callable[
            [BoxFileType, str | None, BoxClient | None, BoxClient],
            ExternalAccess,
        ],
        fetch_versioned_implementation_with_fallback(
            "onyx.external_permissions.box.doc_sync",
            "get_external_access_for_raw_box_file",
            fallback=noop_fallback,
        ),
    )
    return external_access_fn(
        file,
        company_domain,
        retriever_box_client,
        admin_box_client,
    )


def convert_box_item_to_document(
    client: BoxClient,
    allow_images: bool,
    size_threshold: int,
    permission_sync_context: PermissionSyncContext | None,
    retriever_user_id: str,
    file: BoxFileType,
) -> Document | ConnectorFailure | None:
    """
    Convert a Box file to an Onyx Document.
    """
    sections: list[TextSection | ImageSection] = []
    doc_id = "unknown"

    try:
        # Skip folders
        if file.get("type") == BOX_FOLDER_TYPE:
            logger.info("Skipping folder.")
            return None

        # Check file size
        size_str = file.get("size")
        if size_str:
            try:
                size_int = int(size_str)
            except ValueError:
                logger.warning(f"Parsing string to int failed: size_str={size_str}")
            else:
                if size_int > size_threshold:
                    logger.warning(
                        f"{file.get('name')} exceeds size threshold of {size_threshold}. Skipping."
                    )
                    return None

        # Extract sections
        file_name = file.get("name", "unknown")
        file_id = file.get("id", "unknown")
        logger.debug(
            f"Attempting to extract content from file: {file_name} (id: {file_id})"
        )
        sections = _download_and_extract_sections(
            file, client, allow_images, size_threshold
        )

        # If we still don't have any sections, skip this file
        if not sections:
            logger.warning(
                f"No content extracted from {file_name} (id: {file_id}). "
                f"This may be due to download permission issues, unsupported file type, "
                f"or empty file content."
            )
            return None

        doc_id = onyx_document_id_from_box_file(file)
        external_access = (
            _get_external_access_for_raw_box_file(
                file=file,
                company_domain=permission_sync_context.box_domain,
                retriever_box_client=client,
                admin_box_client=client,
            )
            if permission_sync_context
            else None
        )

        # Parse modified time to UTC datetime
        # Note: Must use exact timezone.utc object (not FixedOffset) for identity checks
        modified_time_str = file.get("modified_at")
        doc_updated_at = None
        if modified_time_str:
            try:
                parsed_dt = datetime.fromisoformat(
                    modified_time_str.replace("Z", "+00:00")
                )
                if parsed_dt.tzinfo is None:
                    doc_updated_at = parsed_dt.replace(tzinfo=timezone.utc)
                else:
                    # Convert to UTC and recreate with exact timezone.utc object
                    # (astimezone may return FixedOffset, which fails identity checks)
                    utc_timestamp = parsed_dt.astimezone(timezone.utc).timestamp()
                    doc_updated_at = datetime.fromtimestamp(
                        utc_timestamp, tz=timezone.utc
                    )
            except (ValueError, AttributeError) as e:
                logger.warning(
                    f"Failed to parse modified_at timestamp '{modified_time_str}': {e}"
                )

        # Create the document
        return Document(
            id=doc_id,
            sections=sections,
            source=DocumentSource.BOX,
            semantic_identifier=file.get("name", ""),
            metadata={},
            doc_updated_at=doc_updated_at,
            external_access=external_access,
        )
    except Exception as e:
        # Try to get doc_id for error reporting, but don't fail if it's unavailable
        try:
            doc_id = onyx_document_id_from_box_file(file)
        except Exception:
            doc_id = "unknown"

        file_name = file.get("name", "unknown")
        error_str = f"Error converting file '{file_name}' to Document as {retriever_user_id}: {e}"
        logger.warning(error_str)

        return ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=doc_id,
                document_link=(sections[0].link if sections else None),
            ),
            failed_entity=None,
            failure_message=error_str,
            exception=e,
        )


def build_slim_document(
    client: BoxClient,
    file: BoxFileType,
    permission_sync_context: PermissionSyncContext | None,
) -> SlimDocument | None:
    """Build a slim document for pruning."""
    if file.get("type") == BOX_FOLDER_TYPE:
        return None

    external_access = (
        _get_external_access_for_raw_box_file(
            file=file,
            company_domain=(
                permission_sync_context.box_domain if permission_sync_context else None
            ),
            retriever_box_client=client,
            admin_box_client=client,
        )
        if permission_sync_context
        else None
    )
    return SlimDocument(
        id=onyx_document_id_from_box_file(file),
        external_access=external_access,
    )
