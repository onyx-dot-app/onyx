from enum import Enum

from pydantic import BaseModel, ConfigDict

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class WEB_CONNECTOR_VALID_SETTINGS(str, Enum):
    # Given a base site, index everything under that path
    RECURSIVE = "recursive"
    # Given a URL, index only the given page
    SINGLE = "single"
    # Given a sitemap.xml URL, parse all the pages in it
    SITEMAP = "sitemap"
    # Given a file upload where every line is a URL, parse all the URLs provided
    UPLOAD = "upload"


class UrlRewriteRule(BaseModel):
    """A single URL prefix rewrite: any fetched URL starting with ``source``
    has that prefix replaced by ``target`` before the document is stored."""

    source: str
    target: str


class WebConnectorConfig(ConnectorConfig):
    model_config = ConfigDict(extra="allow")

    base_url: str
    web_connector_type: WEB_CONNECTOR_VALID_SETTINGS = (
        WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE
    )
    mintlify_cleanup: bool = True
    batch_size: int = INDEX_BATCH_SIZE
    scroll_before_scraping: bool = False
    url_rewrites: list[UrlRewriteRule] | None = None
