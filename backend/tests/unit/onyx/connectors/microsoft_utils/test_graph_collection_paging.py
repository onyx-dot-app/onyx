"""iter_graph_collection follows nextLink and sends the query only once."""

from typing import Any

from onyx.connectors.microsoft_utils.graph_client import (
    GraphApiClient,
    iter_graph_collection,
)

URL = "https://graph.microsoft.com/v1.0/groups"
NEXT_LINK = f"{URL}?$skiptoken=abc"


class _PagedClient(GraphApiClient):
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        super().__init__(lambda: "fake-token", "https://graph.microsoft.com/v1.0")
        self._pages = list(pages)
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get_json(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,  # noqa: ARG002
    ) -> dict[str, Any]:
        self.calls.append((url, params))
        return self._pages.pop(0)


def test_single_page() -> None:
    client = _PagedClient([{"value": [{"id": "1"}, {"id": "2"}]}])

    items = list(iter_graph_collection(client, URL, {"$top": "999"}))

    assert items == [{"id": "1"}, {"id": "2"}]
    assert client.calls == [(URL, {"$top": "999"})]


def test_follows_next_link_without_resending_params() -> None:
    client = _PagedClient(
        [
            {"value": [{"id": "1"}], "@odata.nextLink": NEXT_LINK},
            {"value": [{"id": "2"}]},
        ]
    )

    items = list(iter_graph_collection(client, URL, {"$top": "999"}))

    assert items == [{"id": "1"}, {"id": "2"}]
    assert client.calls == [(URL, {"$top": "999"}), (NEXT_LINK, None)]


def test_empty_page() -> None:
    client = _PagedClient([{"value": []}])

    assert list(iter_graph_collection(client, URL)) == []
