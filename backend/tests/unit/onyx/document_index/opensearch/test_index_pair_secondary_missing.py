"""Unit tests for the FUTURE-404 (secondary missing) conversion path.

Two pure-Python seams:
- `OpenSearchDocumentIndex.update` keeps processing requests past a missing-doc
  one and reports only the docs that were actually missing (chunk -> doc mapping).
- `OpenSearchIndexPair.update` lets PRESENT (primary) write, then converts a
  secondary `OpenSearchDocumentMissingError` into a typed
  `SecondaryIndexDocumentMissingError` carrying those doc ids.
The underlying 404/409 behavior is covered for real against a live cluster in
tests/external_dependency_unit/opensearch/test_opensearch_client.py.
"""

from unittest.mock import MagicMock

import pytest

from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import OpenSearchDocumentMissingError
from onyx.document_index.opensearch.client import OpenSearchUpdateError
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.opensearch_document_index import OpenSearchIndexPair
from onyx.document_index.opensearch.opensearch_document_index import (
    SecondaryIndexDocumentMissingError,
)
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


def _make_pair(secondary: object) -> tuple[OpenSearchIndexPair, MagicMock]:
    """Returns the pair plus the primary mock (asserting through the typed
    `_primary` attribute would confuse the type checker)."""
    pair = OpenSearchIndexPair.__new__(OpenSearchIndexPair)
    primary = MagicMock()
    pair._primary = primary
    pair._secondary = secondary
    return pair, primary


def _update_request(doc_id: str = "doc-1") -> MetadataUpdateRequest:
    return MetadataUpdateRequest(
        document_ids=[doc_id], doc_id_to_chunk_cnt={doc_id: 1}, boost=1
    )


def _make_index() -> tuple[OpenSearchDocumentIndex, TenantState, MagicMock]:
    """Returns the index, its tenant state, and the client mock (asserting
    through the typed `_client` attribute would confuse the type checker)."""
    ts = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
    idx = OpenSearchDocumentIndex.__new__(OpenSearchDocumentIndex)
    client = MagicMock()
    idx._client = client
    idx._tenant_state = ts
    idx._index_name = "test-index"
    return idx, ts, client


def test_update_continues_past_missing_and_attributes_precisely() -> None:
    """A missing doc in one request must not drop the others, and only the
    truly-missing doc is reported (not every doc in the batch)."""
    idx, ts, client = _make_index()
    missing_chunk = get_opensearch_doc_chunk_id(
        tenant_state=ts, document_id="doc-missing", chunk_index=0
    )
    client.bulk_update_documents.side_effect = [
        OpenSearchDocumentMissingError([missing_chunk]),
        None,
    ]

    with pytest.raises(OpenSearchDocumentMissingError) as exc:
        idx.update(
            [_update_request("doc-missing"), _update_request("doc-present")],
            swallow_document_missing=True,
        )

    assert exc.value.missing_document_ids == ["doc-missing"]
    assert exc.value.missing_chunk_ids == [missing_chunk]
    # the present doc's request was still attempted after the missing one
    assert client.bulk_update_documents.call_count == 2


def test_pair_converts_secondary_missing_to_typed_signal() -> None:
    secondary = MagicMock()
    secondary.update.side_effect = OpenSearchDocumentMissingError(
        ["chunk-1"], ["doc-1"]
    )
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
