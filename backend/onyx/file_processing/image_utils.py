from typing import Tuple

from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.connectors.models import ImageSection
from onyx.db.pg_file_store import save_bytes_to_pgfilestore
from onyx.utils.logger import setup_logger

logger = setup_logger()


def store_image_and_create_section(
    db_session: Session,
    image_data: bytes,
    file_name: str,
    display_name: str,
    link: str | None = None,
    media_type: str = "application/octet-stream",
    file_origin: FileOrigin = FileOrigin.OTHER,
) -> Tuple[ImageSection, str | None]:
    """
    Stores an image in PGFileStore and creates an ImageSection object without summarization.

    Args:
        db_session: Database session
        image_data: Raw image bytes
        file_name: Base identifier for the file
        display_name: Human-readable name for the image
        media_type: MIME type of the image
        file_origin: Origin of the file (e.g., CONFLUENCE, GOOGLE_DRIVE, etc.)

    Returns:
        Tuple containing:
        - ImageSection object with image reference
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
        raise e

    # Create an ImageSection with empty text (will be filled by LLM later in the pipeline)
    return (
        ImageSection(image_file_name=stored_file_name, link=link),
        stored_file_name,
    )
