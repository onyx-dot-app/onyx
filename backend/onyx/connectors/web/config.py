from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeOpaque

_OPAQUE_SCOPE = FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
_BEHAVIOR = FieldPolicy(FieldClass.BEHAVIOR)


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

    # Document ids are the page URLs. A new base URL (e.g. http to https or a
    # new host) usually gives new ids for the same pages: re-index and prune.
    base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    web_connector_type: Annotated[WEB_CONNECTOR_VALID_SETTINGS, _OPAQUE_SCOPE] = (
        WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE
    )
    mintlify_cleanup: Annotated[bool, _BEHAVIOR] = True
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    # Changes the page text. It can also find more links to crawl, but a
    # re-index of the pages already found is the main effect.
    scroll_before_scraping: Annotated[bool, _BEHAVIOR] = False
    # Rewritten URLs are the document ids.
    url_rewrites: Annotated[
        list[UrlRewriteRule] | None, FieldPolicy(FieldClass.IDENTITY)
    ] = None
