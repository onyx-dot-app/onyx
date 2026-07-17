"""Unit tests for the missing-doc (404) conversion paths.

Pure-Python seams:
- `OpenSearchDocumentIndex.update` keeps processing requests past a missing-doc
  one and reports only the docs that were actually missing (chunk -> doc mapping).
- `OpenSearchIndexPair.update` lets PRESENT (primary) write, then converts a
  secondary `OpenSearchDocumentMissingError` into a typed
  `SecondaryIndexDocumentMissingError` carrying those doc ids.
- With `primary_backfill_in_progress` (INSTANT reindex-port post-swap), the pair
  also surfaces a doc missing from the *primary* as that same typed signal, so the
  caller defers instead of clearing needs_sync and letting the create-only port
  reinstall a stale ACL.
The underlying 404/409 behavior is covered for real against a live cluster in
tests/external_dependency_unit/opensearch/test_opensearch_client.py.
"""

from unittest.mock import MagicMock

import pytest

from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.document_index.interfaces_new import SecondaryIndexDocumentMissingError
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import OpenSearchDocumentMissingError
from onyx.document_index.opensearch.client import OpenSearchUpdateError
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.opensearch_document_index import OpenSearchIndexPair
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


def _make_pair(
    secondary: object, primary_backfill_in_progress: bool = False
) -> tuple[OpenSearchIndexPair, MagicMock]:
    """Returns the pair plus the primary mock (asserting through the typed
    `_primary` attribute would confuse the type checker)."""
    pair = OpenSearchIndexPair.__new__(OpenSearchIndexPair)
    primary = MagicMock()
    pair._primary = primary
    pair._secondary = secondary
    pair._primary_backfill_in_progress = primary_backfill_in_progress
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
            surface_document_missing=True,
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
    assert secondary.update.call_args.kwargs.get("surface_document_missing") is True


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
    # Not a backfill target: primary write must NOT surface missing docs.
    assert primary.update.call_args.kwargs.get("surface_document_missing") is not True


def test_pair_surfaces_primary_missing_during_instant_backfill() -> None:
    """INSTANT post-swap: the now-live primary is still being backfilled by the port.
    A not-yet-copied doc is missing from primary; the pair must surface it as the same
    typed signal so the caller defers instead of clearing needs_sync (which would let
    the create-only port reinstall a stale ACL)."""
    pair, primary = _make_pair(None, primary_backfill_in_progress=True)
    primary.update.side_effect = OpenSearchDocumentMissingError(["chunk-1"], ["doc-1"])

    with pytest.raises(SecondaryIndexDocumentMissingError) as exc:
        pair.update([_update_request()])

    assert exc.value.document_ids == ["doc-1"]
    assert primary.update.call_args.kwargs.get("surface_document_missing") is True


def test_pair_backfill_flag_off_does_not_surface_primary_missing() -> None:
    """With the backfill flag off, primary writes the legacy way (missing docs are
    silently ignored, no typed signal) — steady-state behavior is unchanged."""
    pair, primary = _make_pair(None, primary_backfill_in_progress=False)
    pair.update([_update_request()])
    primary.update.assert_called_once()
    assert primary.update.call_args.kwargs.get("surface_document_missing") is not True
