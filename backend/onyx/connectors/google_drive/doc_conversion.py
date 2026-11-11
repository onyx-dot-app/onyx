import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple, cast
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import (
    GOOGLE_DRIVE_ADVANCED_PARSE_MAX_BYTES,
    SKIP_SPREADSHEET_CONTENT,
)
from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.connectors.cross_connector_utils.section_utils import cap_sections_text
from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    extract_and_stage_tabular_file,
    is_tabular_file,
)
from onyx.connectors.google_drive.constants import (
    DRIVE_FOLDER_TYPE,
    DRIVE_RESOURCE_KEY_FIELD,
    DRIVE_SHORTCUT_TYPE,
    GOOGLE_APPS_MIME_PREFIX,
)
from onyx.connectors.google_drive.file_retrieval import has_link_only_permission
from onyx.connectors.google_drive.form_extraction import get_form_text
from onyx.connectors.google_drive.models import (
    DriveListingPayload,
    GDriveMimeType,
    GoogleDriveFileType,
)
from onyx.connectors.google_drive.section_extraction import (
    HEADING_DELIMITER,
    get_document_sections,
)
from onyx.connectors.google_drive.source_operations import (
    ExportSizeThresholdExceeded,
    GoogleDriveHttpError,
    GoogleDriveSourceOperations,
    is_transient_google_error,
)
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    ImageSection,
    SlimDocument,
    SlimDocumentStub,
    TabularSection,
    TextSection,
)
from onyx.file_processing.extract_file_text import (
    extract_file_text,
    read_docx_file,
    read_pdf_file,
    read_pptx_file,
)
from onyx.file_processing.file_types import (
    PRESENTATION_MIME_TYPE,
    SPREADSHEET_MIME_TYPE,
    OnyxMimeTypes,
    is_indexable_file_type,
)
from onyx.file_processing.image_utils import (
    make_image_callback,
    store_image_and_create_section,
)
from onyx.file_store.staging import RawFileCallback
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
    noop_fallback,
)

logger = setup_logger()


class FileExtractionResult(BaseModel):
    sections: list[TextSection | ImageSection | TabularSection]
    staged_file_id: str | None = None
    # Why the read gives no document, when the content or an API decides it.
    skip_reason: str | None = None


# Cache for folder path lookups to avoid redundant API calls
# Maps folder_id -> (folder_name, parent_id)
_folder_cache: dict[str, tuple[str, str | None]] = {}


def _get_folder_info(
    ops: GoogleDriveSourceOperations, user_email: str, folder_id: str
) -> tuple[str, str | None]:
    """Fetch folder name and parent ID, with caching."""
    if folder_id in _folder_cache:
        return _folder_cache[folder_id]

    try:
        folder = ops.get_file(
            user_email=user_email, file_id=folder_id, fields="name, parents"
        )
    except GoogleDriveHttpError as e:
        logger.warning("Failed to get folder info for %s: %s", folder_id, e)
        folder = None
    if folder is None:
        _folder_cache[folder_id] = ("Unknown", None)
        return "Unknown", None
    folder_name = folder.get("name", "Unknown")
    parents = folder.get("parents", [])
    parent_id = parents[0] if parents else None
    _folder_cache[folder_id] = (folder_name, parent_id)
    return folder_name, parent_id


def _get_drive_name(
    ops: GoogleDriveSourceOperations, user_email: str, drive_id: str
) -> str:
    """Fetch shared drive name."""
    cache_key = f"drive_{drive_id}"
    if cache_key in _folder_cache:
        return _folder_cache[cache_key][0]

    try:
        drive_name = ops.get_shared_drive_name(user_email=user_email, drive_id=drive_id)
    except GoogleDriveHttpError as e:
        logger.warning("Failed to get drive name for %s: %s", drive_id, e)
        drive_name = None
    drive_name = drive_name or f"Shared Drive {drive_id}"
    _folder_cache[cache_key] = (drive_name, None)
    return drive_name


def build_folder_path(
    file: GoogleDriveFileType,
    ops: GoogleDriveSourceOperations,
    user_email: str,
    drive_id: str | None = None,
) -> list[str]:
    """
    Build the full folder path for a file by walking up the parent chain.
    Returns a list of folder names from root to immediate parent.

    Args:
        file: The Google Drive file object
        ops: The gateway that reads the folders
        user_email: The user to read the folders as. Also decides "My Drive"
            vs "Shared with me" by ownership.
        drive_id: Optional drive ID (will be extracted from file if not provided)
    """
    path_parts: list[str] = []

    # Get drive_id from file if not provided
    if drive_id is None:
        drive_id = file.get("driveId")

    # Check if file is owned by the user (for distinguishing "My Drive" vs "Shared with me")
    owners = file.get("owners", [])
    is_owned_by_user = any(
        owner.get("emailAddress", "").lower() == user_email.lower() for owner in owners
    )

    # Get the file's parent folder ID
    parents = file.get("parents", [])
    if not parents:
        # File is at root level
        if drive_id:
            return [_get_drive_name(ops, user_email, drive_id)]
        # If not in a shared drive, check if it's owned by the user
        if is_owned_by_user:
            return ["My Drive"]
        else:
            return ["Shared with me"]

    parent_id: str | None = parents[0]

    # Walk up the folder hierarchy (limit to 50 levels to prevent infinite loops)
    visited: set[str] = set()
    for _ in range(50):
        if not parent_id or parent_id in visited:
            break
        visited.add(parent_id)

        folder_name, next_parent = _get_folder_info(ops, user_email, parent_id)

        # Check if we've reached the root (parent is the drive itself or no parent)
        if next_parent is None:
            # This folder's name is either the drive root, My Drive, or Shared with me
            if drive_id:
                path_parts.insert(0, _get_drive_name(ops, user_email, drive_id))
            else:
                # Not in a shared drive - determine if it's "My Drive" or "Shared with me"
                if is_owned_by_user:
                    path_parts.insert(0, "My Drive")
                else:
                    path_parts.insert(0, "Shared with me")
            break
        else:
            path_parts.insert(0, folder_name)
            parent_id = next_parent

    # If we didn't find a root, determine the root based on ownership and drive
    if not path_parts:
        if drive_id:
            return [_get_drive_name(ops, user_email, drive_id)]
        elif is_owned_by_user:
            return ["My Drive"]
        else:
            return ["Shared with me"]

    return path_parts


# This is not a standard valid unicode char, it is used by the docs advanced API to
# represent smart chips (elements like dates and doc links).
SMART_CHIP_CHAR = "\ue907"
WEB_VIEW_LINK_KEY = "webViewLink"
# Fallback templates for generating web links when Drive omits webViewLink.
_FALLBACK_WEB_VIEW_LINK_TEMPLATES = {
    GDriveMimeType.DOC.value: "https://docs.google.com/document/d/{}/view",
    GDriveMimeType.SPREADSHEET.value: "https://docs.google.com/spreadsheets/d/{}/view",
    GDriveMimeType.PPT.value: "https://docs.google.com/presentation/d/{}/view",
    GDriveMimeType.FORM.value: "https://docs.google.com/forms/d/{}/view",
}
# Fallback template for non-native (uploaded binary) Drive files.
_FALLBACK_BINARY_WEB_VIEW_LINK_TEMPLATE = "https://drive.google.com/file/d/{}/view"

MAX_RETRIEVER_EMAILS = 20
# Above this many advanced sections, skip align_basic_advanced (its heading
# matching is ~O(headings x doc length)) and index the unaligned sections.
ADVANCED_PARSE_MAX_SECTIONS = 2000

# Mapping of Google Drive mime types to export formats
GOOGLE_MIME_TYPES_TO_EXPORT = {
    GDriveMimeType.DOC.value: "text/plain",
    GDriveMimeType.SPREADSHEET.value: "text/csv",
    GDriveMimeType.PPT.value: PRESENTATION_MIME_TYPE,
}


class PermissionSyncContext(BaseModel):
    """
    This is the information that is needed to sync permissions for a document.
    """

    primary_admin_email: str
    google_domain: str


def onyx_document_id_from_drive_file(file: GoogleDriveFileType) -> str:
    link = file.get(WEB_VIEW_LINK_KEY)
    if not link:
        file_id = file.get("id")
        if not file_id:
            raise KeyError(
                f"Google Drive file missing both '{WEB_VIEW_LINK_KEY}' and 'id' fields."
            )
        mime_type = file.get("mimeType", "")
        template = _FALLBACK_WEB_VIEW_LINK_TEMPLATES.get(mime_type)
        if template is None:
            link = _FALLBACK_BINARY_WEB_VIEW_LINK_TEMPLATE.format(file_id)
        else:
            link = template.format(file_id)
        logger.debug(
            "Missing webViewLink for Google Drive file with id %s. Falling back to constructed link %s",
            file_id,
            link,
        )
    parsed_url = urlparse(link)
    parsed_url = parsed_url._replace(query="")  # remove query parameters
    spl_path = parsed_url.path.split("/")
    if spl_path and (spl_path[-1] in ["edit", "view", "preview"]):
        spl_path.pop()
        parsed_url = parsed_url._replace(path="/".join(spl_path))
    # Remove query parameters and reconstruct URL
    return urlunparse(parsed_url)


@dataclass(frozen=True)
class _DriveFileRead:
    """One read of a Drive file's content as one user."""

    file: GoogleDriveFileType
    ops: GoogleDriveSourceOperations
    retriever_email: str
    allow_images: bool
    size_threshold: int
    raw_file_callback: RawFileCallback | None

    @property
    def file_id(self) -> str:
        return self.file["id"]

    @property
    def name(self) -> str:
        return self.file["name"]

    @property
    def mime_type(self) -> str:
        return self.file["mimeType"]

    @property
    def link(self) -> str:
        return self.file.get(WEB_VIEW_LINK_KEY, "")

    def download(self) -> bytes:
        return self.ops.download_file(
            user_email=self.retriever_email,
            file_id=self.file_id,
            size_threshold=self.size_threshold,
            resource_key=self.file.get(DRIVE_RESOURCE_KEY_FIELD),
        )

    def export(self, mime_type: str) -> bytes:
        return self.ops.export_file(
            user_email=self.retriever_email,
            file_id=self.file_id,
            mime_type=mime_type,
            size_threshold=self.size_threshold,
            resource_key=self.file.get(DRIVE_RESOURCE_KEY_FIELD),
        )

    def text(self, text: str) -> FileExtractionResult:
        return FileExtractionResult(sections=[TextSection(link=self.link, text=text)])

    def tabular(
        self, raw_bytes: bytes, name: str, content_type: str
    ) -> FileExtractionResult:
        if self.raw_file_callback is None:
            return FileExtractionResult(
                sections=[], skip_reason="a tabular file needs a raw file callback"
            )
        result = extract_and_stage_tabular_file(
            file=io.BytesIO(raw_bytes),
            file_name=name,
            content_type=content_type,
            raw_file_callback=self.raw_file_callback,
            link=self.link,
            skip_content=SKIP_SPREADSHEET_CONTENT,
        )
        return FileExtractionResult(
            sections=list(result.sections), staged_file_id=result.staged_file_id
        )

    def pptx(self, data: bytes) -> FileExtractionResult:
        sections: list[TextSection | ImageSection | TabularSection] = []
        text, _ = read_pptx_file(
            io.BytesIO(data),
            file_name=self.name,
            extract_images=self.allow_images,
            image_callback=make_image_callback(
                sections, self.file_id, self.name, self.link
            ),
        )
        if text:
            sections.insert(0, TextSection(link=self.link, text=text))
        return FileExtractionResult(sections=sections)


def _read_image(read: _DriveFileRead) -> FileExtractionResult:
    sections: list[TextSection | ImageSection | TabularSection] = []
    # Download outside the try: a failed download must fail the document,
    # not drop it.
    image_data = read.download()
    try:
        section, _ = store_image_and_create_section(
            image_data=image_data,
            file_id=read.file_id,
            display_name=read.name,
            media_type=read.mime_type,
            file_origin=FileOrigin.CONNECTOR,
            link=read.link,
        )
        sections.append(section)
    except Exception as e:
        logger.error("Failed to process image %s: %s", read.name, e)
    return FileExtractionResult(sections=sections)


def _read_google_export(read: _DriveFileRead) -> FileExtractionResult:
    """Google Docs, Sheets and Slides: Drive exports them to a file type."""
    export_mime_type = GOOGLE_MIME_TYPES_TO_EXPORT[read.mime_type]
    response = read.export(export_mime_type)
    if not response:
        logger.warning("Failed to export %s as %s", read.name, export_mime_type)
        return FileExtractionResult(sections=[])
    if export_mime_type in OnyxMimeTypes.TABULAR_MIME_TYPES:
        # Synthesize an extension on the filename
        ext = ".xlsx" if export_mime_type == SPREADSHEET_MIME_TYPE else ".csv"
        return read.tabular(response, f"{read.name}{ext}", export_mime_type)
    if export_mime_type == PRESENTATION_MIME_TYPE:
        return read.pptx(response)
    return read.text(response.decode("utf-8"))


def _read_google_form(read: _DriveFileRead) -> FileExtractionResult:
    """Drive cannot export a Google Form; the Forms API reads its questions."""
    try:
        form = read.ops.fetch_google_form(
            user_email=read.retriever_email,
            form_id=read.file_id,
            max_response_bytes=read.size_threshold,
        )
    except GoogleDriveHttpError as e:
        if not e.api_disabled:
            raise
        return FileExtractionResult(
            sections=[], skip_reason="the Google Forms API is off"
        )
    if form is None:
        return FileExtractionResult(
            sections=[],
            skip_reason=f"the form exceeds the size threshold of {read.size_threshold}",
        )
    form_text = get_form_text(form)
    return read.text(form_text) if form_text else FileExtractionResult(sections=[])


def _read_plain_text(read: _DriveFileRead) -> FileExtractionResult:
    try:
        return read.text(read.download().decode("utf-8"))
    except UnicodeDecodeError as e:
        logger.warning("Failed to extract text from %s: %s", read.name, e)
        return FileExtractionResult(sections=[])


def _read_docx(read: _DriveFileRead) -> FileExtractionResult:
    text, _ = read_docx_file(io.BytesIO(read.download()))
    return read.text(text)


def _read_tabular(read: _DriveFileRead) -> FileExtractionResult:
    # Google Drive doesn't enforce file extensions, so an xlsx file may not
    # end in .xlsx. Synthesize the extension so tabular_file_to_sections
    # dispatches correctly.
    name = read.name if is_tabular_file(read.name) else f"{read.name}.xlsx"
    return read.tabular(read.download(), name, read.mime_type)


def _read_pptx(read: _DriveFileRead) -> FileExtractionResult:
    return read.pptx(read.download())


def _read_pdf(read: _DriveFileRead) -> FileExtractionResult:
    text, _pdf_meta, images = read_pdf_file(io.BytesIO(read.download()))
    sections: list[TextSection | ImageSection | TabularSection] = [
        TextSection(link=read.link, text=text)
    ]
    # Process embedded images in the PDF
    try:
        for idx, (img_data, img_name) in enumerate(images):
            section, _ = store_image_and_create_section(
                image_data=img_data,
                file_id=f"{read.file_id}_img_{idx}",
                display_name=img_name or f"{read.name} - image {idx}",
                file_origin=FileOrigin.CONNECTOR,
            )
            sections.append(section)
    except Exception as e:
        logger.error("Failed to process PDF images in %s: %s", read.name, e)
    return FileExtractionResult(sections=sections)


def _read_by_extension(read: _DriveFileRead) -> FileExtractionResult:
    # Download outside the try: a failed download must fail the document, so
    # that the run reports it and tries the next user. A file that cannot be
    # parsed is still skipped.
    raw_bytes = read.download()
    try:
        return read.text(extract_file_text(io.BytesIO(raw_bytes), read.name))
    except Exception as e:
        logger.warning("Failed to extract text from %s: %s", read.name, e)
        return FileExtractionResult(sections=[])


class _MimeHandler(NamedTuple):
    read: Callable[[_DriveFileRead], FileExtractionResult]
    # The file is an image, so it needs allow_images.
    is_image: bool = False
    # The content is tabular, so it needs a raw file callback.
    is_tabular: bool = False


_TABULAR_HANDLER = _MimeHandler(_read_tabular, is_tabular=True)
# For a mime type not in the table. Text extraction selects a parser by the
# file extension.
_EXTENSION_HANDLER = _MimeHandler(_read_by_extension)

# Conversion reads a file with the handler for its mime type. The metadata
# check reads this table too, so it accepts each type that conversion reads.
_MIME_HANDLERS: dict[str, _MimeHandler] = {
    **{
        mime_type: _MimeHandler(_read_image, is_image=True)
        for mime_type in OnyxMimeTypes.IMAGE_MIME_TYPES
    },
    **{
        mime_type: _MimeHandler(
            _read_google_export,
            is_tabular=export_mime_type in OnyxMimeTypes.TABULAR_MIME_TYPES,
        )
        for mime_type, export_mime_type in GOOGLE_MIME_TYPES_TO_EXPORT.items()
    },
    GDriveMimeType.FORM.value: _MimeHandler(_read_google_form),
    GDriveMimeType.PLAIN_TEXT.value: _MimeHandler(_read_plain_text),
    GDriveMimeType.WORD_DOC.value: _MimeHandler(_read_docx),
    GDriveMimeType.SPREADSHEET_OPEN_FORMAT.value: _TABULAR_HANDLER,
    PRESENTATION_MIME_TYPE: _MimeHandler(_read_pptx),
    GDriveMimeType.PDF.value: _MimeHandler(_read_pdf),
}


def _mime_handler(mime_type: str, file_name: str) -> _MimeHandler:
    handler = _MIME_HANDLERS.get(mime_type)
    if handler is not None:
        return handler
    if is_tabular_file(file_name):
        return _TABULAR_HANDLER
    return _EXTENSION_HANDLER


def _download_and_extract_sections_basic(
    file: GoogleDriveFileType,
    ops: GoogleDriveSourceOperations,
    retriever_email: str,
    allow_images: bool,
    size_threshold: int,
    raw_file_callback: RawFileCallback | None = None,
) -> FileExtractionResult:
    """Extract text and images from a Google Drive file. Call it only for a
    file that passes `drive_file_skip_reason`."""
    read = _DriveFileRead(
        file=file,
        ops=ops,
        retriever_email=retriever_email,
        allow_images=allow_images,
        size_threshold=size_threshold,
        raw_file_callback=raw_file_callback,
    )
    try:
        return _mime_handler(read.mime_type, read.name).read(read)
    except ExportSizeThresholdExceeded:
        return FileExtractionResult(
            sections=[],
            skip_reason=f"the content exceeds the size threshold of {size_threshold}",
        )


def _find_nth(haystack: str, needle: str, n: int, start: int = 0) -> int:
    start = haystack.find(needle, start)
    while start >= 0 and n > 1:
        start = haystack.find(needle, start + len(needle))
        n -= 1
    return start


def align_basic_advanced(
    basic_sections: list[TextSection | ImageSection | TabularSection],
    adv_sections: list[TextSection],
) -> list[TextSection | ImageSection | TabularSection]:
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
    new_sections: list[TextSection | ImageSection | TabularSection] = []
    heading_start = 0
    for adv_ind in range(1, len(adv_sections)):
        heading = adv_sections[adv_ind].text.split(HEADING_DELIMITER)[0]
        # retrieve the longest part of the heading that is not a smart chip
        heading_key = max(heading.split(SMART_CHIP_CHAR), key=len).strip()
        if heading_key == "":
            logger.warning(
                "Cannot match heading: %s, its link will come from the following section",
                heading,
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
                "Heading key %s from heading %s not found in basic text",
                heading_key,
                heading,
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
    ops: GoogleDriveSourceOperations,
    retriever_email: str | None,
    admin_email: str,
    fallback_user_email: str,
    add_prefix: bool = False,
    fallback_retriever_email: str | None = None,
) -> ExternalAccess:
    """
    Get the external access for a raw Google Drive file.

    Permissions are read as ``retriever_email``, then as
    ``fallback_retriever_email``, then as ``admin_email``, until all are found.

    add_prefix: When True, prefix group IDs with source type (for indexing path).
               When False (default), leave unprefixed (for permission sync path
               where upsert_document_external_perms handles prefixing).
    fallback_user_email: When permission info can't be retrieved (e.g. externally-owned
               files), fall back to granting access to this user.
    """
    external_access_fn = cast(
        Callable[
            [
                GoogleDriveFileType,
                str,
                GoogleDriveSourceOperations,
                str | None,
                str,
                str,
                bool,
                str | None,
            ],
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
        ops,
        retriever_email,
        admin_email,
        fallback_user_email,
        add_prefix,
        fallback_retriever_email,
    )


def convert_drive_item_to_document(
    ops: GoogleDriveSourceOperations,
    allow_images: bool,
    size_threshold: int,
    # if not specified, we will not sync permissions
    # will also be a no-op if EE is not enabled
    permission_sync_context: PermissionSyncContext | None,
    retriever_emails: list[str],
    file: GoogleDriveFileType,
    raw_file_callback: RawFileCallback | None = None,
    folder_path: list[str] | None = None,
) -> Document | ConnectorFailure | None:
    """
    Attempt to convert a drive item to a document with each retriever email
    in order. returns upon a successful retrieval or a non-403 error.

    `folder_path` is the path the listing built. Without it, the path is
    built here from the file's parents.

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
            ops,
            allow_images,
            size_threshold,
            retriever_email,
            file,
            permission_sync_context,
            raw_file_callback,
            folder_path,
        )

        # There are a variety of permissions-based errors that occasionally occur
        # when retrieving files. Often when these occur, there is another user
        # that can successfully retrieve the file, so we try the next user.
        if (
            doc_or_failure is None
            or isinstance(doc_or_failure, Document)
            or not (
                isinstance(doc_or_failure.exception, GoogleDriveHttpError)
                and doc_or_failure.exception.status_code in [401, 403, 404]
                # Google also reports a rate limit as a 403.
                and not doc_or_failure.exception.rate_limited
            )
        ):
            return doc_or_failure

        if first_error is None:
            first_error = doc_or_failure
        else:
            first_error.failure_message += f"\n\n{doc_or_failure.failure_message}"

    if (
        first_error
        and isinstance(first_error.exception, GoogleDriveHttpError)
        and first_error.exception.status_code == 403
    ):
        # This SHOULD happen very rarely, and we don't want to break the indexing process when
        # a high volume of 403s occurs early. We leave a verbose log to help investigate.
        logger.error(
            "Skipping file id: %s name: %s due to 403 error.Attempted to retrieve with %s,got the following errors: %s",
            file.get("id"),
            file.get("name"),
            retriever_emails,
            first_error.failure_message,
        )
        return None
    return first_error


def drive_file_size(file: GoogleDriveFileType) -> int | None:
    """Byte size from the file listing, None when the listing has none."""
    size_str = file.get("size")
    if not size_str:
        return None
    try:
        return int(size_str)
    except ValueError:
        logger.warning("Parsing string to int failed: size_str=%s", size_str)
        return None


def _with_advanced_doc_sections(
    ops: GoogleDriveSourceOperations,
    retriever_email: str,
    file: GoogleDriveFileType,
    basic_sections: list[TextSection | ImageSection | TabularSection],
) -> list[TextSection | ImageSection | TabularSection]:
    """Heading-aware sections of a Google Doc. The basic export is within the
    size cap, so this parse is bounded. Falls back to the basic sections on
    any failure."""
    sections = basic_sections
    try:
        logger.debug("starting advanced parsing for %s", file.get("name"))
        google_doc = ops.fetch_google_doc(
            user_email=retriever_email,
            doc_id=file.get("id", ""),
            max_response_bytes=GOOGLE_DRIVE_ADVANCED_PARSE_MAX_BYTES,
        )
        doc_sections = (
            None
            if google_doc is None
            else get_document_sections(google_doc, file.get("id", ""))
        )
        if doc_sections is None:
            logger.info(
                "Advanced parse of %s exceeds %s bytes; keeping basic text.",
                file.get("name"),
                GOOGLE_DRIVE_ADVANCED_PARSE_MAX_BYTES,
            )
        elif doc_sections:
            has_smart_chips = any(
                SMART_CHIP_CHAR in section.text for section in doc_sections
            )
            if has_smart_chips and len(doc_sections) <= ADVANCED_PARSE_MAX_SECTIONS:
                logger.debug(
                    "found smart chips in %s, aligning with basic sections",
                    file.get("name"),
                )
                sections = align_basic_advanced(basic_sections, doc_sections)
            else:
                sections = cast(
                    list[TextSection | ImageSection | TabularSection],
                    doc_sections,
                )
    except Exception as e:
        # A rate limit that outlasted the retries fails the document, so the
        # next run fetches it again. Basic text would stay indexed until the
        # file changes.
        if is_transient_google_error(e):
            raise
        logger.warning("Error in advanced parsing: %s. Using basic extraction.", e)
    return sections


def _post_download_skip_reason(
    file: GoogleDriveFileType, extraction: FileExtractionResult
) -> str | None:
    """The post-download check: why the read content gives no document, None
    when it gives one. It caps the section text in place."""
    if extraction.skip_reason is not None:
        return extraction.skip_reason
    if not extraction.sections:
        return "no content extracted"
    extraction.sections = cap_sections_text(extraction.sections, file.get("name"))
    if not extraction.sections:
        return "no content within the text cap"
    return None


def _convert_drive_item_to_document(
    ops: GoogleDriveSourceOperations,
    allow_images: bool,
    size_threshold: int,
    retriever_email: str,
    file: GoogleDriveFileType,
    # if not specified, we will not sync permissions
    # will also be a no-op if EE is not enabled
    permission_sync_context: PermissionSyncContext | None,
    raw_file_callback: RawFileCallback | None = None,
    folder_path: list[str] | None = None,
) -> Document | ConnectorFailure | None:
    """
    Main entry point for converting a Google Drive file => Document object.
    """
    sections: list[TextSection | ImageSection | TabularSection] = []
    doc_id = "unknown"

    try:
        # The listing applies the link rule, so conversion does not.
        skip_reason = drive_file_skip_reason(
            file,
            allow_images=allow_images,
            size_threshold=size_threshold,
            has_raw_file_callback=raw_file_callback is not None,
            exclude_domain_link_only=False,
        )
        if skip_reason is not None:
            logger.info("Skipping %s: %s", file.get("name"), skip_reason)
            return None

        extraction = _download_and_extract_sections_basic(
            file,
            ops,
            retriever_email,
            allow_images,
            size_threshold,
            raw_file_callback,
        )
        sections = extraction.sections
        # A Google Doc within the size cap also gets heading-aware sections.
        if (
            file.get("mimeType") == GDriveMimeType.DOC.value
            and extraction.skip_reason is None
        ):
            extraction.sections = _with_advanced_doc_sections(
                ops, retriever_email, file, extraction.sections
            )

        skip_reason = _post_download_skip_reason(file, extraction)
        if skip_reason is not None:
            logger.warning("Skipping %s: %s", file.get("name"), skip_reason)
            return None
        sections = extraction.sections
        staged_file_id = extraction.staged_file_id
        size_bytes = drive_file_size(file)

        doc_id = onyx_document_id_from_drive_file(file)
        external_access = (
            _get_external_access_for_raw_gdrive_file(
                file=file,
                company_domain=permission_sync_context.google_domain,
                ops=ops,
                # try both retriever_email and primary_admin_email if necessary
                retriever_email=retriever_email,
                admin_email=permission_sync_context.primary_admin_email,
                add_prefix=True,  # Indexing path - prefix here
                fallback_user_email=retriever_email,
            )
            if permission_sync_context
            else None
        )

        # Build doc_metadata with hierarchy information
        file_name = file.get("name", "")
        mime_type = file.get("mimeType", "")
        drive_id = file.get("driveId")

        # Build full folder path by walking up the parent chain
        # Pass retriever_email to determine if file is in "My Drive" vs "Shared with me"
        source_path = (
            folder_path
            if folder_path is not None
            else build_folder_path(file, ops, retriever_email, drive_id)
        )

        doc_metadata = {
            "hierarchy": {
                "source_path": source_path,
                "drive_id": drive_id,
                "file_name": file_name,
                "mime_type": mime_type,
            }
        }

        # Create the document
        return Document(
            id=doc_id,
            sections=sections,
            source=DocumentSource.GOOGLE_DRIVE,
            semantic_identifier=file_name,
            doc_metadata=doc_metadata,
            metadata={
                "owner_names": ", ".join(
                    owner.get("displayName", "") for owner in file.get("owners", [])
                ),
            },
            doc_created_at=(
                datetime.fromisoformat(created_time)
                if (created_time := file.get("createdTime"))
                else None
            ),
            doc_updated_at=datetime.fromisoformat(file.get("modifiedTime", "")),
            external_access=external_access,
            parent_hierarchy_raw_node_id=(file.get("parents") or [None])[0],
            file_id=staged_file_id,
            source_mime_type=mime_type or None,
            source_size_bytes=size_bytes,
        )
    except Exception as e:
        doc_id = "unknown"
        try:
            doc_id = onyx_document_id_from_drive_file(file)
        except Exception as e2:
            logger.warning("Error getting document id from file: %s", e2)

        file_name = file.get("name")
        error_str = (
            f"Error converting file '{file_name}' to Document as {retriever_email}: {e}"
        )
        if isinstance(e, GoogleDriveHttpError) and e.status_code == 403:
            logger.warning(
                "Uncommon permissions error while downloading file. User %s was able to see file %s but cannot download it.",
                retriever_email,
                file_name,
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
    ops: GoogleDriveSourceOperations,
    file: GoogleDriveFileType,
    # if not specified, we will not sync permissions
    # will also be a no-op if EE is not enabled
    permission_sync_context: PermissionSyncContext | None,
    retriever_email: str,
) -> SlimDocument | None:
    if file.get("mimeType") in [DRIVE_FOLDER_TYPE, DRIVE_SHORTCUT_TYPE]:
        return None

    owner_email = cast(str | None, file.get("owners", [{}])[0].get("emailAddress"))
    external_access = (
        _get_external_access_for_raw_gdrive_file(
            file=file,
            company_domain=permission_sync_context.google_domain,
            ops=ops,
            retriever_email=owner_email,
            admin_email=permission_sync_context.primary_admin_email,
            fallback_user_email=retriever_email,
            fallback_retriever_email=(
                None if retriever_email == owner_email else retriever_email
            ),
        )
        if permission_sync_context
        else None
    )
    return SlimDocument(
        id=onyx_document_id_from_drive_file(file),
        external_access=external_access,
        parent_hierarchy_raw_node_id=(file.get("parents") or [None])[0],
        doc_created_at=(
            datetime.fromisoformat(created_time)
            if (created_time := file.get("createdTime"))
            else None
        ),
    )


def drive_file_skip_reason(
    file: GoogleDriveFileType,
    *,
    allow_images: bool,
    size_threshold: int,
    has_raw_file_callback: bool,
    exclude_domain_link_only: bool,
) -> str | None:
    """The metadata check: why conversion gives no document for this file,
    None when it may give one. It reads only the listed metadata, so the
    listing, pruning and conversion all use it. `_post_download_skip_reason`
    covers what only the content shows."""
    mime_type = file.get("mimeType", "")
    file_name = file.get("name", "")
    if mime_type in (DRIVE_SHORTCUT_TYPE, DRIVE_FOLDER_TYPE):
        return "a shortcut or folder is not a document"
    if exclude_domain_link_only and has_link_only_permission(file):
        return "only a link gives access, and such files are excluded"
    size_bytes = drive_file_size(file)
    if size_bytes is not None and size_bytes > size_threshold:
        return f"{size_bytes} bytes is over the size threshold of {size_threshold}"
    handler = _mime_handler(mime_type, file_name)
    if handler.is_image and not allow_images:
        return "images are off"
    if handler.is_tabular and not has_raw_file_callback:
        return "a tabular file needs a raw file callback"
    if handler is _EXTENSION_HANDLER:
        # Drive can download no Google type, and exports only those in the table.
        if mime_type.startswith(GOOGLE_APPS_MIME_PREFIX):
            return f"Drive cannot export {mime_type}"
        if not is_indexable_file_type(file_name, mime_type, allow_images):
            return f"the file type is not supported ({mime_type})"
    return None


def _domain_readers(file: GoogleDriveFileType, retriever_email: str) -> list[str]:
    """Users in the listing user's domain who can read the file: its owners
    and the users its permissions name. Only domain users can be
    impersonated. Permissions are present only when the listing asked for
    them."""
    domain = retriever_email.split("@")[-1].lower()
    emails = [owner.get("emailAddress") for owner in file.get("owners") or []] + [
        permission.get("emailAddress")
        for permission in file.get("permissions") or []
        if permission.get("type") == "user"
    ]
    readers: list[str] = []
    for email in emails:
        if (
            email
            and email.split("@")[-1].lower() == domain
            and email.lower() != retriever_email.lower()
            and email not in readers
        ):
            readers.append(email)
    return readers


def build_slim_document_stub(
    ops: GoogleDriveSourceOperations,
    file: GoogleDriveFileType,
    permission_sync_context: PermissionSyncContext | None,
    retriever_email: str,
) -> SlimDocumentStub | None:
    """`build_slim_document`, plus what a later conversion needs."""
    slim = build_slim_document(ops, file, permission_sync_context, retriever_email)
    if slim is None:
        return None
    return SlimDocumentStub(
        id=slim.id,
        external_access=slim.external_access,
        parent_hierarchy_raw_node_id=slim.parent_hierarchy_raw_node_id,
        doc_created_at=slim.doc_created_at,
        doc_updated_at=(
            datetime.fromisoformat(modified_time)
            if (modified_time := file.get("modifiedTime"))
            else None
        ),
        mime_type=file.get("mimeType") or None,
        size_bytes=drive_file_size(file),
        listing_payload=DriveListingPayload(
            retriever_email=retriever_email,
            drive_file=dict(file),
            # Built once here, so conversion workers do not each fetch the
            # parent folders.
            folder_path=build_folder_path(file, ops, retriever_email),
            # TODO(conversion stage): add the shared drive's members.
            reader_emails=_domain_readers(file, retriever_email),
        ),
    )
