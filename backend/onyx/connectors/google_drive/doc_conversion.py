import io
from collections.abc import Callable
from datetime import datetime
from typing import Any
from typing import cast
from urllib.parse import urlparse
from urllib.parse import urlunparse

from googleapiclient.errors import HttpError  # type: ignore
from googleapiclient.http import MediaIoBaseDownload  # type: ignore
from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.constants import DRIVE_SHORTCUT_TYPE
from onyx.connectors.google_drive.models import GDriveMimeType
from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_drive.section_extraction import get_document_sections
from onyx.connectors.google_drive.section_extraction import HEADING_DELIMITER
from onyx.connectors.google_utils.resources import get_drive_service
from onyx.connectors.google_utils.resources import get_google_docs_service
from onyx.connectors.google_utils.resources import GoogleDocsService
from onyx.connectors.google_utils.resources import GoogleDriveService
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import ALL_ACCEPTED_FILE_EXTENSIONS
from onyx.file_processing.extract_file_text import docx_to_text_and_images
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.extract_file_text import pptx_to_text
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.extract_file_text import xlsx_to_text
from onyx.file_processing.file_validation import is_valid_image_type
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)
from onyx.utils.variable_functionality import noop_fallback

logger = setup_logger()

# This is not a standard valid unicode char, it is used by the docs advanced API to
# represent smart chips (elements like dates and doc links).
SMART_CHIP_CHAR = "\ue907"
WEB_VIEW_LINK_KEY = "webViewLink"

MAX_RETRIEVER_EMAILS = 20
CHUNK_SIZE_BUFFER = 64  # extra bytes past the limit to read

# Mapping of Google Drive mime types to export formats
GOOGLE_MIME_TYPES_TO_EXPORT = {
    GDriveMimeType.DOC.value: "text/plain",
    GDriveMimeType.SPREADSHEET.value: "text/csv",
    GDriveMimeType.PPT.value: "text/plain",
}

# Define Google MIME types mapping
GOOGLE_MIME_TYPES = {
    GDriveMimeType.DOC.value: "text/plain",
    GDriveMimeType.SPREADSHEET.value: "text/csv",
    GDriveMimeType.PPT.value: "text/plain",
}


class PermissionSyncContext(BaseModel):
    """
    This is the information that is needed to sync permissions for a document.
    """

    primary_admin_email: str
    google_domain: str


def onyx_document_id_from_drive_file(file: GoogleDriveFileType) -> str:
    link = file[WEB_VIEW_LINK_KEY]
    parsed_url = urlparse(link)
    parsed_url = parsed_url._replace(query="")  # remove query parameters
    spl_path = parsed_url.path.split("/")
    if spl_path and (spl_path[-1] in ["edit", "view", "preview"]):
        spl_path.pop()
        parsed_url = parsed_url._replace(path="/".join(spl_path))
    # Remove query parameters and reconstruct URL
    return urlunparse(parsed_url)


def is_gdrive_image_mime_type(mime_type: str) -> bool:
    """
    Return True if the mime_type is a common image type in GDrive.
    (e.g. 'image/png', 'image/jpeg')
    """
    return is_valid_image_type(mime_type)


def download_request(
    service: GoogleDriveService, file_id: str, size_threshold: int
) -> bytes:
    """
    Download the file from Google Drive.
    """
    # For other file types, download the file
    # Use the correct API call for downloading files
    request = service.files().get_media(fileId=file_id)
    return _download_request(request, file_id, size_threshold)


def _download_request(request: Any, file_id: str, size_threshold: int) -> bytes:
    response_bytes = io.BytesIO()
    downloader = MediaIoBaseDownload(
        response_bytes, request, chunksize=size_threshold + CHUNK_SIZE_BUFFER
    )
    done = False
    while not done:
        download_progress, done = downloader.next_chunk()
        if download_progress.resumable_progress > size_threshold:
            logger.warning(
                f"File {file_id} exceeds size threshold of {size_threshold}. Skipping2."
            )
            return bytes()

    response = response_bytes.getvalue()
    if not response:
        logger.warning(f"Failed to download {file_id}")
        return bytes()
    return response


def _download_and_extract_sections_basic(
    file: dict[str, str],
    service: GoogleDriveService,
    allow_images: bool,
    size_threshold: int,
) -> list[TextSection | ImageSection]:
    """Extract text and images from a Google Drive file."""
    file_id = file["id"]
    file_name = file["name"]
    mime_type = file["mimeType"]
    link = file.get(WEB_VIEW_LINK_KEY, "")

    # For non-Google files, download the file
    # Use the correct API call for downloading files
    # lazy evaluation to only download the file if necessary
    def response_call() -> bytes:
        return download_request(service, file_id, size_threshold)

    if is_gdrive_image_mime_type(mime_type):
        # Skip images if not explicitly enabled
        if not allow_images:
            return []

        # Store images for later processing
        sections: list[TextSection | ImageSection] = []
        try:
            section, embedded_id = store_image_and_create_section(
                image_data=response_call(),
                file_id=file_id,
                display_name=file_name,
                media_type=mime_type,
                file_origin=FileOrigin.CONNECTOR,
                link=link,
            )
            sections.append(section)
        except Exception as e:
            logger.error(f"Failed to process image {file_name}: {e}")
        return sections

    # For Google Docs, Sheets, and Slides, export as plain text
    if mime_type in GOOGLE_MIME_TYPES_TO_EXPORT:
        export_mime_type = GOOGLE_MIME_TYPES_TO_EXPORT[mime_type]
        # Use the correct API call for exporting files
        request = service.files().export_media(
            fileId=file_id, mimeType=export_mime_type
        )
        response = _download_request(request, file_id, size_threshold)
        if not response:
            logger.warning(f"Failed to export {file_name} as {export_mime_type}")
            return []

        text = response.decode("utf-8")
        return [TextSection(link=link, text=text)]

    # Process based on mime type
    if mime_type == "text/plain":
        try:
            text = response_call().decode("utf-8")
            return [TextSection(link=link, text=text)]
        except UnicodeDecodeError as e:
            logger.warning(f"Failed to extract text from {file_name}: {e}")
            return []

    elif (
        mime_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        text, _ = docx_to_text_and_images(io.BytesIO(response_call()))
        return [TextSection(link=link, text=text)]

    elif (
        mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ):
        text = xlsx_to_text(io.BytesIO(response_call()), file_name=file_name)
        return [TextSection(link=link, text=text)] if text else []

    elif (
        mime_type
        == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ):
        text = pptx_to_text(io.BytesIO(response_call()), file_name=file_name)
        return [TextSection(link=link, text=text)] if text else []

    elif mime_type == "application/pdf":
        text, _pdf_meta, images = read_pdf_file(io.BytesIO(response_call()))
        pdf_sections: list[TextSection | ImageSection] = [
            TextSection(link=link, text=text)
        ]

        # Process embedded images in the PDF
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

    # Final attempt at extracting text
    file_ext = get_file_ext(file.get("name", ""))
    if file_ext not in ALL_ACCEPTED_FILE_EXTENSIONS:
        logger.warning(f"Skipping file {file.get('name')} due to extension.")
        return []

    try:
        text = extract_file_text(io.BytesIO(response_call()), file_name)
        return [TextSection(link=link, text=text)]
    except Exception as e:
        logger.warning(f"Failed to extract text from {file_name}: {e}")
        return []


def _find_nth(haystack: str, needle: str, n: int, start: int = 0) -> int:
    start = haystack.find(needle, start)
    while start >= 0 and n > 1:
        start = haystack.find(needle, start + len(needle))
        n -= 1
    return start


def align_basic_advanced(
    basic_sections: list[TextSection | ImageSection], adv_sections: list[TextSection]
) -> list[TextSection | ImageSection]:
    """Align the basic sections with the advanced sections.
    In particular, the basic sections contain all content of the file,
    including smart chips like dates and doc links. The advanced sections
    are separated by section headers and contain header-based links that
    improve user experience when they click on the source in the UI.

    There are edge cases in text matching (i.e. the heading is a smart chip or
    there is a smart chip in the doc with text containing the actual heading text)
    that make the matching imperfect; this is hence done on a best-effort basis.
    """
    if len(adv_sections) <= 1:
        return basic_sections  # no benefit from aligning

    basic_full_text = "".join(
        [section.text for section in basic_sections if isinstance(section, TextSection)]
    )
    new_sections: list[TextSection | ImageSection] = []
    heading_start = 0
    for adv_ind in range(1, len(adv_sections)):
        heading = adv_sections[adv_ind].text.split(HEADING_DELIMITER)[0]
        # retrieve the longest part of the heading that is not a smart chip
        heading_key = max(heading.split(SMART_CHIP_CHAR), key=len).strip()
        if heading_key == "":
            logger.warning(
                f"Cannot match heading: {heading}, its link will come from the following section"
            )
            continue
        heading_offset = heading.find(heading_key)

        # count occurrences of heading str in previous section
        heading_count = adv_sections[adv_ind - 1].text.count(heading_key)

        prev_start = heading_start
        heading_start = (
            _find_nth(basic_full_text, heading_key, heading_count, start=prev_start)
            - heading_offset
        )
        if heading_start < 0:
            logger.warning(
                f"Heading key {heading_key} from heading {heading} not found in basic text"
            )
            heading_start = prev_start
            continue

        new_sections.append(
            TextSection(
                link=adv_sections[adv_ind - 1].link,
                text=basic_full_text[prev_start:heading_start],
            )
        )

    # handle last section
    new_sections.append(
        TextSection(link=adv_sections[-1].link, text=basic_full_text[heading_start:])
    )
    return new_sections


def _get_external_access_for_raw_gdrive_file(
    file: GoogleDriveFileType,
    company_domain: str,
    retriever_drive_service: GoogleDriveService | None,
    admin_drive_service: GoogleDriveService,
) -> ExternalAccess:
    """
    Get the external access for a raw Google Drive file.
    """
    external_access_fn = cast(
        Callable[
            [GoogleDriveFileType, str, GoogleDriveService | None, GoogleDriveService],
            ExternalAccess,
        ],
        fetch_versioned_implementation_with_fallback(
            "onyx.external_permissions.google_drive.doc_sync",
            "get_external_access_for_raw_gdrive_file",
            fallback=noop_fallback,
        ),
    )
    return external_access_fn(
        file,
        company_domain,
        retriever_drive_service,
        admin_drive_service,
    )


def convert_drive_item_to_document(
    creds: Any,
    allow_images: bool,
    size_threshold: int,
    # if not specified, we will not sync permissions
    # will also be a no-op if EE is not enabled
    permission_sync_context: PermissionSyncContext | None,
    retriever_emails: list[str],
    file: GoogleDriveFileType,
) -> Document | ConnectorFailure | None:
    """
    Attempt to convert a drive item to a document with each retriever email
    in order. returns upon a successful retrieval or a non-403 error.

    We used to always get the user email from the file owners when available,
    but this was causing issues with shared folders where the owner was not included in the service account
    now we use the email of the account that successfully listed the file. There are cases where a
    user that can list a file cannot download it, so we retry with file owners and admin email.
    """
    first_error = None
    doc_or_failure = None
    retriever_emails = retriever_emails[:MAX_RETRIEVER_EMAILS]
    # use seen instead of list(set()) to avoid re-ordering the retriever emails
    seen = set()
    for retriever_email in retriever_emails:
        if retriever_email in seen:
            continue
        seen.add(retriever_email)
        doc_or_failure = _convert_drive_item_to_document(
            creds,
            allow_images,
            size_threshold,
            retriever_email,
            file,
            permission_sync_context,
        )

        # There are a variety of permissions-based errors that occasionally occur
        # when retrieving files. Often when these occur, there is another user
        # that can successfully retrieve the file, so we try the next user.
        if (
            doc_or_failure is None
            or isinstance(doc_or_failure, Document)
            or not (
                isinstance(doc_or_failure.exception, HttpError)
                and doc_or_failure.exception.status_code in [401, 403, 404]
            )
        ):
            return doc_or_failure

        if first_error is None:
            first_error = doc_or_failure
        else:
            first_error.failure_message += f"\n\n{doc_or_failure.failure_message}"

    if (
        first_error
        and isinstance(first_error.exception, HttpError)
        and first_error.exception.status_code == 403
    ):
        # This SHOULD happen very rarely, and we don't want to break the indexing process when
        # a high volume of 403s occurs early. We leave a verbose log to help investigate.
        logger.error(
            f"Skipping file id: {file.get('id')} name: {file.get('name')} due to 403 error."
            f"Attempted to retrieve with {retriever_emails},"
            f"got the following errors: {first_error.failure_message}"
        )
        return None
    return first_error


def _convert_drive_item_to_document(
    creds: Any,
    allow_images: bool,
    size_threshold: int,
    retriever_email: str,
    file: GoogleDriveFileType,
    # if not specified, we will not sync permissions
    # will also be a no-op if EE is not enabled
    permission_sync_context: PermissionSyncContext | None,
) -> Document | ConnectorFailure | None:
    """
    Main entry point for converting a Google Drive file => Document object.
    """
    sections: list[TextSection | ImageSection] = []

    # Only construct these services when needed
    def _get_drive_service() -> GoogleDriveService:
        return get_drive_service(creds, user_email=retriever_email)

    def _get_docs_service() -> GoogleDocsService:
        return get_google_docs_service(creds, user_email=retriever_email)

    doc_id = "unknown"

    try:
        # skip shortcuts or folders
        if file.get("mimeType") in [DRIVE_SHORTCUT_TYPE, DRIVE_FOLDER_TYPE]:
            logger.info("Skipping shortcut/folder.")
            return None

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

        # If it's a Google Doc, we might do advanced parsing
        if file.get("mimeType") == GDriveMimeType.DOC.value:
            try:
                logger.debug(f"starting advanced parsing for {file.get('name')}")
                # get_document_sections is the advanced approach for Google Docs
                doc_sections = get_document_sections(
                    docs_service=_get_docs_service(),
                    doc_id=file.get("id", ""),
                )
                if doc_sections:
                    sections = cast(list[TextSection | ImageSection], doc_sections)
                    if any(SMART_CHIP_CHAR in section.text for section in doc_sections):
                        logger.debug(
                            f"found smart chips in {file.get('name')},"
                            " aligning with basic sections"
                        )
                        basic_sections = _download_and_extract_sections_basic(
                            file, _get_drive_service(), allow_images, size_threshold
                        )
                        sections = align_basic_advanced(basic_sections, doc_sections)

            except Exception as e:
                logger.warning(
                    f"Error in advanced parsing: {e}. Falling back to basic extraction."
                )
        # Not Google Doc, attempt basic extraction
        else:
            sections = _download_and_extract_sections_basic(
                file, _get_drive_service(), allow_images, size_threshold
            )

        # If we still don't have any sections, skip this file
        if not sections:
            logger.warning(f"No content extracted from {file.get('name')}. Skipping.")
            return None

        doc_id = onyx_document_id_from_drive_file(file)
        external_access = (
            _get_external_access_for_raw_gdrive_file(
                file=file,
                company_domain=permission_sync_context.google_domain,
                # try both retriever_email and primary_admin_email if necessary
                retriever_drive_service=_get_drive_service(),
                admin_drive_service=get_drive_service(
                    creds, user_email=permission_sync_context.primary_admin_email
                ),
            )
            if permission_sync_context
            else None
        )

        # Create the document
        return Document(
            id=doc_id,
            sections=sections,
            source=DocumentSource.GOOGLE_DRIVE,
            semantic_identifier=file.get("name", ""),
            metadata={
                "owner_names": ", ".join(
                    owner.get("displayName", "") for owner in file.get("owners", [])
                ),
            },
            doc_updated_at=datetime.fromisoformat(
                file.get("modifiedTime", "").replace("Z", "+00:00")
            ),
            external_access=external_access,
        )
    except Exception as e:
        doc_id = "unknown"
        try:
            doc_id = onyx_document_id_from_drive_file(file)
        except Exception as e2:
            logger.warning(f"Error getting document id from file: {e2}")

        file_name = file.get("name")
        error_str = (
            f"Error converting file '{file_name}' to Document as {retriever_email}: {e}"
        )
        if isinstance(e, HttpError) and e.status_code == 403:
            logger.warning(
                f"Uncommon permissions error while downloading file. User "
                f"{retriever_email} was able to see file {file_name} "
                "but cannot download it."
            )
            logger.warning(error_str)

        return ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=doc_id,
                document_link=(
                    sections[0].link if sections else None
                ),  # TODO: see if this is the best way to get a link
            ),
            failed_entity=None,
            failure_message=error_str,
            exception=e,
        )


def build_slim_document(
    creds: Any,
    file: GoogleDriveFileType,
    # if not specified, we will not sync permissions
    # will also be a no-op if EE is not enabled
    permission_sync_context: PermissionSyncContext | None,
) -> SlimDocument | None:
    if file.get("mimeType") in [DRIVE_FOLDER_TYPE, DRIVE_SHORTCUT_TYPE]:
        return None

    owner_email = cast(str | None, file.get("owners", [{}])[0].get("emailAddress"))
    external_access = (
        _get_external_access_for_raw_gdrive_file(
            file=file,
            company_domain=permission_sync_context.google_domain,
            retriever_drive_service=(
                get_drive_service(
                    creds,
                    user_email=owner_email,
                )
                if owner_email
                else None
            ),
            admin_drive_service=get_drive_service(
                creds,
                user_email=permission_sync_context.primary_admin_email,
            ),
        )
        if permission_sync_context
        else None
    )
    return SlimDocument(
        id=onyx_document_id_from_drive_file(file),
        external_access=external_access,
    )
