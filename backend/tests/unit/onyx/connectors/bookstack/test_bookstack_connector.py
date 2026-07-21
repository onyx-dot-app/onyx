from typing import Any, cast
from unittest.mock import MagicMock

from onyx.connectors.bookstack.client import BookStackApiClient
from onyx.connectors.bookstack.connector import BookstackConnector
from onyx.connectors.models import Document


def _unused_transformer(
    bookstack_client: BookStackApiClient, item: dict[str, Any]
) -> Document:
    del bookstack_client, item
    return cast(Document, MagicMock())


def test_get_doc_batch_uses_datetime_updated_at_filters() -> None:
    bookstack_client = MagicMock()
    bookstack_client.get.return_value = {"data": []}

    docs, num_results = BookstackConnector._get_doc_batch(
        batch_size=10,
        bookstack_client=bookstack_client,
        endpoint="/pages",
        transformer=_unused_transformer,
        start_ind=20,
        start=0,
        end=1711974896.789123,
    )

    assert docs == []
    assert num_results == 0
    bookstack_client.get.assert_called_once_with(
        "/pages",
        params={
            "count": "10",
            "offset": "20",
            "sort": "+id",
            "filter[updated_at:gte]": "1970-01-01T00:00:00.000000Z",
            "filter[updated_at:lte]": "2024-04-01T12:34:56.789123Z",
        },
    )


def test_get_doc_batch_omits_updated_at_filters_without_poll_window() -> None:
    bookstack_client = MagicMock()
    bookstack_client.get.return_value = {"data": []}

    BookstackConnector._get_doc_batch(
        batch_size=5,
        bookstack_client=bookstack_client,
        endpoint="/books",
        transformer=_unused_transformer,
        start_ind=0,
    )

    _, kwargs = bookstack_client.get.call_args
    params: dict[str, Any] = kwargs["params"]
    assert "filter[updated_at:gte]" not in params
    assert "filter[updated_at:lte]" not in params
