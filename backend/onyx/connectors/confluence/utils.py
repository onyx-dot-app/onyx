import io
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from io import BytesIO
from typing import Any
from urllib.parse import quote

import bs4
from sqlalchemy.orm import Session

from onyx.configs.app_configs import (
    CONFLUENCE_CONNECTOR_ATTACHMENT_CHAR_COUNT_THRESHOLD,
)
from onyx.configs.constants import FileOrigin
from onyx.connectors.confluence.onyx_confluence import (
    OnyxConfluence,
)
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import PGFileStore
from onyx.db.pg_file_store import create_populate_lobj
from onyx.db.pg_file_store import upsert_pgfilestore
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.html_utils import format_document_soup
from onyx.file_processing.image_summarization import summarize_image_pipeline
from onyx.llm.interfaces import LLM
from onyx.prompts.image_analysis import IMAGE_SUMMARIZATION_SYSTEM_PROMPT
from onyx.prompts.image_analysis import IMAGE_SUMMARIZATION_USER_PROMPT
from onyx.utils.logger import setup_logger

logger = setup_logger()


_USER_EMAIL_CACHE: dict[str, str | None] = {}


def get_user_email_from_username__server(
    confluence_client: OnyxConfluence, user_name: str
) -> str | None:
    global _USER_EMAIL_CACHE
    if _USER_EMAIL_CACHE.get(user_name) is None:
        try:
            response = confluence_client.get_mobile_parameters(user_name)
            email = response.get("email")
        except Exception:
            logger.warning(f"failed to get confluence email for {user_name}")
            # For now, we'll just return None and log a warning. This means
            # we will keep retrying to get the email every group sync.
            email = None
            # We may want to just return a string that indicates failure so we dont
            # keep retrying
            # email = f"FAILED TO GET CONFLUENCE EMAIL FOR {user_name}"
        _USER_EMAIL_CACHE[user_name] = email
    return _USER_EMAIL_CACHE[user_name]


_USER_NOT_FOUND = "Unknown Confluence User"
_USER_ID_TO_DISPLAY_NAME_CACHE: dict[str, str | None] = {}


def _get_user(confluence_client: OnyxConfluence, user_id: str) -> str:
    """Get Confluence Display Name based on the account-id or userkey value

    Args:
        user_id (str): The user id (i.e: the account-id or userkey)
        confluence_client (Confluence): The Confluence Client

    Returns:
        str: The User Display Name. 'Unknown User' if the user is deactivated or not found
    """
    global _USER_ID_TO_DISPLAY_NAME_CACHE
    if _USER_ID_TO_DISPLAY_NAME_CACHE.get(user_id) is None:
        try:
            result = confluence_client.get_user_details_by_userkey(user_id)
            found_display_name = result.get("displayName")
        except Exception:
            found_display_name = None

        if not found_display_name:
            try:
                result = confluence_client.get_user_details_by_accountid(user_id)
                found_display_name = result.get("displayName")
            except Exception:
                found_display_name = None

        _USER_ID_TO_DISPLAY_NAME_CACHE[user_id] = found_display_name

    return _USER_ID_TO_DISPLAY_NAME_CACHE.get(user_id) or _USER_NOT_FOUND


def extract_text_from_confluence_html(
    confluence_client: OnyxConfluence,
    confluence_object: dict[str, Any],
    fetched_titles: set[str],
) -> str:
    """Parse a Confluence html page and replace the 'user Id' by the real
        User Display Name

    Args:
        confluence_object (dict): The confluence object as a dict
        confluence_client (Confluence): Confluence client
        fetched_titles (set[str]): The titles of the pages that have already been fetched
    Returns:
        str: loaded and formated Confluence page
    """
    body = confluence_object["body"]
    object_html = body.get("storage", body.get("view", {})).get("value")

    soup = bs4.BeautifulSoup(object_html, "html.parser")
    for user in soup.findAll("ri:user"):
        user_id = (
            user.attrs["ri:account-id"]
            if "ri:account-id" in user.attrs
            else user.get("ri:userkey")
        )
        if not user_id:
            logger.warning(
                "ri:userkey not found in ri:user element. " f"Found attrs: {user.attrs}"
            )
            continue
        # Include @ sign for tagging, more clear for LLM
        user.replaceWith("@" + _get_user(confluence_client, user_id))

    for html_page_reference in soup.findAll("ac:structured-macro"):
        # Here, we only want to process page within page macros
        if html_page_reference.attrs.get("ac:name") != "include":
            continue

        page_data = html_page_reference.find("ri:page")
        if not page_data:
            logger.warning(
                f"Skipping retrieval of {html_page_reference} because because page data is missing"
            )
            continue

        page_title = page_data.attrs.get("ri:content-title")
        if not page_title:
            # only fetch pages that have a title
            logger.warning(
                f"Skipping retrieval of {html_page_reference} because it has no title"
            )
            continue

        if page_title in fetched_titles:
            # prevent recursive fetching of pages
            logger.debug(f"Skipping {page_title} because it has already been fetched")
            continue

        fetched_titles.add(page_title)

        # Wrap this in a try-except because there are some pages that might not exist
        try:
            page_query = f"type=page and title='{quote(page_title)}'"

            page_contents: dict[str, Any] | None = None
            # Confluence enforces title uniqueness, so we should only get one result here
            for page in confluence_client.paginated_cql_retrieval(
                cql=page_query,
                expand="body.storage.value",
                limit=1,
            ):
                page_contents = page
                break
        except Exception as e:
            logger.warning(
                f"Error getting page contents for object {confluence_object}: {e}"
            )
            continue

        if not page_contents:
            continue

        text_from_page = extract_text_from_confluence_html(
            confluence_client=confluence_client,
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
            logger.warning(f"Error processing ac:link-body: {e}")

    return format_document_soup(soup)


def validate_attachment_filetype(media_type: str) -> bool:
    if media_type.startswith("video/") or media_type == "application/gliffy+json":
        return False
    return True


@dataclass
class AttachmentProcessingResult:
    """
    A container for results after processing a Confluence attachment.
    'text' might be textual extraction or image summarization.
    'file_name' is the final file name used in PGFileStore.
    'error' holds an exception or string if something failed.
    """

    text: str | None
    file_name: str | None
    error: str | None = None


def _download_attachment(
    confluence_client: OnyxConfluence, attachment: dict[str, Any]
) -> bytes | None:
    """
    Retrieves the raw bytes of an attachment from Confluence. Returns None on error.
    """
    download_link = confluence_client.url + attachment["_links"]["download"]
    resp = confluence_client._session.get(download_link)
    if resp.status_code != 200:
        logger.warning(
            f"Failed to fetch {download_link} with status code {resp.status_code}"
        )
        return None
    return resp.content


def _save_attachment_to_pgfilestore(
    db_session: Session,
    raw_bytes: bytes,
    media_type: str,
    attachment_id: str,
    display_name: str,
) -> PGFileStore:
    """
    Saves raw bytes to PGFileStore and returns the resulting record.
    """
    file_name = f"confluence_attachment_{attachment_id}"
    lobj_oid = create_populate_lobj(BytesIO(raw_bytes), db_session)
    pgfilestore = upsert_pgfilestore(
        file_name=file_name,
        display_name=display_name,
        file_origin=FileOrigin.OTHER,
        file_type=media_type,
        lobj_oid=lobj_oid,
        db_session=db_session,
        commit=True,
    )
    return pgfilestore


def _extract_or_summarize_attachment(
    confluence_client: OnyxConfluence,
    attachment: dict[str, Any],
    page_context: str,
    llm: LLM | None,
) -> AttachmentProcessingResult:
    """
    Downloads an attachment from Confluence, attempts to extract text if possible,
    or if it's an image and an LLM is available, summarizes it. Returns a structured result.
    """
    media_type = attachment["metadata"]["mediaType"]
    raw_bytes = _download_attachment(confluence_client, attachment)
    if not raw_bytes:
        return AttachmentProcessingResult(
            text=None, file_name=None, error="Download returned no bytes"
        )

    if media_type.startswith("image/") and llm:
        return _process_image_attachment(
            confluence_client, attachment, page_context, llm, raw_bytes, media_type
        )
    else:
        return _process_text_attachment(attachment, raw_bytes, media_type)


def _process_image_attachment(
    confluence_client: OnyxConfluence,
    attachment: dict[str, Any],
    page_context: str,
    llm: LLM,
    raw_bytes: bytes,
    media_type: str,
) -> AttachmentProcessingResult:
    """Process an image attachment by saving it and generating a summary."""
    try:
        with get_session_with_current_tenant() as db_session:
            saved_record = _save_attachment_to_pgfilestore(
                db_session=db_session,
                raw_bytes=raw_bytes,
                media_type=media_type,
                attachment_id=attachment["id"],
                display_name=attachment["title"],
            )
        user_prompt = IMAGE_SUMMARIZATION_USER_PROMPT.format(
            title=attachment["title"],
            page_title=attachment["title"],
            confluence_xml=page_context,
        )
        summary_text = summarize_image_pipeline(
            llm=llm,
            image_data=raw_bytes,
            query=user_prompt,
            system_prompt=IMAGE_SUMMARIZATION_SYSTEM_PROMPT,
        )
        return AttachmentProcessingResult(
            text=summary_text, file_name=saved_record.file_name, error=None
        )
    except Exception as e:
        msg = f"Image summarization failed for {attachment['title']}: {e}"
        logger.error(msg, exc_info=e)
        return AttachmentProcessingResult(text=None, file_name=None, error=msg)


def _process_text_attachment(
    attachment: dict[str, Any],
    raw_bytes: bytes,
    media_type: str,
) -> AttachmentProcessingResult:
    """Process a text-based attachment by extracting its content."""
    try:
        extracted_text = extract_file_text(
            io.BytesIO(raw_bytes),
            file_name=attachment["title"],
            break_on_unprocessable=False,
        )
    except Exception as e:
        msg = f"Failed to extract text for '{attachment['title']}': {e}"
        logger.error(msg, exc_info=e)
        return AttachmentProcessingResult(text=None, file_name=None, error=msg)

    # Check length constraints
    if extracted_text is None or len(extracted_text) == 0:
        msg = f"No text extracted for {attachment['title']}"
        logger.warning(msg)
        return AttachmentProcessingResult(text=None, file_name=None, error=msg)

    if len(extracted_text) > CONFLUENCE_CONNECTOR_ATTACHMENT_CHAR_COUNT_THRESHOLD:
        msg = (
            f"Skipping attachment {attachment['title']} due to char count "
            f"({len(extracted_text)} > {CONFLUENCE_CONNECTOR_ATTACHMENT_CHAR_COUNT_THRESHOLD})"
        )
        logger.warning(msg)
        return AttachmentProcessingResult(text=None, file_name=None, error=msg)

    # Save the attachment
    try:
        with get_session_with_current_tenant() as db_session:
            saved_record = _save_attachment_to_pgfilestore(
                db_session=db_session,
                raw_bytes=raw_bytes,
                media_type=media_type,
                attachment_id=attachment["id"],
                display_name=attachment["title"],
            )
    except Exception as e:
        msg = f"Failed to save attachment '{attachment['title']}' to PG: {e}"
        logger.error(msg, exc_info=e)
        return AttachmentProcessingResult(
            text=extracted_text, file_name=None, error=msg
        )

    return AttachmentProcessingResult(
        text=extracted_text, file_name=saved_record.file_name, error=None
    )


def convert_attachment_to_content(
    confluence_client: OnyxConfluence,
    attachment: dict[str, Any],
    page_context: str,
    llm: LLM | None,
) -> tuple[str | None, str | None] | None:
    """
    Facade function which:
      1. Validates attachment type
      2. Extracts or summarizes content
      3. Returns (content_text, stored_file_name) or None if we should skip it
    """
    media_type = attachment["metadata"]["mediaType"]
    # Quick check for unsupported types:
    if media_type.startswith("video/") or media_type == "application/gliffy+json":
        logger.warning(
            f"Skipping unsupported attachment type: '{media_type}' for {attachment['title']}"
        )
        return None

    result = _extract_or_summarize_attachment(
        confluence_client, attachment, page_context, llm
    )
    if result.error is not None:
        # It's up to you if you'd like to treat errors as skip scenarios or propagate further
        logger.debug(
            f"Attachment {attachment['title']} encountered error: {result.error}"
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
    if is_cloud and not base_url.endswith("/wiki"):
        base_url += "/wiki"
    return f"{base_url}{content_url}"


def _extract_referenced_attachment_names(page_text: str) -> list[str]:
    """Parse a Confluence html page to generate a list of current
        attachments in use

    Args:
        text (str): The page content

    Returns:
        list[str]: List of filenames currently in use by the page text
    """
    referenced_attachment_filenames = []
    soup = bs4.BeautifulSoup(page_text, "html.parser")
    for attachment in soup.findAll("ri:attachment"):
        referenced_attachment_filenames.append(attachment.attrs["ri:filename"])
    return referenced_attachment_filenames


def datetime_from_string(datetime_string: str) -> datetime:
    datetime_object = datetime.fromisoformat(datetime_string)

    if datetime_object.tzinfo is None:
        # If no timezone info, assume it is UTC
        datetime_object = datetime_object.replace(tzinfo=timezone.utc)
    else:
        # If not in UTC, translate it
        datetime_object = datetime_object.astimezone(timezone.utc)

    return datetime_object


def attachment_to_file_record(
    confluence_client: OnyxConfluence,
    attachment: dict[str, Any],
    db_session: Session,
) -> tuple[PGFileStore, bytes]:
    """Save an attachment to the file store and return the file record."""
    download_link = _attachment_to_download_link(confluence_client, attachment)
    image_data = confluence_client.get(
        download_link, absolute=True, not_json_response=True
    )

    # Save image to file store
    file_name = f"confluence_attachment_{attachment['id']}"
    lobj_oid = create_populate_lobj(BytesIO(image_data), db_session)
    pgfilestore = upsert_pgfilestore(
        file_name=file_name,
        display_name=attachment["title"],
        file_origin=FileOrigin.OTHER,
        file_type=attachment["metadata"]["mediaType"],
        lobj_oid=lobj_oid,
        db_session=db_session,
        commit=True,
    )

    return pgfilestore, image_data


def _attachment_to_download_link(
    confluence_client: OnyxConfluence, attachment: dict[str, Any]
) -> str:
    """Extracts the download link to images."""
    return confluence_client.url + attachment["_links"]["download"]


def _summarize_image_attachment(
    attachment: dict[str, Any],
    page_context: str,
    llm: LLM,
    confluence_client: OnyxConfluence,
) -> tuple[str, str]:
    """Summarize an image attachment using the LLM and save to file store."""
    try:
        user_prompt = IMAGE_SUMMARIZATION_USER_PROMPT.format(
            title=attachment["title"],
            page_title=attachment["title"],
            confluence_xml=page_context,
        )
        with get_session_with_current_tenant() as db_session:
            file_record, file_data = attachment_to_file_record(
                confluence_client=confluence_client,
                attachment=attachment,
                db_session=db_session,
            )

        return (
            summarize_image_pipeline(
                llm=llm,
                image_data=file_data,
                query=user_prompt,
                system_prompt=IMAGE_SUMMARIZATION_SYSTEM_PROMPT,
            ),
            file_record.file_name,
        )

    except Exception as e:
        raise ValueError(
            f"Image summarization failed for {attachment['title']}: {e}"
        ) from e
