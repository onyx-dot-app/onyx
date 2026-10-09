import math
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, quote, urljoin, urlparse

import bs4
import requests
from pydantic import BaseModel

from onyx.configs.app_configs import (
    CONFLUENCE_CONNECTOR_ATTACHMENT_CHAR_COUNT_THRESHOLD,
    CONFLUENCE_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD,
    REQUEST_TIMEOUT_SECONDS,
)
from onyx.configs.constants import FileOrigin
from onyx.file_processing.extract_file_text import extract_file_text, get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions, OnyxMimeTypes
from onyx.file_processing.html_utils import format_document_soup
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.datetime import datetime_to_utc
from onyx.utils.logger import setup_logger
from onyx.utils.retry_after import parse_retry_after_seconds

if TYPE_CHECKING:
    from onyx.connectors.confluence.source_operations import (
        ConfluenceSourceOperations,
    )


logger = setup_logger()

CONFLUENCE_OAUTH_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
RATE_LIMIT_MESSAGE_LOWERCASE = "Rate limit exceeded".lower()


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: str
    refresh_token: str
    scope: str


def validate_attachment_filetype(
    attachment: dict[str, Any],
) -> bool:
    """
    Validates if the attachment is a supported file type.
    """
    media_type = attachment.get("metadata", {}).get("mediaType", "")
    if media_type.startswith("image/"):
        return media_type in OnyxMimeTypes.IMAGE_MIME_TYPES

    # For non-image files, check if we support the extension
    title = attachment.get("title", "")
    extension = get_file_ext(title)

    return extension in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS


class AttachmentProcessingResult(BaseModel):
    """
    A container for results after processing a Confluence attachment.
    'text' is the textual content of the attachment.
    'file_name' is the final file name used in FileStore to store the content.
    'error' holds an exception or string if something failed.
    """

    text: str | None
    file_name: str | None
    error: str | None = None


def process_attachment(
    source_operations: "ConfluenceSourceOperations",
    attachment: dict[str, Any],
    parent_content_id: str | None,
    allow_images: bool,
) -> AttachmentProcessingResult:
    """
    Processes a Confluence attachment. If it's a document, extracts text,
    or if it's an image, stores it for later analysis. Returns a structured result.
    """
    try:
        # Get the media type from the attachment metadata
        media_type: str = attachment.get("metadata", {}).get("mediaType", "")
        # Validate the attachment type
        if not validate_attachment_filetype(attachment):
            return AttachmentProcessingResult(
                text=None,
                file_name=None,
                error=f"Unsupported file type: {media_type}",
            )

        attachment_size = attachment["extensions"]["fileSize"]

        if media_type.startswith("image/"):
            if not allow_images:
                return AttachmentProcessingResult(
                    text=None,
                    file_name=None,
                    error="Image downloading is not enabled",
                )
        else:
            if attachment_size > CONFLUENCE_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD:
                logger.warning(
                    "Skipping %s due to size. size=%s threshold=%s",
                    attachment["title"],
                    attachment_size,
                    CONFLUENCE_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD,
                )
                return AttachmentProcessingResult(
                    text=None,
                    file_name=None,
                    error=f"Attachment text too long: {attachment_size} chars",
                )

        raw_bytes = source_operations.download_attachment(
            attachment=attachment, parent_content_id=parent_content_id
        )
        if not raw_bytes:
            return AttachmentProcessingResult(
                text=None, file_name=None, error="attachment.content is None"
            )

        # Process image attachments
        if media_type.startswith("image/"):
            return _process_image_attachment(attachment, raw_bytes, media_type)

        # Process document attachments
        try:
            text = extract_file_text(
                file=BytesIO(raw_bytes),
                file_name=attachment["title"],
            )

            # Skip if the text is too long
            if len(text) > CONFLUENCE_CONNECTOR_ATTACHMENT_CHAR_COUNT_THRESHOLD:
                return AttachmentProcessingResult(
                    text=None,
                    file_name=None,
                    error=f"Attachment text too long: {len(text)} chars",
                )

            return AttachmentProcessingResult(text=text, file_name=None, error=None)
        except Exception as e:
            return AttachmentProcessingResult(
                text=None, file_name=None, error=f"Failed to extract text: {e}"
            )

    except Exception as e:
        return AttachmentProcessingResult(
            text=None, file_name=None, error=f"Failed to process attachment: {e}"
        )


def _process_image_attachment(
    attachment: dict[str, Any],
    raw_bytes: bytes,
    media_type: str,
) -> AttachmentProcessingResult:
    """Process an image attachment by saving it without generating a summary."""
    try:
        # Use the standardized image storage and section creation
        section, file_name = store_image_and_create_section(
            image_data=raw_bytes,
            file_id=Path(attachment["id"]).name,
            display_name=attachment["title"],
            media_type=media_type,
            file_origin=FileOrigin.CONNECTOR,
        )
        logger.info("Stored image attachment with file name: %s", file_name)

        # Return empty text but include the file_name for later processing
        return AttachmentProcessingResult(text="", file_name=file_name, error=None)
    except Exception as e:
        msg = f"Image storage failed for {attachment['title']}: {e}"
        logger.error(msg, exc_info=e)
        return AttachmentProcessingResult(text=None, file_name=None, error=msg)


def convert_attachment_to_content(
    source_operations: "ConfluenceSourceOperations",
    attachment: dict[str, Any],
    page_id: str,
    allow_images: bool,
) -> tuple[str | None, str | None] | None:
    """
    Facade function which:
      1. Validates attachment type
      2. Extracts content or stores image for later processing
      3. Returns (content_text, stored_file_name) or None if we should skip it
    """
    media_type = attachment.get("metadata", {}).get("mediaType", "")
    # Quick check for unsupported types:
    if media_type.startswith("video/") or media_type == "application/gliffy+json":
        logger.warning(
            "Skipping unsupported attachment type: '%s' for %s",
            media_type,
            attachment["title"],
        )
        return None

    result = process_attachment(source_operations, attachment, page_id, allow_images)
    if result.error is not None:
        logger.warning(
            "Attachment %s encountered error: %s", attachment["title"], result.error
        )
        return None

    # Return the text and the file name
    return result.text, result.file_name


def build_confluence_document_id(
    base_url: str, content_url: str, is_cloud: bool
) -> str:
    """For confluence, the document id is the page url for a page based document
        or the attachment download url for an attachment based document

    Args:
        base_url (str): The base url of the Confluence instance
        content_url (str): The url of the page or attachment download url

    Returns:
        str: The document id
    """

    # NOTE: urljoin is tricky and will drop the last segment of the base if it doesn't
    # end with "/" because it believes that makes it a file.
    final_url = base_url.rstrip("/") + "/"
    if is_cloud and not final_url.endswith("/wiki/"):
        final_url = urljoin(final_url, "wiki") + "/"
    final_url = urljoin(final_url, content_url.lstrip("/"))
    return final_url


def build_cql_url(cql: str, expand: str | None = None) -> str:
    """Returns the content-search path for a CQL query."""
    expand_string = f"&expand={expand}" if expand else ""
    return f"rest/api/content/search?cql={cql}{expand_string}"


def datetime_from_string(datetime_string: str) -> datetime:
    return datetime_to_utc(datetime.fromisoformat(datetime_string))


def confluence_refresh_tokens(
    client_id: str, client_secret: str, cloud_id: str, refresh_token: str
) -> dict[str, Any]:
    # rotate the refresh and access token
    # Note that access tokens are only good for an hour in confluence cloud,
    # so we're going to have problems if the connector runs for longer
    # https://developer.atlassian.com/cloud/confluence/oauth-2-3lo-apps/#use-a-refresh-token-to-get-another-access-token-and-refresh-token-pair
    response = requests.post(
        CONFLUENCE_OAUTH_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    try:
        token_response = TokenResponse.model_validate_json(response.text)
    except Exception:
        raise RuntimeError("Confluence Cloud token refresh failed.")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=token_response.expires_in)

    new_credentials: dict[str, Any] = {}
    new_credentials["confluence_access_token"] = token_response.access_token
    new_credentials["confluence_refresh_token"] = token_response.refresh_token
    new_credentials["created_at"] = now.isoformat()
    new_credentials["expires_at"] = expires_at.isoformat()
    new_credentials["expires_in"] = token_response.expires_in
    new_credentials["scope"] = token_response.scope
    new_credentials["cloud_id"] = cloud_id
    return new_credentials


def _handle_http_error(e: requests.HTTPError, attempt: int, max_retries: int) -> int:
    MIN_DELAY = 2
    MAX_DELAY = 60
    STARTING_DELAY = 5
    BACKOFF = 2

    # Check if the response or headers are None to avoid potential AttributeError
    if e.response is None or e.response.headers is None:
        logger.warning("HTTPError with `None` as response or as headers")
        raise e

    # Confluence Server returns 403 when rate limited
    if e.response.status_code == 403:
        FORBIDDEN_MAX_RETRY_ATTEMPTS = 7
        FORBIDDEN_RETRY_DELAY = 10
        if attempt < FORBIDDEN_MAX_RETRY_ATTEMPTS:
            logger.warning(
                "403 error. This sometimes happens when we hit Confluence rate limits. Retrying in %s seconds...",
                FORBIDDEN_RETRY_DELAY,
            )
            return math.ceil(time.monotonic() + FORBIDDEN_RETRY_DELAY)

        raise e

    if e.response.status_code >= 500:
        if attempt >= max_retries - 1:
            raise e

        delay = min(STARTING_DELAY * (BACKOFF**attempt), MAX_DELAY)
        logger.warning(
            "Server error %s. Retrying in %s seconds (attempt %s)...",
            e.response.status_code,
            delay,
            attempt + 1,
        )
        return math.ceil(time.monotonic() + delay)

    if (
        e.response.status_code != 429
        and RATE_LIMIT_MESSAGE_LOWERCASE not in e.response.text.lower()
    ):
        raise e

    retry_after = parse_retry_after_seconds(e.response.headers.get("Retry-After"))
    if retry_after is not None:
        if retry_after > MAX_DELAY:
            logger.warning(
                "Clamping retry_after from %s to %s seconds...",
                retry_after,
                MAX_DELAY,
            )
            retry_after = MAX_DELAY
        if retry_after < MIN_DELAY:
            retry_after = MIN_DELAY

    if retry_after is not None:
        logger.warning(
            "Rate limiting with retry header. Retrying after %s seconds...", retry_after
        )
        delay = retry_after
    else:
        logger.warning(
            "Rate limiting without retry header. Retrying with exponential backoff..."
        )
        delay = min(STARTING_DELAY * (BACKOFF**attempt), MAX_DELAY)

    delay_until = math.ceil(time.monotonic() + delay)
    return delay_until


def get_single_param_from_url(url: str, param: str) -> str | None:
    """Get a parameter from a url"""
    parsed_url = urlparse(url)
    return parse_qs(parsed_url.query).get(param, [None])[0]


def get_start_param_from_url(url: str) -> int:
    """Get the start parameter from a url"""
    start_str = get_single_param_from_url(url, "start")
    return int(start_str) if start_str else 0


def update_param_in_path(path: str, param: str, value: str) -> str:
    """Update a parameter in a path. Path should look something like:

    /api/rest/users?start=0&limit=10
    """
    parsed_url = urlparse(path)
    query_params = parse_qs(parsed_url.query)
    query_params[param] = [value]
    return (
        path.split("?")[0]
        + "?"
        + "&".join(f"{k}={quote(v[0])}" for k, v in query_params.items())
    )


def sanitize_attachment_title(title: str) -> str:
    """
    Sanitize the attachment title to be a valid HTML attribute.
    """
    return title.replace("<", "_").replace(">", "_").replace(" ", "_").replace(":", "_")


def extract_text_from_confluence_html(
    source_operations: "ConfluenceSourceOperations",
    confluence_object: dict[str, Any],
    fetched_titles: set[str],
) -> str:
    """Parse a Confluence html page and replace the 'user Id' by the real
        User Display Name

    Args:
        source_operations: The Confluence source-operations gateway
        confluence_object (dict): The confluence object as a dict
        fetched_titles (set[str]): The titles of the pages that have already been fetched
    Returns:
        str: loaded and formated Confluence page
    """
    body = confluence_object["body"]
    object_html = body.get("storage", body.get("view", {})).get("value")

    soup = bs4.BeautifulSoup(object_html, "html.parser")

    _remove_macro_stylings(soup=soup)

    for date_span in soup.findAll("span", {"class": "date-lozenger-container"}):
        date_span.replaceWith(date_span.get_text())

    for user in soup.findAll("ri:user"):
        user_id = (
            user.attrs["ri:account-id"]
            if "ri:account-id" in user.attrs
            else user.get("ri:userkey")
        )
        if not user_id:
            logger.warning(
                "ri:userkey not found in ri:user element. Found attrs: %s",
                user.attrs,
            )
            continue
        # Include @ sign for tagging, more clear for LLM
        user.replaceWith("@" + source_operations.get_user_display_name(user_id=user_id))

    for html_page_reference in soup.findAll("ac:structured-macro"):
        # Here, we only want to process page within page macros
        if html_page_reference.attrs.get("ac:name") != "include":
            continue

        page_data = html_page_reference.find("ri:page")
        if not page_data:
            logger.warning(
                "Skipping retrieval of %s because because page data is missing",
                html_page_reference,
            )
            continue

        page_title = page_data.attrs.get("ri:content-title")
        if not page_title:
            # only fetch pages that have a title
            logger.warning(
                "Skipping retrieval of %s because it has no title",
                html_page_reference,
            )
            continue

        if page_title in fetched_titles:
            # prevent recursive fetching of pages
            logger.debug("Skipping %s because it has already been fetched", page_title)
            continue

        fetched_titles.add(page_title)

        # Wrap this in a try-except because there are some pages that might not exist
        try:
            page_contents = source_operations.find_page_by_title(title=page_title)
        except Exception as e:
            logger.warning(
                "Error getting page contents for object %s: %s",
                confluence_object,
                e,
            )
            continue

        if not page_contents:
            continue

        text_from_page = extract_text_from_confluence_html(
            source_operations=source_operations,
            confluence_object=page_contents,
            fetched_titles=fetched_titles,
        )

        html_page_reference.replaceWith(text_from_page)

    for html_link_body in soup.findAll("ac:link-body"):
        # This extracts the text from inline links in the page so they can be
        # represented in the document text as plain text
        try:
            text_from_link = html_link_body.text
            html_link_body.replaceWith(f"(LINK TEXT: {text_from_link})")
        except Exception as e:
            logger.warning("Error processing ac:link-body: %s", e)

    for html_attachment in soup.findAll("ri:attachment"):
        # This extracts the text from inline attachments in the page so they can be
        # represented in the document text as plain text
        try:
            html_attachment.replaceWith(
                f"<attachment>{sanitize_attachment_title(html_attachment.attrs['ri:filename'])}</attachment>"
            )  # to be replaced later
        except Exception as e:
            logger.warning("Error processing ac:attachment: %s", e)

    return format_document_soup(soup)


def _remove_macro_stylings(soup: bs4.BeautifulSoup) -> None:
    for macro_root in soup.findAll("ac:structured-macro"):
        if not isinstance(macro_root, bs4.Tag):
            continue

        macro_styling = macro_root.find(name="ac:parameter", attrs={"ac:name": "page"})
        if not macro_styling or not isinstance(macro_styling, bs4.Tag):
            continue

        macro_styling.extract()
