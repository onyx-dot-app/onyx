import io
from datetime import datetime
from typing import cast

from googleapiclient.http import MediaIoBaseDownload  # type: ignore

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.constants import DRIVE_SHORTCUT_TYPE
from onyx.connectors.google_drive.models import GDriveMimeType
from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_drive.section_extraction import get_document_sections
from onyx.connectors.google_utils.resources import GoogleDocsService
from onyx.connectors.google_utils.resources import GoogleDriveService
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.db.engine import get_session_with_current_tenant
from onyx.file_processing.extract_file_text import docx_to_text_and_images
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.extract_file_text import pptx_to_text
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.extract_file_text import xlsx_to_text
from onyx.file_processing.file_validation import is_valid_image_type
from onyx.file_processing.image_summarization import summarize_image_with_error_handling
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger

logger = setup_logger()

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
) -> list[TextSection | ImageSection]:
    """Extract text and images from a Google Drive file."""
    file_id = file["id"]
    file_name = file["name"]
    mime_type = file["mimeType"]
    link = file.get("webViewLink", "")

    try:
        # For Google Docs, Sheets, and Slides, export as plain text
        if mime_type in GOOGLE_MIME_TYPES_TO_EXPORT:
            export_mime_type = GOOGLE_MIME_TYPES_TO_EXPORT[mime_type]
            # Use the correct API call for exporting files
            request = service.files().export_media(
                fileId=file_id, mimeType=export_mime_type
            )
            response_bytes = io.BytesIO()
            downloader = MediaIoBaseDownload(response_bytes, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            response = response_bytes.getvalue()
            if not response:
                logger.warning(f"Failed to export {file_name} as {export_mime_type}")
                return []

            text = response.decode("utf-8")
            return [TextSection(link=link, text=text)]

        # For other file types, download the file
        # Use the correct API call for downloading files
        request = service.files().get_media(fileId=file_id)
        response_bytes = io.BytesIO()
        downloader = MediaIoBaseDownload(response_bytes, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        response = response_bytes.getvalue()
        if not response:
            logger.warning(f"Failed to download {file_name}")
            return []

        # Process based on mime type
        if mime_type == "text/plain":
            text = response.decode("utf-8")
            return [TextSection(link=link, text=text)]

        elif (
            mime_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            text, _ = docx_to_text_and_images(io.BytesIO(response))
            return [TextSection(link=link, text=text)]

        elif (
            mime_type
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ):
            text = xlsx_to_text(io.BytesIO(response))
            return [TextSection(link=link, text=text)]

        elif (
            mime_type
            == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ):
            text = pptx_to_text(io.BytesIO(response))
            return [TextSection(link=link, text=text)]

        elif is_gdrive_image_mime_type(mime_type):
            # For images, store them for later processing
            sections: list[TextSection | ImageSection] = []
            try:
                with get_session_with_current_tenant() as db_session:
                    section, embedded_id = store_image_and_create_section(
                        db_session=db_session,
                        image_data=response,
                        file_name=file_id,
                        display_name=file_name,
                        media_type=mime_type,
                        file_origin=FileOrigin.CONNECTOR,
                        link=link,
                    )
                    sections.append(section)
            except Exception as e:
                logger.error(f"Failed to process image {file_name}: {e}")
            return sections

        elif mime_type == "application/pdf":
            text, _pdf_meta, images = read_pdf_file(io.BytesIO(response))
            pdf_sections: list[TextSection | ImageSection] = [
                TextSection(link=link, text=text)
            ]

            # Process embedded images in the PDF
            try:
                with get_session_with_current_tenant() as db_session:
                    for idx, (img_data, img_name) in enumerate(images):
                        section, embedded_id = store_image_and_create_section(
                            db_session=db_session,
                            image_data=img_data,
                            file_name=f"{file_id}_img_{idx}",
                            display_name=img_name or f"{file_name} - image {idx}",
                            file_origin=FileOrigin.CONNECTOR,
                        )
                        pdf_sections.append(section)
            except Exception as e:
                logger.error(f"Failed to process PDF images in {file_name}: {e}")
            return pdf_sections

        else:
            # For unsupported file types, try to extract text
            try:
                text = extract_file_text(io.BytesIO(response), file_name)
                return [TextSection(link=link, text=text)]
            except Exception as e:
                logger.warning(f"Failed to extract text from {file_name}: {e}")
                return []

    except Exception as e:
        logger.error(f"Error processing file {file_name}: {e}")
        return []


def convert_drive_item_to_document(
    file: GoogleDriveFileType,
    drive_service: GoogleDriveService,
    docs_service: GoogleDocsService,
) -> Document | None:
    """
    Main entry point for converting a Google Drive file => Document object.
    """
    try:
        # skip shortcuts or folders
        if file.get("mimeType") in [DRIVE_SHORTCUT_TYPE, DRIVE_FOLDER_TYPE]:
            logger.info("Skipping shortcut/folder.")
            return None

        # If it's a Google Doc, we might do advanced parsing
        sections: list[TextSection | ImageSection] = []

        # Try to get sections using the advanced method first
        if file.get("mimeType") == GDriveMimeType.DOC.value:
            try:
                doc_sections = get_document_sections(
                    docs_service=docs_service, doc_id=file.get("id", "")
                )
                if doc_sections:
                    sections = cast(list[TextSection | ImageSection], doc_sections)
            except Exception as e:
                logger.warning(
                    f"Error in advanced parsing: {e}. Falling back to basic extraction."
                )

        # If we don't have sections yet, use the basic extraction method
        if not sections:
            sections = _extract_sections_basic(file, drive_service)

        # If we still don't have any sections, skip this file
        if not sections:
            logger.warning(f"No content extracted from {file.get('name')}. Skipping.")
            return None

        doc_id = file["webViewLink"]

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
        )
    except Exception as e:
        logger.error(f"Error converting file {file.get('name')}: {e}")
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
