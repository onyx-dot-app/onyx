from io import BytesIO
from typing import Tuple

from onyx.configs.constants import FileOrigin
from onyx.connectors.models import ImageSection
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()


def store_image_and_create_section(
    image_data: bytes,
    file_id: str,
    display_name: str,
    link: str | None = None,
    media_type: str = "application/octet-stream",
    file_origin: FileOrigin = FileOrigin.OTHER,
) -> Tuple[ImageSection, str | None]:
    """
    Stores an image in FileStore and creates an ImageSection object without summarization.

    Args:
        image_data: Raw image bytes
        file_id: Base identifier for the file
        display_name: Human-readable name for the image
        media_type: MIME type of the image
        file_origin: Origin of the file (e.g., CONFLUENCE, GOOGLE_DRIVE, etc.)

    Returns:
        Tuple containing:
        - ImageSection object with image reference
        - The file_id in FileStore or None if storage failed
    """
    # Storage logic
    try:
        file_store = get_default_file_store()
        file_id = file_store.save_file(
            content=BytesIO(image_data),
            display_name=display_name,
            file_origin=file_origin,
            file_type=media_type,
            file_id=file_id,
        )
    except Exception as e:
        logger.error(f"Failed to store image: {e}")
        raise e

    # Create an ImageSection with empty text (will be filled by LLM later in the pipeline)
    return (
        ImageSection(image_file_id=file_id, link=link),
        file_id,
    )
