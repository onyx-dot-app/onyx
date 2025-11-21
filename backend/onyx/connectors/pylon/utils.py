from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from io import BytesIO
from typing import Any

import httpx
from pydantic import BaseModel

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rate_limit_builder,
)
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.connectors.pylon.models import Issue
from onyx.connectors.pylon.models import Message
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()


class PylonRetriableError(Exception):
    """Raised for retriable Pylon conditions (429, 5xx)."""


class PylonNonRetriableError(Exception):
    """Raised for non-retriable Pylon client errors (4xx except 429)."""


class AttachmentData(BaseModel):
    """Container for downloaded attachment data.

    Attributes:
        content: Raw bytes of the attachment
        filename: Extracted filename from content-disposition header
        content_type: MIME type from content-type header (e.g., "image/png")
        url: Original presigned URL used for download
    """

    content: bytes
    filename: str
    content_type: str
    url: str


def build_auth_client(
    api_key: str, base_url: str = "https://api.usepylon.com"
) -> httpx.Client:
    """Build an authenticated HTTP client for Pylon API requests.

    Args:
        api_key: Pylon API key for Bearer authentication
        base_url: Base URL for Pylon API (defaults to production)

    Returns:
        Configured httpx.Client with authentication headers
    """
    client = httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    )
    return client


def build_generic_client() -> httpx.Client:
    """
    Build a generic HTTP client for downloading attachments from Pylon issues and messages.
    These attachments are presigned URLs and do not require authentication.

    Returns:
        Configured httpx.Client with authentication headers
    """
    client = httpx.Client(
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    )
    return client


@retry_builder(
    tries=6,
    delay=1,
    backoff=2,
    max_delay=30,
    exceptions=(PylonRetriableError, httpx.RequestError, httpx.ConnectError),
)
@rate_limit_builder(max_calls=20, period=60)
def pylon_get(
    client: httpx.Client, url: str, params: dict[str, Any] | None = None
) -> httpx.Response:
    """Perform a GET against Pylon API with retry and rate limiting.

    Retries on 429 and 5xx responses, and on transport errors. Honors
    `Retry-After` header for 429 when present by sleeping before retrying.
    """
    try:
        response = client.get(url, params=params)
    except httpx.RequestError:
        # Allow retry_builder to handle retries of transport errors
        raise

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 429:
            retry_after = e.response.headers.get("Retry-After") if e.response else None
            if retry_after is not None:
                try:
                    time.sleep(int(retry_after))
                except (TypeError, ValueError):
                    pass
            raise PylonRetriableError("Pylon rate limit exceeded (429)") from e
        if status is not None and 500 <= status < 600:
            raise PylonRetriableError(f"Pylon server error: {status}") from e
        if status is not None and 400 <= status < 500:
            raise PylonNonRetriableError(f"Pylon client error: {status}") from e
        # Unknown status, propagate
        raise

    return response


def parse_ymd_date(date_str: str) -> SecondsSinceUnixEpoch:
    """Parse YYYY-MM-DD date string to Unix timestamp.

    Args:
        date_str: Date string in YYYY-MM-DD format
    Returns:
        Unix timestamp as SecondsSinceUnixEpoch
    """
    try:
        # Convert start_date (expected format: YYYY-MM-DD) to SecondsSinceUnixEpoch
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        date_epoch = dt.timestamp()
    except Exception as e:
        # Default to 2025-01-01 UTC if there's a parsing error
        logger.warning(
            "Unable to parse start date from '%s'. Reason '%s'", date_str, str(e)
        )
        date_epoch = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    return date_epoch


def parse_pylon_datetime(datetime_str: str) -> SecondsSinceUnixEpoch:
    """Parse RFC3339 datetime string to Unix timestamp.

    Args:
        datetime_str: RFC3339 formatted datetime string

    Returns:
        Unix timestamp as SecondsSinceUnixEpoch
    """
    from datetime import datetime, timezone

    # Parse RFC3339 format (ISO with timezone)
    dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def get_time_window_days(
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
    start_boundary: SecondsSinceUnixEpoch,
) -> list[tuple[str, str]]:
    """Split time window into daily chunks for better checkpointing.

    Args:
        start: Start timestamp
        end: End timestamp
        start_boundary: either global start_epoch_sec or date from checkpoint

    Returns:
        List of (start_iso, end_iso) tuples for each day
    """
    # Respect start_epoch_sec if provided
    if start_boundary and start < start_boundary:
        start = start_boundary

    days = []
    start_dt = datetime.fromtimestamp(start, tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
    one_day = timedelta(days=1)

    while start_dt <= end_dt:
        day_start = start_dt
        day_end = min(start_dt + one_day, end_dt)

        days.append((day_start.isoformat(), day_end.isoformat()))

        start_dt += one_day

    return days


def generate_attachment_id(stable_url: str) -> str:
    """Generate stable ID for attachment based on URL.

    Args:
        stable_url: URL with query parameters stripped

    Returns:
        Hash-based stable ID
    """
    # Create a hash of the URL for stable ID generation
    url_hash = hashlib.md5(stable_url.encode()).hexdigest()[:16]
    return f"pylon_attachment_{url_hash}"


def normalize_attachment_url(url: str) -> str:
    """Normalize attachment URL by removing query parameters.

    Args:
        url: Raw attachment URL

    Returns:
        URL with query parameters removed

    Example url:
    "https://assets.usepylon.com/UUID_1/UUID_2-image.png?Expires=253370764800&Signature=SIG_VALUE&Key-Pair-Id=VALUE"
    """
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    # Remove query parameters and fragment
    normalized = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            "",  # Remove query
            "",  # Remove fragment
        )
    )
    return normalized


def _parse_filename_from_content_disposition(content_disposition: str) -> str | None:
    """Parse filename from Content-Disposition header.

    Args:
        content_disposition: Value of Content-Disposition header

    Returns:
        Extracted filename or None if not found

    Example:
        "inline; filename=Screenshot 2025-10-12 at 8.22.32.png" -> "Screenshot 2025-10-12 at 8.22.32.png"
        'attachment; filename="document.pdf"' -> "document.pdf"
    """
    import re

    if not content_disposition:
        return None

    # Try to match filename="..." or filename=... patterns
    # Handle both quoted and unquoted filenames
    patterns = [
        r"filename\*=UTF-8\'\'([^;]+)",  # RFC 5987 encoded filename
        r'filename="([^"]+)"',  # Quoted filename
        r"filename='([^']+)'",  # Single-quoted filename
        r"filename=([^;]+)",  # Unquoted filename
    ]

    for pattern in patterns:
        match = re.search(pattern, content_disposition, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            # URL decode if it's RFC 5987 encoded
            if "UTF-8''" in pattern:
                from urllib.parse import unquote

                filename = unquote(filename)
            return filename if filename else None

    return None


def _clean_html_to_text(
    html: str,
) -> str:
    """Convert HTML fragments to cleaned plain text using shared HTML utils.

    This applies consistent stripping of boilerplate (e.g., style/script/link/meta),
    normalizes whitespace, and respects global configuration for link handling
    and readability extraction.

    Args:
        html: The HTML string to clean.
        discard: Additional element names to discard beyond defaults. If not
            provided, a safe default set for inline fragments is used.
        mintlify_cleanup: Whether to enable Mintlify-specific class pruning.

    Returns:
        Cleaned plain text suitable for indexing.
    """
    default_discard = [
        "style",
        "script",
        "link",
        "meta",
        "svg",
        "noscript",
        "template",
    ]
    parsed = web_html_cleanup(
        html,
        mintlify_cleanup_enabled=False,
        additional_element_types_to_discard=default_discard,
    )
    return parsed.cleaned_text


@retry_builder(tries=3, delay=1.0, backoff=2.0)
def download_attachment(
    client: httpx.Client, presigned_url: str
) -> AttachmentData | None:
    """Download attachment from presigned URL with retry logic.

    Performs a HEAD request first to check content-disposition header and content-length.
    Skips attachments without content-disposition header or those exceeding 10 MB.

    Args:
        client: HTTP client to use for the download
        presigned_url: Presigned URL for the attachment (e.g., from a Pylon issue)

    Returns:
        AttachmentData object containing content, filename, content_type, and url,
        or None if file should be skipped

    Raises:
        Exception: If download fails after retries or if response is unsuccessful
    """
    MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB in bytes

    # First, make a HEAD request to check content-disposition and content-length
    head_response = client.head(presigned_url)
    head_response.raise_for_status()

    # Extract filename from content-disposition header
    content_disposition = head_response.headers.get("content-disposition")
    if not content_disposition:
        logger.info("Skipping attachment download (no content-disposition header)")
        return None

    filename = _parse_filename_from_content_disposition(content_disposition)
    if not filename:
        logger.info("Skipping attachment download (no filename in content-disposition)")
        return None

    # Extract content-type (MIME type)
    content_type = head_response.headers.get("content-type", "application/octet-stream")

    # Check content-length
    content_length_header = head_response.headers.get("content-length")
    if content_length_header and content_length_header.isdigit():
        content_length = int(content_length_header)
        if content_length > MAX_ATTACHMENT_SIZE:
            logger.info(
                f"Skipping attachment download (size {content_length} bytes exceeds "
                f"{MAX_ATTACHMENT_SIZE} bytes limit)"
            )
            return None

    response = client.get(presigned_url)
    response.raise_for_status()

    if not response.content:
        logger.warning("Empty response content from attachment")
        return None

    return AttachmentData(
        content=response.content,
        filename=filename,
        content_type=content_type,
        url=presigned_url,
    )


def map_to_document(
    issue: Issue, messages: list[Message], attachments: list[AttachmentData]
) -> Document:
    """
    Map Pylon issue, messages, and attachments to a single Document object.

    Behavior:
    - Converts issue and message HTML to plain text and appends as TextSection.
    - Processes each attachment via extract_text_and_images; appends extracted text as TextSection.
    - Persists only images (original image attachments and any embedded images) to FileStore and
      appends ImageSection referencing the stored file id.
    - Attachment URLs are presigned/ephemeral, so they are not added to the link field.
    """

    sections: list[TextSection | ImageSection] = []

    # Issue body
    if issue.body_html:
        cleaned_issue_text = _clean_html_to_text(issue.body_html)
        if cleaned_issue_text:
            sections.append(TextSection(link=issue.link, text=cleaned_issue_text))

    # Messages
    for idx, message in enumerate(messages):
        if idx == 0:
            # the first message's `message_html` and the issue's body_html are identical
            continue
        message_html = message.message_html
        if not message_html:
            continue
        cleaned_message_text = _clean_html_to_text(message_html or "")
        if cleaned_message_text:
            link = f"{issue.link}&messageID={message.id}" if issue.link else None
            sections.append(TextSection(link=link, text=cleaned_message_text))

    sections.extend(_process_attachments(attachments))

    if issue.title:
        semantic_identifier = issue.title
    elif issue.number is not None:
        semantic_identifier = f"Issue #{issue.number}"
    else:
        semantic_identifier = f"Issue {issue.id or 'unknown'}"

    metadata = _create_metadata(issue)

    document = Document(
        id=f"pylon:issue:{issue.id}",
        source=DocumentSource.PYLON,
        semantic_identifier=semantic_identifier,
        title=issue.title or semantic_identifier,
        sections=sections,
        metadata=metadata,
    )
    assignee = issue.assignee.email if issue.assignee and issue.assignee.email else None

    if assignee:
        document.secondary_owners = [BasicExpertInfo(email=assignee)]

    requester = (
        issue.requester.email if issue.requester and issue.requester.email else None
    )
    if requester:
        document.primary_owners = [BasicExpertInfo(email=requester)]

    return document


def _process_attachments(
    attachments: list[AttachmentData],
) -> Sequence[TextSection | ImageSection]:
    sections: list[TextSection | ImageSection] = []
    for attachment in attachments:
        # Stable base id derived from normalized (query-stripped) URL
        base_stable_url = normalize_attachment_url(attachment.url)
        base_id = generate_attachment_id(base_stable_url)

        # Persist original if it is an image
        if attachment.content_type.startswith("image/"):
            try:
                image_section, _ = store_image_and_create_section(
                    image_data=attachment.content,
                    file_id=base_id,
                    display_name=attachment.filename,
                    media_type=attachment.content_type,
                    file_origin=FileOrigin.CONNECTOR,
                )
                logger.debug(
                    f"Attachment Image: {image_section.image_file_id}: {attachment.content_type}: {attachment.filename}"
                )
                sections.append(image_section)
            except Exception:
                # Best-effort: do not fail the whole document if image storage fails
                logger.exception(
                    "Failed to persist original image attachment for Pylon"
                )

        else:

            extraction_result = extract_text_and_images(
                file=BytesIO(attachment.content),
                file_name=attachment.filename,
                pdf_pass=None,
                content_type=attachment.content_type,
                image_callback=None,
            )
            if extraction_result.text_content:
                sections.append(TextSection(text=extraction_result.text_content))

            # Persist any embedded images discovered during extraction
            for idx, (img_bytes, img_name) in enumerate(
                extraction_result.embedded_images
            ):
                try:
                    mime = "application/octet-stream"
                    image_section, _ = store_image_and_create_section(
                        image_data=img_bytes,
                        file_id=f"{base_id}:{idx}",
                        display_name=img_name,
                        media_type=mime,
                        file_origin=FileOrigin.CONNECTOR,
                    )
                    logger.debug(
                        f"Attachment Image Embedded: {image_section.image_file_id}: "
                        f"{attachment.content_type}: {attachment.filename}"
                    )
                    sections.append(image_section)
                except Exception:
                    logger.exception(
                        "Failed to persist embedded image for Pylon attachment"
                    )
    return sections


def _create_metadata(issue: Issue) -> dict[str, str | list[str]]:
    # Build metadata with string or list[str] values only
    metadata: dict[str, str | list[str]] = {
        "entity_type": issue.type.value if issue.type else "Ticket"
    }
    if issue.number is not None:
        metadata["issue_number"] = str(issue.number)
    if issue.state:
        metadata["state"] = issue.state
    if issue.created_at:
        metadata["created_at"] = issue.created_at
    updated_at = issue.latest_message_time or issue.resolution_time or issue.created_at
    if updated_at:
        metadata["updated_at"] = updated_at
    if issue.tags:
        metadata["tags"] = issue.tags
    if issue.source is not None:
        metadata["source"] = str(issue.source.value)
    return metadata


def is_valid_issue(issue: Issue) -> bool:
    """
    Validate that the Issue model has all required fields.
    OpenAPI spec does not specify required fields, so we check manually.
    The intended use is to ignore issues that are missing critical fields.
    Args:
        issue: Issue model to validate
    Returns:
        True if valid, False otherwise
    """
    required_fields = ["id", "body_html"]
    for field in required_fields:
        if not hasattr(issue, field) or getattr(issue, field) is None:
            return False
    return True


def is_valid_message(issue: Message) -> bool:
    """
    Validate that the Message model has all required fields.
    OpenAPI spec does not specify required fields, so we check manually.
    The intended use is to ignore issues that are missing critical fields.
    Args:
        issue: Issue model to validate
    Returns:
        True if valid, False otherwise
    """
    required_fields = ["id", "message_html"]
    for field in required_fields:
        if not hasattr(issue, field) or getattr(issue, field) is None:
            return False
    return True


def _create_id(issue: Issue) -> str:
    return f"{DocumentSource.PYLON.value}:issue:{issue.id}"
