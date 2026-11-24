from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from onyx.connectors.models import CheckRowText, ListingPayload


class SharepointCredentials(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sp_client_id: str | None = None
    sp_directory_id: str | None = None
    sp_client_secret: str | None = None
    authentication_method: str | None = None
    sp_private_key: str | None = None
    sp_certificate_password: str | None = None


class SharepointDrive(BaseModel):
    """A document library as Graph lists it. ``list_id`` is the SharePoint
    list behind it, which the permission reads address. Graph can list a
    library without its traversal metadata, so the connector requires it only
    on the library it selects."""

    model_config = ConfigDict(frozen=True)

    id: str | None = None
    name: str | None = None
    web_url: str | None = None
    drive_type: str | None = None
    list_id: str | None = None


class SitePagesPage(BaseModel):
    """One page of a site's pages listing, each page as Graph returned it."""

    pages: list[dict[str, Any]]
    next_link: str | None = None


class SiteUrlListing(BaseModel):
    """The tenant's site listing, by web URL. ``complete`` is False when a
    page cap stopped the read before the last page."""

    site_urls: list[str]
    complete: bool


class EntraGroupRef(BaseModel):
    id: str
    name: str


class SiteProblem(BaseModel):
    site_url: str
    row: CheckRowText
    message: str
    denied: bool


class LibraryProblem(BaseModel):
    row: CheckRowText
    message: str
    name: str


class SharepointListedKind(str, Enum):
    DRIVE_ITEM = "drive_item"
    SITE_PAGE = "site_page"


class SharepointListingPayload(ListingPayload):
    """What conversion needs to fetch one listed file or site page.

    The file's download link is a credential for the file, so the payload
    holds it only encrypted (``encrypted_download_url``). Conversion uses it
    while it is fresh, and else downloads by drive id and item id."""

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
    # The listing's download link, encrypted with the deployment's key and in
    # base64, and when the listing read it. Never log the decrypted link.
    encrypted_download_url: str | None = None
    download_url_listed_at: datetime | None = None
    # The listing run that listed the document. Conversion keys the shared
    # permission cache by it, so that a run never reads access that another
    # run or another credential cached. None: conversion keeps the cache in
    # the process.
    listing_run_id: str | None = None

    # A site page: the site's Graph id, and the page as the listing returned
    # it, with no canvas.
    site_id: str | None = None
    # The "site" value of the page document's metadata, when it has one.
    site_name: str | None = None
    site_page: dict[str, Any] | None = None
