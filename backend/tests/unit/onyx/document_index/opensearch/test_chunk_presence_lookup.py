"""Unit tests for the pre-swap chunk-presence lookup.

The lookup goes through mget rather than a search so that a chunk written but not
yet refreshed still counts as present.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id

_TENANT_STATE = TenantState(tenant_id="public", multitenant=False)


def _make_index(found_chunk_ids: set[str]) -> tuple[OpenSearchDocumentIndex, MagicMock]:
    index = OpenSearchDocumentIndex.__new__(OpenSearchDocumentIndex)
    index._index_name = "test_index"
    index._tenant_state = _TENANT_STATE

    client = MagicMock()
    client.get_existing_chunk_ids.side_effect = lambda chunk_ids: {
        chunk_id for chunk_id in chunk_ids if chunk_id in found_chunk_ids
    }
    index._client = client
    return index, client


def _first_chunk_id(document_id: str) -> str:
    return get_opensearch_doc_chunk_id(
        tenant_state=_TENANT_STATE, document_id=document_id, chunk_index=0
    )


def test_no_documents_skips_the_lookup() -> None:
    index, client = _make_index(set())
    assert index.get_documents_missing_chunks([]) == []
    client.get_existing_chunk_ids.assert_not_called()


def test_all_documents_present() -> None:
    document_ids = ["doc-a", "doc-b", "doc-c"]
    index, _ = _make_index({_first_chunk_id(d) for d in document_ids})
    assert index.get_documents_missing_chunks(document_ids) == []


def test_missing_documents_reported_in_input_order() -> None:
    index, _ = _make_index({_first_chunk_id("doc-b")})
    assert index.get_documents_missing_chunks(["doc-a", "doc-b", "doc-c"]) == [
        "doc-a",
        "doc-c",
    ]


def test_duplicate_document_ids_are_looked_up_once() -> None:
    index, client = _make_index(set())
    assert index.get_documents_missing_chunks(["doc-a", "doc-a", "doc-b"]) == [
        "doc-a",
        "doc-b",
    ]
    (looked_up,), _ = client.get_existing_chunk_ids.call_args
    assert sorted(looked_up) == sorted(
        [_first_chunk_id("doc-a"), _first_chunk_id("doc-b")]
    )


def test_any_chunk_lookup_sees_a_document_whose_first_chunk_is_gone() -> None:
    """The two lookups have to disagree here, or excusing a document on the cheaper one
    would wave a real loss through."""
    index = OpenSearchDocumentIndex.__new__(OpenSearchDocumentIndex)
    index._index_name = "test_index"
    index._tenant_state = _TENANT_STATE

    client = MagicMock()
    client.get_existing_chunk_ids.side_effect = lambda _ids: set()
    client.iter_chunks_for_doc_ids.side_effect = lambda *_: iter(
        [[SimpleNamespace(document_id="doc-a", chunk_index=3)]]
    )
    index._client = client

    assert index.get_documents_missing_chunks(["doc-a"]) == ["doc-a"]
    assert index.get_documents_with_any_chunk(["doc-a"]) == {"doc-a"}


def test_any_chunk_lookup_refreshes_before_it_scans() -> None:
    """A search cannot see an unrefreshed write, and this answer is used to excuse a
    document, so a stale absence would wave a real loss through."""
    index = OpenSearchDocumentIndex.__new__(OpenSearchDocumentIndex)
    index._index_name = "test_index"
    index._tenant_state = _TENANT_STATE

    calls: list[str] = []
    client = MagicMock()
    client.refresh_index.side_effect = lambda: calls.append("refresh")
    client.iter_chunks_for_doc_ids.side_effect = lambda *_: (
        calls.append("scan"),
        iter([]),
    )[1]
    index._client = client

    index.get_documents_with_any_chunk(["doc-a"])
    assert calls == ["refresh", "scan"]


def test_any_chunk_lookup_skips_the_refresh_when_asked_nothing() -> None:
    index = OpenSearchDocumentIndex.__new__(OpenSearchDocumentIndex)
    index._index_name = "test_index"
    index._tenant_state = _TENANT_STATE
    client = MagicMock()
    index._client = client

    assert index.get_documents_with_any_chunk([]) == set()
    client.refresh_index.assert_not_called()


def _make_client_with_mget(present_ids: set[str]) -> Any:
    """A real client with only its transport stubbed, so the batching loop still runs."""
    from onyx.document_index.opensearch.client import OpenSearchIndexClient

    client = OpenSearchIndexClient.__new__(OpenSearchIndexClient)
    client._index_name = "test_index"

    transport = MagicMock()
    transport.mget.side_effect = lambda body, **_: {
        "docs": [
            {"_id": chunk_id, "found": chunk_id in present_ids}
            for chunk_id in body["ids"]
        ]
    }
    client._client = transport
    return client


def test_get_existing_chunk_ids_returns_only_found() -> None:
    client = _make_client_with_mget({"a", "c"})
    assert client.get_existing_chunk_ids(["a", "b", "c"]) == {"a", "c"}


def test_get_existing_chunk_ids_batches_large_inputs() -> None:
    chunk_ids = [f"chunk-{i}" for i in range(1200)]
    client = _make_client_with_mget(set(chunk_ids))
    assert client.get_existing_chunk_ids(chunk_ids) == set(chunk_ids)
    assert client._client.mget.call_count == 3


def test_get_existing_chunk_ids_empty_input_makes_no_request() -> None:
    client = _make_client_with_mget(set())
    assert client.get_existing_chunk_ids([]) == set()
    client._client.mget.assert_not_called()
