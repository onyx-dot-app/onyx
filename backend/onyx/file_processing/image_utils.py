from typing import Tuple

from sqlalchemy.orm import Session

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.configs.constants import FileOrigin
from onyx.connectors.models import Section
from onyx.db.pg_file_store import save_bytes_to_pgfilestore
from onyx.file_processing.image_summarization import summarize_image_with_error_handling
from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger

logger = setup_logger()


def store_image_and_create_section(
    db_session: Session,
    image_data: bytes,
    file_name: str,
    display_name: str,
    media_type: str = "image/unknown",
    llm: LLM | None = None,
    file_origin: FileOrigin = FileOrigin.OTHER,
) -> Tuple[Section, str | None]:
    """
    Stores an image in PGFileStore and creates a Section object with optional summarization.

    Args:
        db_session: Database session
        image_data: Raw image bytes
        file_name: Base identifier for the file
        display_name: Human-readable name for the image
        media_type: MIME type of the image
        llm: Optional LLM with vision capabilities for summarization
        file_origin: Origin of the file (e.g., CONFLUENCE, GOOGLE_DRIVE, etc.)

    Returns:
        Tuple containing:
        - Section object with image reference and optional summary text
        - The file_name in PGFileStore or None if storage failed
    """
    # Storage logic
    stored_file_name = None
    try:
        pgfilestore = save_bytes_to_pgfilestore(
            db_session=db_session,
            raw_bytes=image_data,
            media_type=media_type,
            identifier=file_name,
            display_name=display_name,
            file_origin=file_origin,
        )
        stored_file_name = pgfilestore.file_name
    except Exception as e:
        logger.error(f"Failed to store image: {e}")
        if not CONTINUE_ON_CONNECTOR_FAILURE:
            raise
        return Section(text=""), None

    # Summarization logic
    summary_text = ""
    if llm:
        summary_text = (
            summarize_image_with_error_handling(llm, image_data, display_name) or ""
        )

    return (
        Section(text=summary_text, image_file_name=stored_file_name),
        stored_file_name,
    )
