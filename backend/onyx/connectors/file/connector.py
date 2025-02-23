import os
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import IO

from sqlalchemy.orm import Session

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.configs.app_configs import EMBEDDED_IMAGE_EXTRACTION_ENABLED
from onyx.configs.app_configs import IMAGE_SUMMARIZATION_ENABLED
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.pg_file_store import get_pgfilestore_by_file_name
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.extract_file_text import is_valid_file_ext
from onyx.file_processing.extract_file_text import load_files_from_zip
from onyx.file_processing.image_summarization import summarize_image_pipeline
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.factory import get_default_llms
from onyx.llm.interfaces import LLM
from onyx.llm.utils import model_supports_image_input
from onyx.prompts.image_analysis import IMAGE_SUMMARIZATION_SYSTEM_PROMPT
from onyx.prompts.image_analysis import IMAGE_SUMMARIZATION_USER_PROMPT
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


def _summarize_image(
    llm: LLM,
    image_data: bytes,
    file_display_name: str,
) -> str | None:
    """
    Summarizes a single embedded image.
    """
    user_prompt = IMAGE_SUMMARIZATION_USER_PROMPT.format(title=file_display_name)
    try:
        return summarize_image_pipeline(
            llm,
            image_data,
            user_prompt,
            system_prompt=IMAGE_SUMMARIZATION_SYSTEM_PROMPT,
        )
    except Exception as e:
        if CONTINUE_ON_CONNECTOR_FAILURE:
            logger.warning(f"Image summarization failed for {file_display_name}: {e}")
            return None
        raise


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
    pg_record_id: str,
    display_name: str,
) -> Section:
    """
    Create a Section object for a single image. If summarization is enabled and we have an LLM,
    summarize the image. Otherwise, empty text.
    The image_url references the internal file URL.
    """
    internal_url = f"INTERNAL_URL/api/file/{pg_record_id}"

    summary_text = ""
    if IMAGE_SUMMARIZATION_ENABLED and llm:
        try:
            summary_text = _summarize_image(llm, image_data, display_name) or ""
        except Exception as e:
            logger.error(f"Unable to summarize embedded image: {e}")
            if not CONTINUE_ON_CONNECTOR_FAILURE:
                raise

    return Section(text=summary_text, image_url=internal_url)


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
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}
    if extension in IMAGE_EXTENSIONS:
        # Summarize or produce empty doc
        image_data = file.read()
        image_section = _create_image_section(
            llm, image_data, pg_record.file_name, title
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
        embedded_image_support=EMBEDDED_IMAGE_EXTRACTION_ENABLED,
    )

    # Build sections: first the text as a single Section
    sections = []
    link_in_meta = metadata.get("link")
    if text_content.strip():
        sections.append(Section(link=link_in_meta, text=text_content.strip()))

    # Then any extracted images from docx, etc.
    for idx, (img_data, img_name) in enumerate(embedded_images, start=1):
        # We create a new section with an image summary
        # We do not store each embedded image separately in Postgres by default:
        # so we can't do the best "INTERNAL_URL/api/file/<id>" for each embedded image
        # unless you store them separately. For demonstration, we'll re-use the doc's ID
        # with a suffix or keep the same ID.
        # If you want actual image retrieval, you'd have to store them separately.
        # For now, we just simulate an internal URL:
        faux_image_id = f"{pg_record.file_name}_embedded_{idx}"
        image_section = _create_image_section(
            llm, img_data, faux_image_id, f"{title} - image {idx}"
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


class LocalFileConnector(LoadConnector):
    """
    Connector that reads files from Postgres and yields Documents, including
    optional embedded image extraction.
    """

    def __init__(
        self,
        file_locations: list[Path | str],
        tenant_id: str = POSTGRES_DEFAULT_SCHEMA,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.file_locations = [Path(file_location) for file_location in file_locations]
        self.batch_size = batch_size
        self.tenant_id = tenant_id
        self.pdf_pass: str | None = None
        self.llm: LLM | None = None

        # Check if image summarization is enabled and if the LLM has vision
        if IMAGE_SUMMARIZATION_ENABLED:
            llm, _ = get_default_llms()
            if not model_supports_image_input(
                llm.config.model_name, llm.config.model_provider
            ):
                raise ValueError(
                    f"The configured default LLM {llm.config.model_provider}/{llm.config.model_name} "
                    "does not appear to support image input for summarization."
                )
            self.llm = llm
        else:
            self.llm = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.pdf_pass = credentials.get("pdf_password")
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        """
        Iterates over each file path, fetches from Postgres, tries to parse text
        or images, and yields Document batches.
        """
        documents: list[Document] = []
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(self.tenant_id)

        with get_session_with_current_tenant() as db_session:
            for file_path in self.file_locations:
                current_datetime = datetime.now(timezone.utc)

                files_iter = _read_files_and_metadata(
                    file_name=str(file_path),
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
                        llm=self.llm,
                    )
                    documents.extend(new_docs)

                    if len(documents) >= self.batch_size:
                        yield documents
                        documents = []

            if documents:
                yield documents

        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


if __name__ == "__main__":
    connector = LocalFileConnector(file_locations=[os.environ["TEST_FILE"]])
    connector.load_credentials({"pdf_password": os.environ.get("PDF_PASSWORD")})
    doc_batches = connector.load_from_state()
    for batch in doc_batches:
        print("BATCH:", batch)
