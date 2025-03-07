import io
from datetime import datetime
from datetime import timezone
from tempfile import NamedTemporaryFile

import openpyxl  # type: ignore
from googleapiclient.discovery import build  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
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
from onyx.db.engine import get_session_with_current_tenant
from onyx.file_processing.extract_file_text import docx_to_text_and_images
from onyx.file_processing.extract_file_text import pptx_to_text
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.file_validation import is_valid_image_type
from onyx.file_processing.image_summarization import summarize_image_with_error_handling
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.file_processing.unstructured import get_unstructured_api_key
from onyx.file_processing.unstructured import unstructured_to_text
from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _summarize_drive_image(
    image_data: bytes, image_name: str, image_analysis_llm: LLM | None
) -> str:
    """
    Summarize the given image using the provided LLM.
    """
    if not image_analysis_llm:
        return ""

    return (
        summarize_image_with_error_handling(
            llm=image_analysis_llm,
            image_data=image_data,
            context_name=image_name,
        )
        or ""
    )


def is_gdrive_image_mime_type(mime_type: str) -> bool:
    """
    Return True if the mime_type is a common image type in GDrive.
    (e.g. 'image/png', 'image/jpeg')
    """
    return is_valid_image_type(mime_type)


def _extract_sections_basic(
    file: dict[str, str],
    service: GoogleDriveService,
    image_analysis_llm: LLM | None = None,
) -> list[Section]:
    """
    Extends the existing logic to handle either a docx with embedded images
    or standalone images (PNG, JPG, etc).
    """
    mime_type = file["mimeType"]
    link = file["webViewLink"]
    file_name = file.get("name", file["id"])
    supported_file_types = set(item.value for item in GDriveMimeType)

    # 1) If the file is an image, retrieve the raw bytes, optionally summarize
    if is_gdrive_image_mime_type(mime_type):
        try:
            response = service.files().get_media(fileId=file["id"]).execute()

            with get_session_with_current_tenant() as db_session:
                section, _ = store_image_and_create_section(
                    db_session=db_session,
                    image_data=response,
                    file_name=file["id"],
                    display_name=file_name,
                    media_type=mime_type,
                    llm=image_analysis_llm,
                    file_origin=FileOrigin.CONNECTOR,
                )
                return [section]
        except Exception as e:
            logger.warning(f"Failed to fetch or summarize image: {e}")
            return [
                Section(
                    link=link,
                    text="",
                    image_file_name=link,
                )
            ]

    if mime_type not in supported_file_types:
        # Unsupported file types can still have a title, finding this way is still useful
        return [Section(link=link, text=UNSUPPORTED_FILE_TYPE_CONTENT)]

    try:
        # ---------------------------
        # Google Sheets extraction
        if mime_type == GDriveMimeType.SPREADSHEET.value:
            try:
                sheets_service = build(
                    "sheets", "v4", credentials=service._http.credentials
                )
                spreadsheet = (
                    sheets_service.spreadsheets()
                    .get(spreadsheetId=file["id"])
                    .execute()
                )

                sections = []
                for sheet in spreadsheet["sheets"]:
                    sheet_name = sheet["properties"]["title"]
                    sheet_id = sheet["properties"]["sheetId"]

                    # Get sheet dimensions
                    grid_properties = sheet["properties"].get("gridProperties", {})
                    row_count = grid_properties.get("rowCount", 1000)
                    column_count = grid_properties.get("columnCount", 26)

                    # Convert column count to letter (e.g., 26 -> Z, 27 -> AA)
                    end_column = ""
                    while column_count:
                        column_count, remainder = divmod(column_count - 1, 26)
                        end_column = chr(65 + remainder) + end_column

                    range_name = f"'{sheet_name}'!A1:{end_column}{row_count}"

                    try:
                        result = (
                            sheets_service.spreadsheets()
                            .values()
                            .get(spreadsheetId=file["id"], range=range_name)
                            .execute()
                        )
                        values = result.get("values", [])

                        if values:
                            text = f"Sheet: {sheet_name}\n"
                            for row in values:
                                text += "\t".join(str(cell) for cell in row) + "\n"
                            sections.append(
                                Section(
                                    link=f"{link}#gid={sheet_id}",
                                    text=text,
                                )
                            )
                    except HttpError as e:
                        logger.warning(
                            f"Error fetching data for sheet '{sheet_name}': {e}"
                        )
                        continue
                return sections

            except Exception as e:
                logger.warning(
                    f"Ran into exception '{e}' when pulling data from Google Sheet '{file['name']}'."
                    " Falling back to basic extraction."
                )
        # ---------------------------
        # Microsoft Excel (.xlsx or .xls) extraction branch
        elif mime_type in [
            GDriveMimeType.SPREADSHEET_OPEN_FORMAT.value,
            GDriveMimeType.SPREADSHEET_MS_EXCEL.value,
        ]:
            try:
                response = service.files().get_media(fileId=file["id"]).execute()

                with NamedTemporaryFile(suffix=".xlsx", delete=True) as tmp:
                    tmp.write(response)
                    tmp_path = tmp.name

                    section_separator = "\n\n"
                    workbook = openpyxl.load_workbook(tmp_path, read_only=True)

                    # Work similarly to the xlsx_to_text function used for file connector
                    # but returns Sections instead of a string
                    sections = [
                        Section(
                            link=link,
                            text=(
                                f"Sheet: {sheet.title}\n\n"
                                + section_separator.join(
                                    ",".join(map(str, row))
                                    for row in sheet.iter_rows(
                                        min_row=1, values_only=True
                                    )
                                    if row
                                )
                            ),
                        )
                        for sheet in workbook.worksheets
                    ]

                return sections

            except Exception as e:
                logger.warning(
                    f"Error extracting data from Excel file '{file['name']}': {e}"
                )
                return [
                    Section(link=link, text="Error extracting data from Excel file")
                ]

        # ---------------------------
        # Export for Google Docs, PPT, and fallback for spreadsheets
        if mime_type in [
            GDriveMimeType.DOC.value,
            GDriveMimeType.PPT.value,
            GDriveMimeType.SPREADSHEET.value,
        ]:
            export_mime_type = (
                "text/plain"
                if mime_type != GDriveMimeType.SPREADSHEET.value
                else "text/csv"
            )
            text = (
                service.files()
                .export(fileId=file["id"], mimeType=export_mime_type)
                .execute()
                .decode("utf-8")
            )
            return [Section(link=link, text=text)]

        # ---------------------------
        # Plain text and Markdown files
        elif mime_type in [
            GDriveMimeType.PLAIN_TEXT.value,
            GDriveMimeType.MARKDOWN.value,
        ]:
            text_data = (
                service.files().get_media(fileId=file["id"]).execute().decode("utf-8")
            )
            return [Section(link=link, text=text_data)]

        # ---------------------------
        # Word, PowerPoint, PDF files
        elif mime_type in [
            GDriveMimeType.WORD_DOC.value,
            GDriveMimeType.POWERPOINT.value,
            GDriveMimeType.PDF.value,
        ]:
            response_bytes = service.files().get_media(fileId=file["id"]).execute()

            # Optionally use Unstructured
            if get_unstructured_api_key():
                text = unstructured_to_text(
                    file=io.BytesIO(response_bytes),
                    file_name=file_name,
                )
                return [Section(link=link, text=text)]

            if mime_type == GDriveMimeType.WORD_DOC.value:
                # Use docx_to_text_and_images to get text plus embedded images
                text, embedded_images = docx_to_text_and_images(
                    file=io.BytesIO(response_bytes),
                )
                sections = []
                if text.strip():
                    sections.append(Section(link=link, text=text.strip()))

                # Process each embedded image using the standardized function
                with get_session_with_current_tenant() as db_session:
                    for idx, (img_data, img_name) in enumerate(
                        embedded_images, start=1
                    ):
                        # Create a unique identifier for the embedded image
                        embedded_id = f"{file['id']}_embedded_{idx}"

                        section, _ = store_image_and_create_section(
                            db_session=db_session,
                            image_data=img_data,
                            file_name=embedded_id,
                            display_name=img_name or f"{file_name} - image {idx}",
                            llm=image_analysis_llm,
                            file_origin=FileOrigin.CONNECTOR,
                        )
                        sections.append(section)
                return sections

            elif mime_type == GDriveMimeType.PDF.value:
                text, _pdf_meta, images = read_pdf_file(io.BytesIO(response_bytes))
                return [Section(link=link, text=text)]

            elif mime_type == GDriveMimeType.POWERPOINT.value:
                text_data = pptx_to_text(io.BytesIO(response_bytes))
                return [Section(link=link, text=text_data)]

        # Catch-all case, should not happen since there should be specific handling
        # for each of the supported file types
        error_message = f"Unsupported file type: {mime_type}"
        logger.error(error_message)
        raise ValueError(error_message)

    except Exception as e:
        logger.exception(f"Error extracting sections from file: {e}")
        return [Section(link=link, text=UNSUPPORTED_FILE_TYPE_CONTENT)]


def convert_drive_item_to_document(
    file: GoogleDriveFileType,
    drive_service: GoogleDriveService,
    docs_service: GoogleDocsService,
    image_analysis_llm: LLM | None,
) -> Document | None:
    """
    Main entry point for converting a Google Drive file => Document object.
    Now we accept an optional `llm` to pass to `_extract_sections_basic`.
    """
    try:
        # skip shortcuts or folders
        if file.get("mimeType") in [DRIVE_SHORTCUT_TYPE, DRIVE_FOLDER_TYPE]:
            logger.info("Skipping shortcut/folder.")
            return None

        # If it's a Google Doc, we might do advanced parsing
        sections: list[Section] = []
        if file.get("mimeType") == GDriveMimeType.DOC.value:
            try:
                # get_document_sections is the advanced approach for Google Docs
                sections = get_document_sections(docs_service, file["id"])
            except Exception as e:
                logger.warning(
                    f"Failed to pull google doc sections from '{file['name']}': {e}. "
                    "Falling back to basic extraction."
                )

        # If not a doc, or if we failed above, do our 'basic' approach
        if not sections:
            sections = _extract_sections_basic(file, drive_service, image_analysis_llm)

        if not sections:
            return None

        doc_id = file["webViewLink"]
        updated_time = datetime.fromisoformat(file["modifiedTime"]).astimezone(
            timezone.utc
        )

        return Document(
            id=doc_id,
            sections=sections,
            source=DocumentSource.GOOGLE_DRIVE,
            semantic_identifier=file["name"],
            doc_updated_at=updated_time,
            metadata={},  # or any metadata from 'file'
            additional_info=file.get("id"),
        )

    except Exception as e:
        logger.exception(f"Error converting file '{file.get('name')}' to Document: {e}")
        if not CONTINUE_ON_CONNECTOR_FAILURE:
            raise
    return None


def build_slim_document(file: GoogleDriveFileType) -> SlimDocument | None:
    if file.get("mimeType") in [DRIVE_FOLDER_TYPE, DRIVE_SHORTCUT_TYPE]:
        return None
    return SlimDocument(
        id=file["webViewLink"],
        perm_sync_data={
            "doc_id": file.get("id"),
            "drive_id": file.get("driveId"),
            "permissions": file.get("permissions", []),
            "permission_ids": file.get("permissionIds", []),
            "name": file.get("name"),
            "owner_email": file.get("owners", [{}])[0].get("emailAddress"),
        },
    )
