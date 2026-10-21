import re
from typing import Annotated
from urllib.parse import parse_qs, urlparse

from pydantic import field_validator

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP,
)
from onyx.connectors.connector_config import ConnectorConfig, field_format_error
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeInclude,
    ScopeToggle,
)
from onyx.connectors.planning_rule import ConnectorChangeOverride

_RECURSIVE_INDEX_ENABLED = "recursive_index_enabled"

ROOT_PAGE_ID_FORMAT_ERROR = "Paste the page URL or its 32-character ID."

_HEX_ID = re.compile(r"[0-9a-fA-F]{32}")
_DASHED_ID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _dashed(hex_id: str) -> str:
    return (
        f"{hex_id[0:8]}-{hex_id[8:12]}-{hex_id[12:16]}-{hex_id[16:20]}-{hex_id[20:]}"
    ).lower()


def page_id_from_url(url: str) -> str | None:
    """The page ID (a dashed UUID) in a Notion page URL, or None."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if not (
        "notion.so" in netloc or "notion.site" in netloc or "app.notion.com" in netloc
    ):
        return None

    # The path ends in "Title-PageID".
    path_last = parsed.path.split("/")[-1]
    candidate = path_last.split("-")[-1] if "-" in path_last else path_last
    cleaned = re.sub(r"[^0-9a-fA-F-]", "", candidate).replace("-", "")
    if _HEX_ID.fullmatch(cleaned):
        return _dashed(cleaned)

    params = parse_qs(parsed.query)
    for key in ("p", "page_id"):
        if key in params and params[key]:
            candidate = params[key][0].replace("-", "")
            if _HEX_ID.fullmatch(candidate):
                return _dashed(candidate)
    return None


class NotionConnectorConfig(ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    # Also follows child pages that search does not return.
    recursive_index_enabled: Annotated[
        bool, FieldPolicy(FieldClass.SCOPE, scope=ScopeToggle(widens_when=True))
    ] = not NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP
    # Empty indexes every page that search returns.
    root_page_id: Annotated[
        str | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None

    # The connector sends the value to Notion as a page ID, so a URL becomes
    # the ID it holds.
    @field_validator("root_page_id")
    @classmethod
    def _root_page_is_an_id_or_url(cls, value: str | None) -> str | None:
        root: str = (value or "").strip()
        if not root or _HEX_ID.fullmatch(root) or _DASHED_ID.fullmatch(root):
            return value
        page_id: str | None = page_id_from_url(root)
        if page_id is None:
            raise field_format_error(ROOT_PAGE_ID_FORMAT_ERROR)
        return page_id


def notion_planning_rule(
    old: NotionConnectorConfig, new: NotionConnectorConfig
) -> ConnectorChangeOverride | None:
    # The connector always follows child pages from a root page.
    if old.root_page_id and new.root_page_id:
        return ConnectorChangeOverride(
            scope_directions={_RECURSIVE_INDEX_ENABLED: ScopeDirection.NONE}
        )
    return None
