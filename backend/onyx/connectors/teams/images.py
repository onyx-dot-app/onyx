"""The images people paste into a message, stored for the vision model."""

from collections.abc import Callable
from hashlib import sha256

import requests
from pydantic import BaseModel

from onyx.configs.app_configs import TEAMS_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD
from onyx.configs.constants import FileOrigin
from onyx.connectors.microsoft_utils.drive_items import (
    SizeCapExceeded,
    download_graph_url_with_cap,
)
from onyx.connectors.models import ImageSection
from onyx.connectors.teams.models import Message
from onyx.connectors.teams.refusals import is_permanent
from onyx.connectors.teams.session import TeamsSession
from onyx.connectors.teams.utils import hosted_content_urls
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()

# What a document left out of what was pasted, so a reader who sees fewer images
# than the conversation had can tell why.
IMAGES_NOT_INDEXED = "images_not_indexed"

# Each pasted image costs a download now and a vision-model call at indexing,
# so a document stops well past what a working conversation holds.
MAX_IMAGES_PER_DOCUMENT = 100

# The images of one message within a budget, and the downloads charged to it.
MessageImages = Callable[[Message, int], "ImageHarvest"]


class ImageHarvest(BaseModel):
    """What one message gave the thread: its image sections, the downloads they
    cost the thread budget, and the images left out of the document."""

    sections: list[ImageSection]
    downloads: int
    missed: int


def _image_media_type(data: bytes) -> str:
    """Graph names no trustworthy type on the hosted content route, so the type
    is read off the bytes."""
    try:
        return get_image_type_from_bytes(data)
    except ValueError:
        return "application/octet-stream"


def harvest_message_images(
    session: TeamsSession, message: Message, limit: int, link: str | None = None
) -> ImageHarvest:
    """Up to ``limit`` images pasted into one message, stored for the vision
    model. Nothing is downloaded while image analysis is off. A refused or
    oversized image is left out, anything else fails the attempt so the page
    is retried."""
    if not session.allow_images or not message.body.content:
        return ImageHarvest(sections=[], downloads=0, missed=0)
    pasted = hosted_content_urls(message.body.content, session.graph_root)
    urls = pasted[:limit]
    missed = len(pasted) - len(urls)
    sections: list[ImageSection] = []
    for url in urls:
        try:
            data = download_graph_url_with_cap(
                session.access_token(),
                url,
                TEAMS_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD,
                description=f"image of message {message.id}",
            )
        except SizeCapExceeded:
            logger.warning("Skipping an oversized image of message %s", message.id)
            missed += 1
            continue
        except requests.HTTPError as e:
            if not is_permanent(e):
                raise
            logger.warning("Skipping an image of message %s: %s", message.id, e)
            missed += 1
            continue
        section, _ = store_image_and_create_section(
            image_data=data,
            # Deterministic, so a re-index overwrites instead of piling up.
            file_id=f"teams-image-{sha256(url.encode()).hexdigest()[:32]}",
            display_name=f"Image in a message of {message.created_date_time:%Y-%m-%d}",
            link=link or message.web_url,
            media_type=_image_media_type(data),
            file_origin=FileOrigin.CONNECTOR,
        )
        sections.append(section)
    return ImageHarvest(sections=sections, downloads=len(urls), missed=missed)
