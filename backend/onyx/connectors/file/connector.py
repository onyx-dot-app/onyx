import os
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import IO

from sqlalchemy.orm import Session

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.db.engine import get_session_with_current_tenant
from onyx.file_processing.extract_file_text import docx_to_text_and_images
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.extract_file_text import is_valid_file_ext
from onyx.file_processing.extract_file_text import load_files_from_zip
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Constants
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _read_files_and_metadata(
    file_name: str,
    db_session: Session,
) -> Iterator[tuple[str, IO, dict[str, Any]]]:
    """
    Reads the file from Postgres. If the file is a .zip, yields subfiles.
    """
    extension = get_file_ext(file_name)
    metadata: dict[str, Any] = {}
    directory_path = os.path.dirname(file_name)

    # Read file from Postgres store
    file_content = get_default_file_store(db_session).read_file(file_name, mode="b")

    # If it's a zip, expand it
    if extension == ".zip":
        for file_info, subfile, metadata in load_files_from_zip(
            file_content, ignore_dirs=True
        ):
            yield os.path.join(directory_path, file_info.filename), subfile, metadata
    elif is_valid_file_ext(extension):
        yield file_name, file_content, metadata
    else:
        logger.warning(f"Skipping file '{file_name}' with extension '{extension}'")


def _create_image_section(
    image_data: bytes,
    db_session: Session,
    parent_file_name: str,
    display_name: str,
    idx: int = 0,
) -> tuple[ImageSection, str | None]:
    """
    Creates an ImageSection for an image file or embedded image.
    Stores the image in PGFileStore but does not generate a summary.

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
    file_name = f"{parent_file_name}_embedded_{idx}" if idx > 0 else parent_file_name

    # Store the image and create a section
    try:
        section, stored_file_name = store_image_and_create_section(
            db_session=db_session,
            image_data=image_data,
            file_name=file_name,
            display_name=display_name,
            file_origin=FileOrigin.CONNECTOR,
        )
        return section, stored_file_name
    except Exception as e:
        logger.error(f"Failed to store image {display_name}: {e}")
        # Return an empty section with no file name
        return ImageSection(text="", image_file_name=""), None


def _process_file(
    file_name: str,
    file: IO[Any],
    metadata: dict[str, Any] | None,
    pdf_pass: str | None,
    db_session: Session,
) -> list[Document]:
    """
    Process a file and return a list of Documents.
    For images, creates ImageSection objects without summarization.
    For documents with embedded images, extracts and stores the images.
    """
    if metadata is None:
        metadata = {}

    # Get file extension and determine file type
    file_extension = Path(file_name).suffix.lower().lstrip(".")
    mime_type = metadata.get("mime_type", "")

    # Handle image files
    if file_extension in IMAGE_EXTENSIONS or (
        mime_type and mime_type.startswith("image/")
    ):
        try:
            # Read the image data
            image_data = file.read()
            if not image_data:
                logger.warning(f"Empty image file: {file_name}")
                return []

            # Create an ImageSection for the image
            section, _ = _create_image_section(
                image_data=image_data,
                db_session=db_session,
                parent_file_name=file_name,
                display_name=Path(file_name).name,
            )

            # Create a Document with the ImageSection
            return _create_documents_from_sections(
                [section],
                file_name,
                metadata,
            )
        except Exception as e:
            logger.error(f"Failed to process image file {file_name}: {e}")
            return []

    # Handle document files with potential embedded images
    try:
        # For DOCX files, extract text and embedded images
        if file_extension == "docx":
            text, embedded_images = docx_to_text_and_images(file)

            # Create a TextSection for the main text
            sections = [TextSection(text=text)]

            # Create ImageSection objects for embedded images
            for idx, (img_data, img_name) in enumerate(embedded_images, start=1):
                display_name = img_name or f"{Path(file_name).name} - image {idx}"
                image_section, _ = _create_image_section(
                    image_data=img_data,
                    db_session=db_session,
                    parent_file_name=file_name,
                    display_name=display_name,
                    idx=idx,
                )
                sections.append(image_section)

            return _create_documents_from_sections(sections, file_name, metadata)

        # For PDF files, extract text and potentially embedded images
        elif file_extension == "pdf":
            text, pdf_metadata, images = read_pdf_file(file, pdf_pass=pdf_pass)

            # Create a TextSection for the main text
            sections = [TextSection(text=text)]

            # Update metadata with PDF metadata
            if pdf_metadata:
                metadata.update(pdf_metadata)

            # TODO: Handle embedded images in PDFs if needed

            return _create_documents_from_sections(sections, file_name, metadata)

        # For other file types, just extract text
        else:
            text = extract_file_text(file, file_name)
            if not text:
                logger.warning(f"No text extracted from {file_name}")
                return []

            return _create_documents_from_sections(
                [TextSection(text=text)],
                file_name,
                metadata,
            )
    except Exception as e:
        logger.error(f"Failed to process file {file_name}: {e}")
        return []


def _create_documents_from_sections(
    sections: list[TextSection | ImageSection],
    file_name: str,
    metadata: dict[str, Any],
) -> list[Document]:
    """
    Create a Document from sections and metadata.

    Args:
        sections: List of TextSection or ImageSection objects
        file_name: Name of the file
        metadata: Metadata dictionary

    Returns:
        List containing a single Document
    """
    # Extract metadata
    file_display_name = metadata.get("file_display_name") or Path(file_name).name

    # Timestamps
    current_datetime = datetime.now(timezone.utc)
    time_updated = metadata.get("time_updated", current_datetime)
    if isinstance(time_updated, str):
        time_updated = time_str_to_utc(time_updated)

    dt_str = metadata.get("doc_updated_at")
    final_time_updated = time_str_to_utc(dt_str) if dt_str else time_updated

    # Collect owners
    p_owner_names = metadata.get("primary_owners")
    s_owner_names = metadata.get("secondary_owners")
    p_owners = (
        [BasicExpertInfo(display_name=name) for name in p_owner_names]
        if p_owner_names
        else None
    )
    s_owners = (
        [BasicExpertInfo(display_name=name) for name in s_owner_names]
        if s_owner_names
        else None
    )

    # Additional tags we store as doc metadata
    metadata_tags = {
        k: v
        for k, v in metadata.items()
        if k
        not in [
            "document_id",
            "time_updated",
            "doc_updated_at",
            "link",
            "primary_owners",
            "secondary_owners",
            "filename",
            "file_display_name",
            "title",
            "connector_type",
            "pdf_password",
            "mime_type",
        ]
    }

    source_type_str = metadata.get("connector_type")
    source_type = (
        DocumentSource(source_type_str) if source_type_str else DocumentSource.FILE
    )

    doc_id = metadata.get("document_id") or f"FILE_CONNECTOR__{file_name}"
    title = metadata.get("title") or file_display_name

    return [
        Document(
            id=doc_id,
            sections=sections,
            source=source_type,
            semantic_identifier=file_display_name,
            title=title,
            doc_updated_at=final_time_updated,
            primary_owners=p_owners,
            secondary_owners=s_owners,
            metadata=metadata_tags,
        )
    ]


class LocalFileConnector(LoadConnector):
    """
    Connector that reads files from Postgres and yields Documents, including
    embedded image extraction without summarization.
    """

    def __init__(
        self,
        file_locations: list[Path | str],
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.file_locations = [str(loc) for loc in file_locations]
        self.batch_size = batch_size
        self.pdf_pass: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.pdf_pass = credentials.get("pdf_password")

        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        """
        Iterates over each file path, fetches from Postgres, tries to parse text
        or images, and yields Document batches.
        """
        documents: list[Document] = []

        with get_session_with_current_tenant() as db_session:
            for file_path in self.file_locations:
                current_datetime = datetime.now(timezone.utc)

                files_iter = _read_files_and_metadata(
                    file_name=file_path,
                    db_session=db_session,
                )

                for actual_file_name, file, metadata in files_iter:
                    metadata["time_updated"] = metadata.get(
                        "time_updated", current_datetime
                    )
                    new_docs = _process_file(
                        file_name=actual_file_name,
                        file=file,
                        metadata=metadata,
                        pdf_pass=self.pdf_pass,
                        db_session=db_session,
                    )
                    documents.extend(new_docs)

                    if len(documents) >= self.batch_size:
                        yield documents

                        documents = []

            if documents:
                yield documents


if __name__ == "__main__":
    connector = LocalFileConnector(file_locations=[os.environ["TEST_FILE"]])
    connector.load_credentials({"pdf_password": os.environ.get("PDF_PASSWORD")})
    doc_batches = connector.load_from_state()
    for batch in doc_batches:
        print("BATCH:", batch)
