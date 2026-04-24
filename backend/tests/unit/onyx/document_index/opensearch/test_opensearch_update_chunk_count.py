from typing import cast
from unittest.mock import MagicMock

import pytest

from onyx.document_index.interfaces import VespaDocumentFields
from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.opensearch_document_index import (
    ChunkCountNotFoundError,
)
from onyx.document_index.opensearch.opensearch_document_index import ChunkCountZeroError
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchOldDocumentIndex,
)


def _make_real_index() -> OpenSearchDocumentIndex:
    index = OpenSearchDocumentIndex.__new__(OpenSearchDocumentIndex)
    index._index_name = "test_index"
    index._client = MagicMock()
    index._tenant_state = TenantState(tenant_id="test_tenant", multitenant=False)
    return index


def _make_old_index_wrapper() -> OpenSearchOldDocumentIndex:
    """Skips __init__ so we can plug in mocked inner indices directly."""
    wrapper = OpenSearchOldDocumentIndex.__new__(OpenSearchOldDocumentIndex)
    wrapper.index_name = "test_index"
    wrapper.secondary_index_name = None
    wrapper._real_index = MagicMock(spec=OpenSearchDocumentIndex)
    wrapper._secondary_real_index = None
    return wrapper


def test_update_raises_chunk_count_zero_error_when_count_is_zero() -> None:
    """``update()`` must raise ``ChunkCountZeroError`` (not a bare ``ValueError``)
    when a doc's chunk count is 0, so callers can treat the known-zero case
    distinctly from the unknown-count race."""
    index = _make_real_index()
    doc_id = "race-doc"
    request = MetadataUpdateRequest(
        document_ids=[doc_id],
        doc_id_to_chunk_cnt={doc_id: 0},
        hidden=True,
    )

    with pytest.raises(ChunkCountZeroError):
        index.update([request])

    # No per-chunk update attempted for this doc.
    client_mock = cast(MagicMock, index._client)
    client_mock.update_document.assert_not_called()


def test_chunk_count_zero_error_is_subclass_of_value_error() -> None:
    """``ChunkCountZeroError`` must remain a ``ValueError`` subclass so any
    broad ``except ValueError`` handlers still swallow it. It must also be
    distinct from ``ChunkCountNotFoundError`` (known-zero vs unknown)."""
    assert issubclass(ChunkCountZeroError, ValueError)
    assert not issubclass(ChunkCountZeroError, ChunkCountNotFoundError)
    assert not issubclass(ChunkCountNotFoundError, ChunkCountZeroError)


def test_update_single_swallows_chunk_count_zero_error() -> None:
    """``OpenSearchOldDocumentIndex.update_single`` must catch
    ``ChunkCountZeroError`` raised by the inner ``update()`` and return
    cleanly, matching the existing ``ChunkCountNotFoundError`` behaviour."""
    wrapper = _make_old_index_wrapper()
    real_index_mock = cast(MagicMock, wrapper._real_index)
    real_index_mock.update.side_effect = ChunkCountZeroError("race: chunk_count=0")

    # No exception should propagate out.
    wrapper.update_single(
        "race-doc",
        tenant_id="test_tenant",
        chunk_count=0,
        fields=VespaDocumentFields(hidden=True),
        user_fields=None,
    )

    real_index_mock.update.assert_called_once()
