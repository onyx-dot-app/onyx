from datetime import datetime
from datetime import timezone
from io import BytesIO

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
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.db.engine import get_session_with_current_tenant
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.file_validation import is_valid_image_type
from onyx.file_processing.image_summarization import summarize_image_with_error_handling
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger

logger = setup_logger()

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
    """
    Extract sections from a Google Drive file using the basic approach.
    For images, creates ImageSection objects instead of summarizing them.
    """
    mime_type = file.get("mimeType", "")
    file_id = file.get("id", "")
    file_name = file.get("name", "")
    link = file.get("webViewLink", "")

    # Handle images - store them but don't summarize
    if is_gdrive_image_mime_type(mime_type):
        try:
            # Download the image
            image_data = service.files().get_media(fileId=file_id).execute()

            # Store the image in PGFileStore
            with get_session_with_current_tenant() as db_session:
                section, stored_file_name = store_image_and_create_section(
                    db_session=db_session,
                    image_data=image_data,
                    file_name=f"gdrive_{file_id}",
                    display_name=file_name,
                    media_type=mime_type,
                    file_origin=FileOrigin.CONNECTOR,
                )
                return [section]
        except Exception as e:
            logger.error(f"Failed to process image '{file_name}': {e}")
            return [
                TextSection(link=link, text=f"[Failed to process image: {file_name}]")
            ]

    # Handle Google Docs, Sheets, Slides
    if mime_type in GOOGLE_MIME_TYPES:
        try:
            export_mime_type = GOOGLE_MIME_TYPES[mime_type]
            content = (
                service.files()
                .export(fileId=file_id, mimeType=export_mime_type)
                .execute()
            )
            if isinstance(content, bytes):
                text = content.decode("utf-8")
                return [TextSection(link=link, text=text)]
        except Exception as e:
            logger.error(f"Failed to export Google file '{file_name}': {e}")
            return [TextSection(link=link, text=UNSUPPORTED_FILE_TYPE_CONTENT)]

    # Handle other file types
    try:
        content = service.files().get_media(fileId=file_id).execute()
        if isinstance(content, bytes):
            # Try to extract text from the file
            try:
                text = extract_file_text(BytesIO(content), file_name)
                if text:
                    return [TextSection(link=link, text=text)]
            except Exception as text_extraction_error:
                logger.error(
                    f"Failed to extract text from '{file_name}': {text_extraction_error}"
                )
    except Exception as e:
        logger.error(f"Failed to download file '{file_name}': {e}")

    # Default fallback
    return [TextSection(link=link, text=UNSUPPORTED_FILE_TYPE_CONTENT)]


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
            sections = _extract_sections_basic(file, drive_service)

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
