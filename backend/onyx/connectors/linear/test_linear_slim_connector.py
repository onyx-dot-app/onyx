"""Unit tests for LinearConnector.retrieve_all_slim_docs (SlimConnector support).

Linear previously only implemented LoadConnector/PollConnector, which meant
the pruning job (see onyx/background/celery/celery_utils.py) fell back to
`load_from_state()` just to enumerate document IDs -- fetching full issue
descriptions and comment bodies on every pruning run. These tests verify the
new slim path only requests `id`, paginates correctly, and yields plain
SlimDocuments with no permission payload (Linear has no perm-sync support).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from onyx.connectors.linear.connector import LinearConnector
from onyx.connectors.models import SlimDocument

_PAGE_1 = {
    "data": {
        "issues": {
            "edges": [
                {"node": {"id": "issue-1"}},
                {"node": {"id": "issue-2"}},
            ],
            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
        }
    }
}

_PAGE_2 = {
    "data": {
        "issues": {
            "edges": [
                {"node": {"id": "issue-3"}},
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }
    }
}


def _mock_response(json_data: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.ok = True
    response.json.return_value = json_data
    return response


def _connector() -> LinearConnector:
    connector = LinearConnector(batch_size=2)
    connector.load_credentials({"linear_api_key": "fake-key"})
    return connector


@patch("onyx.connectors.linear.connector.requests.post")
def test_retrieve_all_slim_docs_paginates_and_returns_ids(
    mock_post: MagicMock,
) -> None:
    mock_post.side_effect = [_mock_response(_PAGE_1), _mock_response(_PAGE_2)]
    connector = _connector()

    batches = list(connector.retrieve_all_slim_docs())
    docs = [doc for batch in batches for doc in batch]

    assert mock_post.call_count == 2
    assert [doc.id for doc in docs] == ["issue-1", "issue-2", "issue-3"]
    assert all(isinstance(doc, SlimDocument) for doc in docs)
    assert all(doc.external_access is None for doc in docs)


@patch("onyx.connectors.linear.connector.requests.post")
def test_retrieve_all_slim_docs_query_excludes_heavy_fields(
    mock_post: MagicMock,
) -> None:
    """The slim query must never request description/comments -- that's the
    whole point of the slim path existing (cheap pruning enumeration)."""
    mock_post.side_effect = [_mock_response(_PAGE_2)]
    connector = _connector()

    list(connector.retrieve_all_slim_docs())

    sent_query = mock_post.call_args.kwargs["json"]["query"]
    assert "description" not in sent_query
    assert "comments" not in sent_query
    assert "id" in sent_query


@patch("onyx.connectors.linear.connector.requests.post")
def test_retrieve_all_slim_docs_respects_should_stop_callback(
    mock_post: MagicMock,
) -> None:
    mock_post.side_effect = [_mock_response(_PAGE_1), _mock_response(_PAGE_2)]
    connector = _connector()

    callback = MagicMock()
    callback.should_stop.return_value = True

    batches = list(connector.retrieve_all_slim_docs(callback=callback))

    assert batches == []
    mock_post.assert_not_called()


@patch("onyx.connectors.linear.connector.requests.post")
def test_retrieve_all_slim_docs_passes_time_filters(mock_post: MagicMock) -> None:
    mock_post.side_effect = [_mock_response(_PAGE_2)]
    connector = _connector()

    connector_start = 1_700_000_000.0
    connector_end = 1_700_100_000.0
    list(connector.retrieve_all_slim_docs(start=connector_start, end=connector_end))

    sent_query = mock_post.call_args.kwargs["json"]["query"]
    assert "gte:" in sent_query
    assert "lte:" in sent_query