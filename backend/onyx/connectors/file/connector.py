import os
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import IO

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    process_onyx_metadata,
)
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.extract_file_text import is_accepted_file_ext
from onyx.file_processing.extract_file_text import OnyxExtensionType
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger


logger = setup_logger()


def _create_image_section(
    image_data: bytes,
    parent_file_name: str,
    display_name: str,
    media_type: str | None = None,
    link: str | None = None,
    idx: int = 0,
) -> tuple[ImageSection, str | None]:
    """
    Creates an ImageSection for an image file or embedded image.
    Stores the image in FileStore but does not generate a summary.

    Args:
        image_data: Raw image bytes
        db_session: Database session
        parent_file_name: Name of the parent file (for embedded images)
        display_name: Display name for the image
        idx: Index for embedded images

    Returns:
        Tuple of (ImageSection, stored_file_name or None)
    """
    # Create a unique identifier for the image
    file_id = f"{parent_file_name}_embedded_{idx}" if idx > 0 else parent_file_name

    # Store the image and create a section
    try:
        section, stored_file_name = store_image_and_create_section(
            image_data=image_data,
            file_id=file_id,
            display_name=display_name,
            media_type=(
                media_type if media_type is not None else "application/octet-stream"
            ),
            link=link,
            file_origin=FileOrigin.CONNECTOR,
        )
        return section, stored_file_name
    except Exception as e:
        logger.error(f"Failed to store image {display_name}: {e}")
        raise e


def _process_file(
    file_id: str,
    file_name: str,
    file: IO[Any],
    metadata: dict[str, Any] | None,
    pdf_pass: str | None,
    file_type: str | None,
) -> list[Document]:
    """
    Process a file and return a list of Documents.
    For images, creates ImageSection objects without summarization.
    For documents with embedded images, extracts and stores the images.
    """
    if metadata is None:
        metadata = {}

    # Get file extension and determine file type
    extension = get_file_ext(file_name)

    if not is_accepted_file_ext(extension, OnyxExtensionType.All):
        logger.warning(
            f"Skipping file '{file_name}' with unrecognized extension '{extension}'"
        )
        return []

    # If a zip is uploaded with a metadata file, we can process it here
    onyx_metadata, custom_tags = process_onyx_metadata(metadata)
    file_display_name = onyx_metadata.file_display_name or os.path.basename(file_name)
    time_updated = onyx_metadata.doc_updated_at or datetime.now(timezone.utc)
    primary_owners = onyx_metadata.primary_owners
    secondary_owners = onyx_metadata.secondary_owners
    link = onyx_metadata.link

    # These metadata items are not settable by the user
    source_type_str = metadata.get("connector_type")
    source_type = (
        DocumentSource(source_type_str) if source_type_str else DocumentSource.FILE
    )

    doc_id = f"FILE_CONNECTOR__{file_id}"
    title = metadata.get("title") or file_display_name

    # 1) If the file itself is an image, handle that scenario quickly
    if extension in LoadConnector.IMAGE_EXTENSIONS:
        # Read the image data
        image_data = file.read()
        if not image_data:
            logger.warning(f"Empty image file: {file_name}")
            return []

        # Create an ImageSection for the image
        try:
            section, _ = _create_image_section(
                image_data=image_data,
                parent_file_name=file_id,
                display_name=title,
                media_type=file_type,
            )

            return [
                Document(
                    id=doc_id,
                    sections=[section],
                    source=source_type,
                    semantic_identifier=file_display_name,
                    title=title,
                    doc_updated_at=time_updated,
                    primary_owners=primary_owners,
                    secondary_owners=secondary_owners,
                    metadata=custom_tags,
                )
            ]
        except Exception as e:
            logger.error(f"Failed to process image file {file_name}: {e}")
            return []

    # 2) Otherwise: text-based approach. Possibly with embedded images.
    file.seek(0)

    # Extract text and images from the file
    extraction_result = extract_text_and_images(
        file=file,
        file_name=file_name,
        pdf_pass=pdf_pass,
        content_type=file_type,
    )

    # Each file may have file-specific ONYX_METADATA https://docs.onyx.app/admin/connectors/official/file
    # If so, we should add it to any metadata processed so far
    if extraction_result.metadata:
        logger.debug(
            f"Found file-specific metadata for {file_name}: {extraction_result.metadata}"
        )
        onyx_metadata, more_custom_tags = process_onyx_metadata(
            extraction_result.metadata
        )

        # Add file-specific tags
        custom_tags.update(more_custom_tags)

        # File-specific metadata overrides metadata processed so far
        source_type = onyx_metadata.source_type or source_type
        primary_owners = onyx_metadata.primary_owners or primary_owners
        secondary_owners = onyx_metadata.secondary_owners or secondary_owners
        time_updated = onyx_metadata.doc_updated_at or time_updated
        file_display_name = onyx_metadata.file_display_name or file_display_name
        title = onyx_metadata.title or onyx_metadata.file_display_name or title
        link = onyx_metadata.link or link

    # Build sections: first the text as a single Section
    sections: list[TextSection | ImageSection] = []
    if extraction_result.text_content.strip():
        logger.debug(f"Creating TextSection for {file_name} with link: {link}")
        sections.append(
            TextSection(link=link, text=extraction_result.text_content.strip())
        )

    # Then any extracted images from docx, PDFs, etc.
    for idx, (img_data, img_name) in enumerate(
        extraction_result.embedded_images, start=1
    ):
        # Store each embedded image as a separate file in FileStore
        # and create a section with the image reference
        try:
            image_section, stored_file_name = _create_image_section(
                image_data=img_data,
                parent_file_name=file_id,
                display_name=f"{title} - image {idx}",
                media_type="application/octet-stream",  # Default media type for embedded images
                idx=idx,
            )
            sections.append(image_section)
            logger.debug(
                f"Created ImageSection for embedded image {idx} "
                f"in {file_name}, stored as: {stored_file_name}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to process embedded image {idx} in {file_name}: {e}"
            )

    return [
        Document(
            id=doc_id,
            sections=sections,
            source=source_type,
            semantic_identifier=file_display_name,
            title=title,
            doc_updated_at=time_updated,
            primary_owners=primary_owners,
            secondary_owners=secondary_owners,
            metadata=custom_tags,
        )
    ]


class LocalFileConnector(LoadConnector):
    """
    Connector that reads files from Postgres and yields Documents, including
    embedded image extraction without summarization.

    file_locations are S3/Filestore UUIDs
    file_names are the names of the files
    """

    # Note: file_names is a required parameter, but should not break backwards compatibility.
    # If add_file_names migration is not run, old file connector configs will not have file_names.
    # file_names is only used for display purposes in the UI and file_locations is used as a fallback.
    def __init__(
        self,
        file_locations: list[Path | str],
        file_names: list[str] | None = None,
        zip_metadata: dict[str, Any] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.file_locations = [str(loc) for loc in file_locations]
        self.batch_size = batch_size
        self.pdf_pass: str | None = None
        self.zip_metadata = zip_metadata or {}

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.pdf_pass = credentials.get("pdf_password")

        return None

    def _get_file_metadata(self, file_name: str) -> dict[str, Any]:
        return self.zip_metadata.get(file_name, {}) or self.zip_metadata.get(
            os.path.basename(file_name), {}
        )

    def load_from_state(self) -> GenerateDocumentsOutput:
        """
        Iterates over each file path, fetches from Postgres, tries to parse text
        or images, and yields Document batches.
        """
        documents: list[Document] = []

        for file_id in self.file_locations:
            file_store = get_default_file_store()
            file_record = file_store.read_file_record(file_id=file_id)
            if not file_record:
                # typically an unsupported extension
                logger.warning(f"No file record found for '{file_id}' in PG; skipping.")
                continue

            metadata = self._get_file_metadata(file_record.display_name)
            file_io = file_store.read_file(file_id=file_id, mode="b")
            new_docs = _process_file(
                file_id=file_id,
                file_name=file_record.display_name,
                file=file_io,
                metadata=metadata,
                pdf_pass=self.pdf_pass,
                file_type=file_record.file_type,
            )
            documents.extend(new_docs)

            if len(documents) >= self.batch_size:
                yield documents

                documents = []

        if documents:
            yield documents


if __name__ == "__main__":
    connector = LocalFileConnector(
        file_locations=[os.environ["TEST_FILE"]],
        file_names=[os.environ["TEST_FILE"]],
        zip_metadata={},
    )
    connector.load_credentials({"pdf_password": os.environ.get("PDF_PASSWORD")})
    doc_batches = connector.load_from_state()
    for batch in doc_batches:
        print("BATCH:", batch)
