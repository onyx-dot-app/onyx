"""OpenSearchIndexClient.update_by_query raises on a skipped chunk only when
the caller asks, so access fields are never left stale by a race."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.document_index.opensearch.client import OpenSearchIndexClient


def _client(result: dict[str, Any]) -> OpenSearchIndexClient:
    client = OpenSearchIndexClient.__new__(OpenSearchIndexClient)
    client._index_name = "test_index"
    client._client = MagicMock()
    client._client.update_by_query.return_value = result
    return client


def test_conflicts_are_skipped_by_default() -> None:
    client = _client({"updated": 3, "version_conflicts": 1, "failures": []})

    assert client.update_by_query({"query": {}}) == 3


def test_conflicts_raise_when_the_caller_asks() -> None:
    client = _client({"updated": 3, "version_conflicts": 1, "failures": []})

    with pytest.raises(RuntimeError, match="version conflicts"):
        client.update_by_query({"query": {}}, fail_on_conflict=True)


def test_no_conflict_returns_the_count_when_the_caller_asks() -> None:
    client = _client({"updated": 4, "version_conflicts": 0, "failures": []})

    assert client.update_by_query({"query": {}}, fail_on_conflict=True) == 4
