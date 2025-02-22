import io
import os
from datetime import datetime
from datetime import timezone
from typing import Optional

from googleapiclient.discovery import build  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.configs.constants import DocumentSource
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
from onyx.file_processing.extract_file_text import docx_to_text_and_images
from onyx.file_processing.extract_file_text import pptx_to_text
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.image_summarization import summarize_image_pipeline
from onyx.file_processing.unstructured import get_unstructured_api_key
from onyx.file_processing.unstructured import unstructured_to_text
from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger

logger = setup_logger()

# ---------- NEW ENVIRONMENTS / GLOBALS -----------
# The connector can pass an LLM here
_DRIVE_LLM_FOR_IMAGE_SUMMARIZATION: Optional[LLM] = None

# If you want a separate toggle, you can re-fcheck:
GDRIVE_IMAGE_SUMMARIZATION_ENABLED = (
    os.environ.get("GDRIVE_IMAGE_SUMMARIZATION_ENABLED", "").lower() == "true"
)

# Customize prompts as you see fit:
GDRIVE_IMAGE_SUMM_SYSTEM_PROMPT = """
You are an assistant for summarizing images from Google Drive.
Write a concise summary describing what each image depicts.
"""
GDRIVE_IMAGE_SUMM_USER_PROMPT = """
The image is named '{image_name}'. Summarize it in detail.
"""


def set_drive_llm_for_image_summarization(llm: LLM | None) -> None:
    """
    Called by the connector after credentials are loaded.
    This way, the doc_conversion can access the same LLM for summarizing images.
    """
    global _DRIVE_LLM_FOR_IMAGE_SUMMARIZATION
    _DRIVE_LLM_FOR_IMAGE_SUMMARIZATION = llm


def _summarize_drive_image(image_data: bytes, image_name: str) -> str:
    """
    Summarize the given image using our global LLM (if available).
    """
    if not GDRIVE_IMAGE_SUMMARIZATION_ENABLED or not _DRIVE_LLM_FOR_IMAGE_SUMMARIZATION:
        return ""

    try:
        user_prompt = GDRIVE_IMAGE_SUMM_USER_PROMPT.format(image_name=image_name)
        return (
            summarize_image_pipeline(
                llm=_DRIVE_LLM_FOR_IMAGE_SUMMARIZATION,
                image_data=image_data,
                query=user_prompt,
                system_prompt=GDRIVE_IMAGE_SUMM_SYSTEM_PROMPT,
            )
            or ""
        )
    except Exception as e:
        if CONTINUE_ON_CONNECTOR_FAILURE:
            logger.warning(f"Image summarization failed for {image_name}: {e}")
            return ""
        raise


def is_gdrive_image_mime_type(mime_type: str) -> bool:
    """
    Return True if the mime_type is a common image type in GDrive.
    (e.g. 'image/png', 'image/jpeg')
    """
    return mime_type.startswith("image/")


def _extract_sections_basic(
    file: dict[str, str],
    service: GoogleDriveService,
    llm: LLM | None = None,  # not mandatory, we can keep it for reference
) -> list[Section]:
    """
    Extends the existing logic to handle either a docx with embedded images
    or standalone images (PNG, JPG, etc).
    """
    mime_type = file["mimeType"]
    link = file["webViewLink"]
    file_name = file.get("name", file["id"])

    # 1) If the file is an image, retrieve the raw bytes, optionally summarize
    if is_gdrive_image_mime_type(mime_type):
        try:
            response = service.files().get_media(fileId=file["id"]).execute()
            summary_text = _summarize_drive_image(response, file_name)
            return [
                Section(
                    text=summary_text,
                    image_url=link,  # or some internal placeholder
                )
            ]
        except Exception as e:
            logger.warning(f"Failed to fetch or summarize image: {e}")
            return [
                Section(
                    link=link,
                    text="",
                    image_url=link,
                )
            ]

    # 2) If the file is a spreadsheet, doc, PDF, etc., do as before
    #    but if docx => parse embedded images
    if mime_type not in set(item.value for item in GDriveMimeType):
        return [Section(link=link, text=UNSUPPORTED_FILE_TYPE_CONTENT)]

    try:
        if mime_type == GDriveMimeType.SPREADSHEET.value:
            # the existing spreadsheet logic
            sheets_service = build(
                "sheets", "v4", credentials=service._http.credentials
            )
            spreadsheet = (
                sheets_service.spreadsheets().get(spreadsheetId=file["id"]).execute()
            )

            sections = []
            for sheet in spreadsheet["sheets"]:
                sheet_name = sheet["properties"]["title"]
                sheet_id = sheet["properties"]["sheetId"]
                grid_props = sheet["properties"].get("gridProperties", {})
                row_count = grid_props.get("rowCount", 1000)
                column_count = grid_props.get("columnCount", 26)

                # Convert columns => letter. minimal example:
                end_col = ""
                col_temp = column_count
                while col_temp > 0:
                    col_temp, remainder = divmod(col_temp - 1, 26)
                    end_col = chr(65 + remainder) + end_col

                range_name = f"'{sheet_name}'!A1:{end_col}{row_count}"
                try:
                    result = (
                        sheets_service.spreadsheets()
                        .values()
                        .get(spreadsheetId=file["id"], range=range_name)
                        .execute()
                    )
                    values = result.get("values", [])
                    if values:
                        txt = f"Sheet: {sheet_name}\n"
                        for row in values:
                            txt += "\t".join(str(cell) for cell in row) + "\n"
                        sections.append(
                            Section(link=f"{link}#gid={sheet_id}", text=txt)
                        )
                except HttpError as e:
                    logger.warning(f"Error retrieving data for {sheet_name}: {e}")
            return sections

        elif mime_type in [
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

        elif mime_type in [
            GDriveMimeType.PLAIN_TEXT.value,
            GDriveMimeType.MARKDOWN.value,
        ]:
            text_data = (
                service.files().get_media(fileId=file["id"]).execute().decode("utf-8")
            )
            return [Section(link=link, text=text_data)]

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
                    embed_images=True,  # we do want embedded images
                )
                sections = []
                if text.strip():
                    sections.append(Section(link=link, text=text.strip()))

                # Summarize each embedded image if enabled
                for idx, (img_data, img_name) in enumerate(embedded_images, start=1):
                    summary = _summarize_drive_image(img_data, img_name)
                    # We'll store the same link or some placeholder
                    # There's no direct Google link for each embedded sub-image
                    # so we put a generic image_url referencing doc
                    embedded_link = f"{link}#embedded_image_{idx}"
                    sections.append(Section(text=summary, image_url=embedded_link))
                return sections

            elif mime_type == GDriveMimeType.PDF.value:
                text, _pdf_meta, images = read_pdf_file(io.BytesIO(response_bytes))
                return [Section(link=link, text=text)]

            elif mime_type == GDriveMimeType.POWERPOINT.value:
                text_data = pptx_to_text(io.BytesIO(response_bytes))
                return [Section(link=link, text=text_data)]

        return [Section(link=link, text=UNSUPPORTED_FILE_TYPE_CONTENT)]

    except Exception:
        logger.exception("Error extracting sections from file.")
        return [Section(link=link, text=UNSUPPORTED_FILE_TYPE_CONTENT)]


def convert_drive_item_to_document(
    file: GoogleDriveFileType,
    drive_service: GoogleDriveService,
    docs_service: GoogleDocsService,
    llm: LLM | None = None,
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
            sections = _extract_sections_basic(file, drive_service, llm)

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
