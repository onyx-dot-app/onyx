from typing import Any

from pydantic import BaseModel, ConfigDict


class SharepointCredentials(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sp_client_id: str | None = None
    sp_directory_id: str | None = None
    sp_client_secret: str | None = None
    authentication_method: str | None = None
    sp_private_key: str | None = None
    sp_certificate_password: str | None = None


class SharepointTokenInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    expires_in: int | None


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
