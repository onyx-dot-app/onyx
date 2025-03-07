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
from onyx.connectors.models import Section
from onyx.connectors.vision_enabled_connector import VisionEnabledConnector
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.pg_file_store import get_pgfilestore_by_file_name
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.extract_file_text import is_valid_file_ext
from onyx.file_processing.extract_file_text import load_files_from_zip
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
    llm: LLM | None,
    image_data: bytes,
    db_session: Session,
    parent_file_name: str,
    display_name: str,
    idx: int = 0,
) -> tuple[Section, str | None]:
    """
    Create a Section object for a single image and store the image in PGFileStore.
    If summarization is enabled and we have an LLM, summarize the image.

    Returns:
        tuple: (Section object, file_name in PGFileStore or None if storage failed)
    """
    # Create a unique file name for the embedded image
    file_name = f"{parent_file_name}_embedded_{idx}"

    # Use the standardized utility to store the image and create a section
    return store_image_and_create_section(
        db_session=db_session,
        image_data=image_data,
        file_name=file_name,
        display_name=display_name,
        llm=llm,
        file_origin=FileOrigin.OTHER,
    )


def _process_file(
    file_name: str,
    file: IO[Any],
    metadata: dict[str, Any] | None,
    pdf_pass: str | None,
    db_session: Session,
    llm: LLM | None,
) -> list[Document]:
    """
    Processes a single file, returning a list of Documents (typically one).
    Also handles embedded images if 'EMBEDDED_IMAGE_EXTRACTION_ENABLED' is true.
    """
    extension = get_file_ext(file_name)

    # Fetch the DB record so we know the ID for internal URL
    pg_record = get_pgfilestore_by_file_name(file_name=file_name, db_session=db_session)
    if not pg_record:
        logger.warning(f"No file record found for '{file_name}' in PG; skipping.")
        return []

    if not is_valid_file_ext(extension):
        logger.warning(
            f"Skipping file '{file_name}' with unrecognized extension '{extension}'"
        )
        return []

    # Prepare doc metadata
    if metadata is None:
        metadata = {}
    file_display_name = metadata.get("file_display_name") or os.path.basename(file_name)

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
        ]
    }

    source_type_str = metadata.get("connector_type")
    source_type = (
        DocumentSource(source_type_str) if source_type_str else DocumentSource.FILE
    )

    doc_id = metadata.get("document_id") or f"FILE_CONNECTOR__{file_name}"
    title = metadata.get("title") or file_display_name

    # 1) If the file itself is an image, handle that scenario quickly
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
    if extension in IMAGE_EXTENSIONS:
        # Summarize or produce empty doc
        image_data = file.read()
        image_section, _ = _create_image_section(
            llm, image_data, db_session, pg_record.file_name, title
        )
        return [
            Document(
                id=doc_id,
                sections=[image_section],
                source=source_type,
                semantic_identifier=file_display_name,
                title=title,
                doc_updated_at=final_time_updated,
                primary_owners=p_owners,
                secondary_owners=s_owners,
                metadata=metadata_tags,
            )
        ]

    # 2) Otherwise: text-based approach. Possibly with embedded images if enabled.
    #    (For example .docx with inline images).
    file.seek(0)
    text_content = ""
    embedded_images: list[tuple[bytes, str]] = []

    text_content, embedded_images = extract_text_and_images(
        file=file,
        file_name=file_name,
        pdf_pass=pdf_pass,
    )

    # Build sections: first the text as a single Section
    sections = []
    link_in_meta = metadata.get("link")
    if text_content.strip():
        sections.append(Section(link=link_in_meta, text=text_content.strip()))

    # Then any extracted images from docx, etc.
    for idx, (img_data, img_name) in enumerate(embedded_images, start=1):
        # Store each embedded image as a separate file in PGFileStore
        # and create a section with the image summary
        image_section, _ = _create_image_section(
            llm,
            img_data,
            db_session,
            pg_record.file_name,
            f"{title} - image {idx}",
            idx,
        )
        sections.append(image_section)
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


class LocalFileConnector(LoadConnector, VisionEnabledConnector):
    """
    Connector that reads files from Postgres and yields Documents, including
    optional embedded image extraction.
    """

    def __init__(
        self,
        file_locations: list[Path | str],
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.file_locations = [str(loc) for loc in file_locations]
        self.batch_size = batch_size
        self.pdf_pass: str | None = None

        # Initialize vision LLM using the mixin
        self.initialize_vision_llm()

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
                        llm=self.image_analysis_llm,
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
