from typing import Any

from pydantic import BaseModel, ConfigDict

from onyx.connectors.microsoft_utils.models import MicrosoftRowText


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
    row: MicrosoftRowText
    message: str
    denied: bool


class LibraryProblem(BaseModel):
    row: MicrosoftRowText
    message: str
    name: str
