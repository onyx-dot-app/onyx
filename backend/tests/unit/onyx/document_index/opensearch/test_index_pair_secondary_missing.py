"""Unit test for OpenSearchIndexPair.update's FUTURE-404 conversion.

Pure-Python glue: the pair lets PRESENT (primary) write, then converts a
secondary OpenSearchDocumentMissingError into a typed SecondaryIndexDocumentMissingError
carrying the doc ids. The underlying 404/409 behavior is covered for real against
a live cluster in tests/external_dependency_unit/opensearch/test_opensearch_client.py.
"""

from unittest.mock import MagicMock

import pytest

from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.document_index.opensearch.client import OpenSearchDocumentMissingError
from onyx.document_index.opensearch.client import OpenSearchUpdateError
from onyx.document_index.opensearch.opensearch_document_index import OpenSearchIndexPair
from onyx.document_index.opensearch.opensearch_document_index import (
    SecondaryIndexDocumentMissingError,
)


def _make_pair(secondary: object) -> tuple[OpenSearchIndexPair, MagicMock]:
    """Returns the pair plus the primary mock (asserting through the typed
    `_primary` attribute would confuse the type checker)."""
    pair = OpenSearchIndexPair.__new__(OpenSearchIndexPair)
    primary = MagicMock()
    pair._primary = primary
    pair._secondary = secondary
    return pair, primary


def _update_request() -> MetadataUpdateRequest:
    return MetadataUpdateRequest(
        document_ids=["doc-1"], doc_id_to_chunk_cnt={"doc-1": 1}, boost=1
    )


def test_pair_converts_secondary_missing_to_typed_signal() -> None:
    secondary = MagicMock()
    secondary.update.side_effect = OpenSearchDocumentMissingError(["chunk-1"])
    pair, primary = _make_pair(secondary)

    with pytest.raises(SecondaryIndexDocumentMissingError) as exc:
        pair.update([_update_request()])

    assert exc.value.document_ids == ["doc-1"]
    primary.update.assert_called_once()  # PRESENT written before FUTURE
    assert secondary.update.call_args.kwargs.get("swallow_document_missing") is True


def test_pair_propagates_other_secondary_errors() -> None:
    secondary = MagicMock()
    secondary.update.side_effect = OpenSearchUpdateError("boom")
    pair, _primary = _make_pair(secondary)
    with pytest.raises(OpenSearchUpdateError):
        pair.update([_update_request()])


def test_pair_no_secondary_just_primary() -> None:
    pair, primary = _make_pair(None)
    pair.update([_update_request()])
    primary.update.assert_called_once()
