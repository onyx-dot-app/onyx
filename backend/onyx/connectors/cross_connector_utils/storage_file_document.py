import mimetypes
from datetime import datetime
from io import BytesIO

from onyx.configs.app_configs import SKIP_SPREADSHEET_CONTENT
from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    process_onyx_metadata,
)
from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    extract_and_stage_tabular_file,
    is_tabular_file,
)
from onyx.connectors.models import Document, ImageSection, TabularSection, TextSection
from onyx.file_processing.extract_file_text import extract_text_and_images, get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_processing.image_utils import (
    make_image_callback,
    store_image_and_create_section,
)
from onyx.file_store.staging import RawFileCallback
from onyx.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_CONTENT_TYPE = "application/octet-stream"


def build_storage_file_document(
    *,
    file_bytes: bytes,
    file_name: str,
    document_id: str,
    source: DocumentSource,
    link: str,
    last_modified: datetime,
    image_file_id: str,
    raw_file_callback: RawFileCallback | None,
    include_embedded_images: bool,
) -> Document | None:
    """Converts a downloaded storage object into a ``Document``.

    Image files become one image section, tabular files become tabular
    sections, and every other file goes through text extraction. With
    ``include_embedded_images``, images inside a document are stored as image
    sections under ``image_file_id``. Returns None
    when the file yields nothing to index. Raises on extraction and file-store
    errors, so the caller decides how a failed file is reported.
    """
    if get_file_ext(file_name) in OnyxFileExtensions.IMAGE_EXTENSIONS:
        # TODO(evan-onyx): Refactor to avoid direct DB access in connector
        # This will require broader refactoring across the codebase
        image_section, _ = store_image_and_create_section(
            image_data=file_bytes,
            file_id=image_file_id,
            display_name=file_name,
            link=link,
            file_origin=FileOrigin.CONNECTOR,
        )
        return Document(
            id=document_id,
            sections=[image_section],
            source=source,
            semantic_identifier=file_name,
            doc_updated_at=last_modified,
            metadata={},
        )

    if is_tabular_file(file_name):
        if raw_file_callback is None:
            logger.warning(
                "Skipping tabular file %s because raw_file_callback is not set",
                file_name,
            )
            return None
        content_type, _ = mimetypes.guess_type(file_name)
        result = extract_and_stage_tabular_file(
            file=BytesIO(file_bytes),
            file_name=file_name,
            content_type=content_type or DEFAULT_CONTENT_TYPE,
            raw_file_callback=raw_file_callback,
            link=link,
            skip_content=SKIP_SPREADSHEET_CONTENT,
        )
        if not result.sections:
            logger.warning("No content extracted from tabular file %s", file_name)
            return None
        return Document(
            id=document_id,
            sections=result.sections,
            source=source,
            semantic_identifier=file_name,
            doc_updated_at=last_modified,
            metadata={},
            file_id=result.staged_file_id,
        )

    sections: list[TextSection | ImageSection | TabularSection] = []
    extraction_result = extract_text_and_images(
        BytesIO(file_bytes),
        file_name=file_name,
        image_callback=(
            make_image_callback(sections, image_file_id, file_name, link)
            if include_embedded_images
            else None
        ),
    )
    onyx_metadata, custom_tags = process_onyx_metadata(extraction_result.metadata)
    if onyx_metadata.link:
        # Embedded images were stored before the metadata named the link.
        link = onyx_metadata.link
        sections = [section.model_copy(update={"link": link}) for section in sections]
    if text := extraction_result.text_content.strip():
        sections.append(TextSection(link=link, text=text))
    return Document(
        id=document_id,
        sections=sections or [TextSection(link=link, text="")],
        source=onyx_metadata.source_type or source,
        semantic_identifier=onyx_metadata.file_display_name or file_name,
        doc_updated_at=onyx_metadata.doc_updated_at or last_modified,
        metadata=custom_tags,
        primary_owners=onyx_metadata.primary_owners,
        secondary_owners=onyx_metadata.secondary_owners,
    )
