"""Gateway and error builders that the Notion capability check tests share."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, create_autospec

from onyx.connectors.notion.models import NotionSearchObjectType, NotionSearchResponse
from onyx.connectors.notion.source_operations import (
    NotionApiError,
    NotionSourceOperations,
)

_PAGE = {"id": "page-1", "object": "page"}
_DATA_SOURCE = {
    "id": "ds-1",
    "object": "data_source",
    "parent": {"type": "database_id", "database_id": "db-1"},
}


def _search_page(results: list[dict[str, Any]]) -> NotionSearchResponse:
    return NotionSearchResponse(results=results, next_cursor=None, has_more=False)


def workspace_gateway(
    *,
    pages: list[dict[str, Any]] | None = None,
    data_sources: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """A workspace that shares the given pages and data sources."""
    shared: dict[NotionSearchObjectType, list[dict[str, Any]]] = {
        NotionSearchObjectType.PAGE: [_PAGE] if pages is None else pages,
        NotionSearchObjectType.DATA_SOURCE: (
            [_DATA_SOURCE] if data_sources is None else data_sources
        ),
    }

    def iter_search(
        *, object_type: NotionSearchObjectType, **_kwargs: Any
    ) -> Iterator[NotionSearchResponse]:
        return iter([_search_page(shared[object_type])])

    gateway: MagicMock = create_autospec(NotionSourceOperations, instance=True)
    gateway.iter_search.side_effect = iter_search
    gateway.get_bot_user.return_value = {"object": "user", "type": "bot"}
    gateway.get_page.return_value = {"object": "page", "id": "root"}
    gateway.get_database.return_value = {"object": "database", "id": "db-1"}
    gateway.get_block_children.return_value = {"results": [], "next_cursor": None}
    gateway.query_data_source.return_value = {"results": [], "next_cursor": None}
    gateway.list_users.return_value = {"results": [], "next_cursor": None}
    return gateway


def api_error(status: int | None, code: str | None = None) -> NotionApiError:
    return NotionApiError(f"HTTP {status} {code}", status_code=status, code=code)
