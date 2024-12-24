import io
from datetime import datetime
from datetime import timezone

from googleapiclient.discovery import build  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore
from markitdown import MarkItDown  # type: ignore

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import IGNORE_FOR_QA
from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.constants import DRIVE_SHORTCUT_TYPE
from onyx.connectors.google_drive.constants import UNSUPPORTED_FILE_TYPE_CONTENT
from onyx.connectors.google_drive.models import GDriveMimeType
from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_drive.section_extraction import get_document_sections
from onyx.connectors.google_utils.resources import GoogleDocsService
from onyx.connectors.google_utils.resources import GoogleDriveService
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.connectors.models import SlimDocument
from onyx.file_processing.extract_file_text import docx_to_text
from onyx.file_processing.extract_file_text import pptx_to_text
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.unstructured import get_unstructured_api_key
from onyx.file_processing.unstructured import unstructured_to_text
from onyx.utils.logger import setup_logger


logger = setup_logger()

# these errors don't represent a failure in the connector, but simply files
# that can't / shouldn't be indexed
ERRORS_TO_CONTINUE_ON = [
    "cannotExportFile",
    "exportSizeLimitExceeded",
    "cannotDownloadFile",
]


def convert_drive_item_to_document(
    file: GoogleDriveFileType,
    drive_service: GoogleDriveService,
    docs_service: GoogleDocsService,
) -> Document | None:
    """
    Converts a Google Drive file into an internal Document object, extracting
    the text and organizing it into sections. Uses specialized methods for Google Docs
    to preserve structure. Falls back to basic extraction for all other formats.
    """
    try:
        # Skip shortcuts and folders
        if file.get("mimeType") == DRIVE_SHORTCUT_TYPE:
            logger.info("Ignoring Drive Shortcut Filetype")
            return None
        if file.get("mimeType") == DRIVE_FOLDER_TYPE:
            logger.info("Ignoring Drive Folder Filetype")
            return None

        sections: list[Section] = []

        # Special handling for Google Docs to preserve structure
        if file.get("mimeType") == GDriveMimeType.DOC.value:
            try:
                sections = get_document_sections(docs_service, file["id"])
            except Exception as e:
                logger.warning(
                    f"Exception '{e}' when pulling sections from Google Doc '{file['name']}'. "
                    "Falling back to basic extraction."
                )

        # If not a GDoc or GDoc extraction failed
        if not sections:
            try:
                sections = _extract_sections_basic(file, drive_service)
            except HttpError as e:
                reason = e.error_details[0]["reason"] if e.error_details else e.reason
                message = e.error_details[0]["message"] if e.error_details else e.reason
                if e.status_code == 403 and reason in ERRORS_TO_CONTINUE_ON:
                    logger.warning(
                        f"Could not export file '{file['name']}' due to '{message}', skipping..."
                    )
                    return None
                raise

        if not sections:
            return None

        return Document(
            id=file["webViewLink"],
            sections=sections,
            source=DocumentSource.GOOGLE_DRIVE,
            semantic_identifier=file["name"],
            doc_updated_at=datetime.fromisoformat(file["modifiedTime"]).astimezone(
                timezone.utc
            ),
            metadata={}
            if any(section.text for section in sections)
            else {IGNORE_FOR_QA: "True"},
            additional_info=file.get("id"),
        )
    except Exception as e:
        if not CONTINUE_ON_CONNECTOR_FAILURE:
            raise e
        logger.exception("Ran into exception when pulling a file from Google Drive")
        return None


def _extract_sections_basic(
    file: GoogleDriveFileType, service: GoogleDriveService
) -> list[Section]:
    """
    Extracts text from a Google Drive file based on its MIME type.
    """
    mime_type = file["mimeType"]
    link = file["webViewLink"]

    # Handle unsupported MIME types
    if mime_type not in {item.value for item in GDriveMimeType}:
        logger.debug(
            f"Unsupported MIME type '{mime_type}' for file '{file.get('name')}'"
        )
        return [Section(link=link, text=UNSUPPORTED_FILE_TYPE_CONTENT)]

    # Specialized handling for Google Sheets
    if mime_type == GDriveMimeType.SPREADSHEET.value:
        try:
            return _extract_google_sheets(file, service)
        except Exception as e:
            logger.warning(
                f"Error extracting data from Google Sheet '{file['name']}': {e}. "
                "Falling back to basic content extraction."
            )

    # For other types
    return _extract_general_content(file, service)


def _extract_google_sheets(
    file: dict[str, str], service: GoogleDriveService
) -> list[Section]:
    """
    Specialized extraction logic for Google Sheets.
    Iterates through each sheet, fetches all data, and returns a list of Section objects.
    """
    link = file["webViewLink"]
    file_id = file["id"]

    sheets_service = build("sheets", "v4", credentials=service._http.credentials)
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=file_id).execute()

    sections: list[Section] = []
    for sheet in spreadsheet.get("sheets", []):
        sheet_name = sheet["properties"]["title"]
        sheet_id = sheet["properties"]["sheetId"]

        grid_props = sheet["properties"].get("gridProperties", {})
        row_count = grid_props.get("rowCount", 1000)
        column_count = grid_props.get("columnCount", 26)

        # Convert a number to a spreadsheet column letter (1->A, 26->Z, 27->AA,...)
        end_column = ""
        col_count = column_count
        while col_count > 0:
            col_count, remainder = divmod(col_count - 1, 26)
            end_column = chr(65 + remainder) + end_column

        range_name = f"'{sheet_name}'!A1:{end_column}{row_count}"

        try:
            result = (
                sheets_service.spreadsheets()
                .values()
                .get(spreadsheetId=file_id, range=range_name)
                .execute()
            )
            values = result.get("values", [])

            if values:
                text = f"Sheet: {sheet_name}\n"
                for row in values:
                    text += "\t".join(str(cell) for cell in row) + "\n"

                sections.append(Section(link=f"{link}#gid={sheet_id}", text=text))
        except HttpError as e:
            logger.warning(
                f"Error fetching data for sheet '{sheet_name}' in '{file.get('name')}' : {e}"
            )
            continue

    return sections


def _extract_general_content(
    file: dict[str, str], service: GoogleDriveService
) -> list[Section]:
    """
    Extracts general file content for files other than Google Sheets.
    - PDF: Revert to read_pdf_file
    - DOCX: Unstructured, then docx_to_text, then MarkItDown.
    - PPTX: Unstructured, then pptx_to_text, then MarkItDown.
    - TXT: Decode the content; if empty, log.
    - Google Docs/Slides: Export as text/plain and return directly.
    """
    link = file["webViewLink"]
    mime_type = file["mimeType"]
    file_id = file["id"]
    file_name = file.get("name", file_id)

    try:
        # Google Docs and Google Slides (internal GDrive formats)
        if (
            mime_type == GDriveMimeType.DOC.value
            or mime_type == GDriveMimeType.PPT.value
        ):
            logger.debug(f"Extracting Google-native doc/presentation: {file_name}")
            export_mime_type = "text/plain"
            content = (
                service.files()
                .export(fileId=file_id, mimeType=export_mime_type)
                .execute()
            )
            text = content.decode("utf-8", errors="replace").strip()
            if not text:
                logger.warning(
                    f"No text extracted from Google Docs/Slides file '{file_name}'."
                )
                text = UNSUPPORTED_FILE_TYPE_CONTENT
            return [Section(link=link, text=text)]

        # For all other formats, get raw content
        content = service.files().get_media(fileId=file_id).execute()

        if mime_type == GDriveMimeType.PDF.value:
            # Revert to original PDF extraction
            logger.debug(f"Extracting PDF content for '{file_name}'")
            text, _ = read_pdf_file(file=io.BytesIO(content))
            if not text:
                logger.warning(
                    f"No text extracted from PDF '{file_name}' with read_pdf_file."
                )
                text = UNSUPPORTED_FILE_TYPE_CONTENT
            return [Section(link=link, text=text)]

        if mime_type == GDriveMimeType.WORD_DOC.value:
            logger.debug(f"Extracting DOCX content for '{file_name}'")
            return [
                Section(link=link, text=_extract_docx_pptx_txt(content, file, "docx"))
            ]

        if mime_type == GDriveMimeType.POWERPOINT.value:
            logger.debug(f"Extracting PPTX content for '{file_name}'")
            return [
                Section(link=link, text=_extract_docx_pptx_txt(content, file, "pptx"))
            ]

        if (
            mime_type == GDriveMimeType.PLAIN_TEXT.value
            or mime_type == GDriveMimeType.MARKDOWN.value
        ):
            logger.debug(f"Extracting plain text/markdown content for '{file_name}'")
            text = content.decode("utf-8", errors="replace").strip()
            if not text:
                logger.warning(
                    f"No text extracted from TXT/MD '{file_name}'. Returning unsupported message."
                )
                text = UNSUPPORTED_FILE_TYPE_CONTENT
            return [Section(link=link, text=text)]

        # If we reach here, it's some other format supported by MarkItDown/unstructured
        logger.debug(f"Trying MarkItDown/unstructured fallback for '{file_name}'")
        text = _extract_docx_pptx_txt(content, file, None)  # generic fallback
        return [Section(link=link, text=text)]

    except Exception as e:
        logger.error(
            f"Error extracting file content for '{file_name}': {e}", exc_info=True
        )
        return [Section(link=link, text=UNSUPPORTED_FILE_TYPE_CONTENT)]


def _extract_docx_pptx_txt(
    content: bytes, file: dict[str, str], file_type: str | None
) -> str:
    """
    Attempts to extract text from DOCX, PPTX, or any supported format using:
    1. unstructured (if configured)
    2. docx_to_text/pptx_to_text if known format
    3. MarkItDown fallback
    """
    file_name = file.get("name", file["id"])

    # 1. Try unstructured first
    if get_unstructured_api_key():
        try:
            logger.debug(f"Attempting unstructured extraction for '{file_name}'...")
            text = unstructured_to_text(io.BytesIO(content), file_name)
            if text.strip():
                return text
            else:
                logger.warning(f"Unstructured returned empty text for '{file_name}'.")
        except Exception as e:
            logger.warning(f"Unstructured extraction failed for '{file_name}': {e}")

    # 2. If format is docx or pptx, try direct extraction methods
    if file_type == "docx":
        try:
            logger.debug(f"Trying docx_to_text for '{file_name}'...")
            text = docx_to_text(file=io.BytesIO(content))
            if text.strip():
                return text
            else:
                logger.warning(f"docx_to_text returned empty for '{file_name}'.")
        except Exception as e:
            logger.warning(f"docx_to_text failed for '{file_name}': {e}")

    if file_type == "pptx":
        try:
            logger.debug(f"Trying pptx_to_text for '{file_name}'...")
            text = pptx_to_text(file=io.BytesIO(content))
            if text.strip():
                return text
            else:
                logger.warning(f"pptx_to_text returned empty for '{file_name}'.")
        except Exception as e:
            logger.warning(f"pptx_to_text failed for '{file_name}': {e}")

    # 3. Fallback to MarkItDown
    try:
        logger.debug(f"Falling back to MarkItDown for '{file_name}'...")
        md = MarkItDown()
        result = md.convert(io.BytesIO(content))
        if result and result.text_content and result.text_content.strip():
            return result.text_content
        else:
            logger.warning(f"MarkItDown returned empty text for '{file_name}'.")
    except Exception as e:
        logger.error(
            f"MarkItDown conversion failed for '{file_name}': {e}", exc_info=True
        )

    # If all methods fail or return empty, return unsupported message
    logger.error(
        f"All extraction methods failed for '{file_name}', returning unsupported file message."
    )
    return UNSUPPORTED_FILE_TYPE_CONTENT


def build_slim_document(file: GoogleDriveFileType) -> SlimDocument | None:
    # Skip files that are folders or shortcuts
    if file.get("mimeType") in [DRIVE_FOLDER_TYPE, DRIVE_SHORTCUT_TYPE]:
        return None

    return SlimDocument(
        id=file["webViewLink"],
        perm_sync_data={
            "doc_id": file.get("id"),
            "permissions": file.get("permissions", []),
            "permission_ids": file.get("permissionIds", []),
            "name": file.get("name"),
            "owner_email": file.get("owners", [{}])[0].get("emailAddress"),
        },
    )
