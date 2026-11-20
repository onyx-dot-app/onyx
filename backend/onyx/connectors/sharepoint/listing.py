"""The SharePoint stub listing: what the listing stores for each document, so
that the conversion stage can fetch and convert it with no metadata call.

The listing walks the same delta pages as the fetching path. For each file
that indexing keeps, it yields a ``SlimDocumentStub`` and no content. A site
page is listed with its metadata only: the listing does not read the page's
canvas, which is the page's content.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from onyx.connectors.microsoft_utils.drive_items import (
    DRIVE_ITEM_DOWNLOAD_URL_SELECT,
    DRIVE_ITEM_SELECT_FIELDS,
    DriveItemData,
    parse_graph_datetime,
)
from onyx.connectors.models import ListingPayload, SlimDocumentStub
from onyx.file_processing.file_types import OnyxMimeTypes, is_indexable_file_type

CANVAS_LAYOUT_PROPERTY = "canvasLayout"
# The fields of a file that the listing maps. Not the download URL: the
# listing downloads nothing, and conversion downloads by drive and item id.
LISTING_SELECT_FIELDS = ",".join(
    field
    for field in DRIVE_ITEM_SELECT_FIELDS.split(",")
    if field != DRIVE_ITEM_DOWNLOAD_URL_SELECT
)


class SharepointListedKind(str, Enum):
    DRIVE_ITEM = "drive_item"
    SITE_PAGE = "site_page"


class SharepointListingPayload(ListingPayload):
    """What conversion needs to fetch one listed file or site page.

    It never holds the file's ``downloadUrl``: that URL expires in about an
    hour, and it is a credential for the file. Conversion downloads by drive
    id and item id."""

    kind: SharepointListedKind
    site_url: str
    name: str
    web_url: str
    parent_hierarchy_raw_node_id: str | None = None
    created_datetime: datetime | None = None
    last_modified_datetime: datetime | None = None

    # A file in a document library.
    drive_id: str | None = None
    item_id: str | None = None
    drive_name: str | None = None
    # The SharePoint list behind the library and the file's item in it. The
    # permission reads address them.
    list_id: str | None = None
    list_item_id: str | None = None
    # The file's ``parentReference.path``.
    parent_path: str | None = None
    mime_type: str | None = None
    size: int | None = None
    last_modified_by_display_name: str | None = None
    last_modified_by_email: str | None = None

    # A site page: the site's Graph id, and the page as the listing returned
    # it, with no canvas.
    site_id: str | None = None
    site_page: dict[str, Any] | None = None


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


def drive_item_stub(
    item: DriveItemData,
    *,
    site_url: str,
    drive_id: str,
    drive_name: str,
    list_id: str | None,
    parent_hierarchy_raw_node_id: str,
) -> SlimDocumentStub:
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
        ),
    )


def drive_item_from_payload(payload: SharepointListingPayload) -> DriveItemData:
    """The listed file, with no download URL."""
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
    )


def site_page_stub(
    site_page: dict[str, Any], *, site_id: str, site_url: str
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
            site_page=metadata,
        ),
    )
