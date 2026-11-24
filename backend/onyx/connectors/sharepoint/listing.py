"""The SharePoint stub listing: what the listing stores for each document, so
that the conversion stage can fetch and convert it with no metadata call.

The listing walks the same delta pages as the fetching path. For each file
that indexing keeps, it yields a ``SlimDocumentStub`` and no content. A site
page is listed with its metadata only: the listing does not read the page's
canvas, which is the page's content.

A file's stub keeps the pre-authenticated download link of the listing
(``@microsoft.graph.downloadUrl``), encrypted as credentials are, and the
time of the listing. While the link is younger than ``DOWNLOAD_URL_MAX_AGE``,
conversion downloads from it, which is no Graph call. An older or refused
link falls back to Graph ``/content`` (1 RU).
"""

import base64
from datetime import datetime, timedelta, timezone
from typing import Any

from onyx.connectors.microsoft_utils.drive_items import (
    DRIVE_ITEM_SELECT_FIELDS,
    DriveItemData,
    parse_graph_datetime,
)
from onyx.connectors.models import SlimDocumentStub
from onyx.connectors.sharepoint.models import (
    SharepointListedKind,
    SharepointListingPayload,
)
from onyx.file_processing.file_types import OnyxMimeTypes, is_indexable_file_type
from onyx.utils.datetime import datetime_to_utc
from onyx.utils.encryption import decrypt_bytes_to_string, encrypt_string_to_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()

CANVAS_LAYOUT_PROPERTY = "canvasLayout"
# The fields of a file that the listing maps, with its download link.
LISTING_SELECT_FIELDS = DRIVE_ITEM_SELECT_FIELDS
# Graph's download links live about one hour. Conversion uses a stored link
# only while it is younger than this, so a slow download still starts in time.
DOWNLOAD_URL_MAX_AGE = timedelta(minutes=45)


def is_listable_drive_item(item: DriveItemData, size_threshold: int) -> bool:
    """True when the fetching path can make a document from the file: a
    supported type, a mime type that is not excluded, and a size under the
    limit. Conversion checks the size again when the listing has none."""
    if not item.id or not item.name:
        return False
    if not is_indexable_file_type(item.name, None, allow_images=True):
        return False
    if not item.mime_type or item.mime_type in OnyxMimeTypes.EXCLUDED_IMAGE_TYPES:
        return False
    return item.size is None or item.size <= size_threshold


def _encrypt_download_url(url: str) -> str:
    return base64.b64encode(encrypt_string_to_bytes(url)).decode("ascii")


def fresh_download_url(payload: SharepointListingPayload) -> str | None:
    """The listed download link, while it is younger than
    ``DOWNLOAD_URL_MAX_AGE``. None when the payload has none, it is too old,
    or it does not decrypt (for example after a key change)."""
    if not payload.encrypted_download_url or payload.download_url_listed_at is None:
        return None
    age = datetime.now(timezone.utc) - datetime_to_utc(payload.download_url_listed_at)
    if age >= DOWNLOAD_URL_MAX_AGE:
        return None
    try:
        return decrypt_bytes_to_string(base64.b64decode(payload.encrypted_download_url))
    except Exception as e:
        logger.warning(
            "Could not decrypt the listed download link of item %s (%s); "
            "downloading by item id",
            payload.item_id,
            type(e).__name__,
        )
        return None


def drive_item_stub(
    item: DriveItemData,
    *,
    site_url: str,
    drive_id: str,
    drive_name: str,
    list_id: str | None,
    parent_hierarchy_raw_node_id: str,
    listing_run_id: str | None,
) -> SlimDocumentStub:
    encrypted_download_url = (
        _encrypt_download_url(item.download_url) if item.download_url else None
    )
    return SlimDocumentStub(
        id=item.id,
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
        doc_created_at=item.created_datetime,
        doc_updated_at=item.last_modified_datetime,
        mime_type=item.mime_type,
        size_bytes=item.size,
        listing_payload=SharepointListingPayload(
            kind=SharepointListedKind.DRIVE_ITEM,
            site_url=site_url,
            name=item.name,
            web_url=item.web_url,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
            created_datetime=item.created_datetime,
            last_modified_datetime=item.last_modified_datetime,
            drive_id=item.drive_id or drive_id,
            item_id=item.id,
            drive_name=drive_name,
            list_id=list_id,
            list_item_id=item.list_item_id,
            parent_path=item.parent_reference_path,
            mime_type=item.mime_type,
            size=item.size,
            last_modified_by_display_name=item.last_modified_by_display_name,
            last_modified_by_email=item.last_modified_by_email,
            encrypted_download_url=encrypted_download_url,
            download_url_listed_at=(
                datetime.now(timezone.utc) if encrypted_download_url else None
            ),
            listing_run_id=listing_run_id,
        ),
    )


def drive_item_from_payload(payload: SharepointListingPayload) -> DriveItemData:
    """The listed file, with its download link while the link is fresh."""
    if not payload.item_id or not payload.drive_id:
        raise ValueError("The listing payload names no drive item")
    return DriveItemData(
        id=payload.item_id,
        name=payload.name,
        web_url=payload.web_url,
        size=payload.size,
        mime_type=payload.mime_type,
        created_datetime=payload.created_datetime,
        last_modified_datetime=payload.last_modified_datetime,
        last_modified_by_display_name=payload.last_modified_by_display_name,
        last_modified_by_email=payload.last_modified_by_email,
        parent_reference_path=payload.parent_path,
        drive_id=payload.drive_id,
        list_item_id=payload.list_item_id,
        download_url=fresh_download_url(payload),
    )


def site_page_stub(
    site_page: dict[str, Any],
    *,
    site_id: str,
    site_url: str,
    site_name: str | None,
    listing_run_id: str | None,
) -> SlimDocumentStub | None:
    """The stub of a listed site page, or None when the page has no id."""
    page_id = site_page.get("id")
    if not isinstance(page_id, str) or not page_id:
        return None
    created = parse_graph_datetime(site_page.get("createdDateTime"))
    # The same value that the page's document stores as its update time, so
    # that an unchanged page is not fetched again.
    updated = parse_graph_datetime(site_page.get("lastModifiedDateTime")) or created
    metadata = {
        key: value for key, value in site_page.items() if key != CANVAS_LAYOUT_PROPERTY
    }
    return SlimDocumentStub(
        id=page_id,
        parent_hierarchy_raw_node_id=site_url,
        doc_created_at=created,
        doc_updated_at=updated,
        listing_payload=SharepointListingPayload(
            kind=SharepointListedKind.SITE_PAGE,
            site_url=site_url,
            name=str(site_page.get("name") or site_page.get("title") or ""),
            web_url=str(site_page.get("webUrl") or ""),
            parent_hierarchy_raw_node_id=site_url,
            created_datetime=created,
            last_modified_datetime=updated,
            site_id=site_id,
            site_name=site_name,
            site_page=metadata,
            listing_run_id=listing_run_id,
        ),
    )
