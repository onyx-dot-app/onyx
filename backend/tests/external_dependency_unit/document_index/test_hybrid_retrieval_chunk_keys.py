"""External dependency tests for hybrid retrieval that reads only chunk keys.

Hybrid retrieval first runs the hybrid query with doc values only, then fetches
the source of the top hits. These tests check that it returns the same chunks,
order and scores as one hybrid query that returns the source, and that the
source fetch applies the search filters again.
"""

import random
import uuid
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.access.models import DocumentAccess
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters, InferenceChunk
from onyx.db.enums import VectorQuantization
from onyx.document_index.interfaces import TenantState
from onyx.document_index.opensearch import opensearch_document_index, schema, search
from onyx.document_index.opensearch.client import (
    ChunkKeySearchHit,
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.indexing.models import ChunkEmbedding, DocMetadataAwareIndexChunk
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)

_NUM_DOCS = 12
_CHUNKS_PER_DOC = 3
_NUM_HITS = 10
_WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
# The unpatched method, for a spy that wraps it.
_SEARCH_FOR_CHUNK_KEYS = OpenSearchIndexClient.search_for_chunk_keys


def _make_chunk(
    doc_id: str, chunk_index: int, rng: random.Random
) -> DocMetadataAwareIndexChunk:
    """Returns a public chunk with random words and a random embedding."""
    content = " ".join(rng.choice(_WORDS) for _ in range(8))
    return make_chunk(doc_id, chunk_id=chunk_index, content=content).model_copy(
        update={
            "embeddings": ChunkEmbedding(
                full_embedding=[rng.gauss(0.0, 1.0) for _ in range(EMBEDDING_DIM)],
                mini_chunk_embeddings=[],
            ),
        }
    )


def _query_embedding() -> list[float]:
    """Returns the same random query embedding on every call."""
    rng = random.Random(11)
    return [rng.gauss(0.0, 1.0) for _ in range(EMBEDDING_DIM)]


def _hybrid_retrieval(
    document_index: OpenSearchDocumentIndex, query_embedding: list[float]
) -> list[InferenceChunk]:
    """Runs a public hybrid retrieval that matches part of the chunk words."""
    return document_index.hybrid_retrieval(
        query="alpha bravo",
        query_embedding=query_embedding,
        final_keywords=None,
        query_type=QueryType.SEMANTIC,
        filters=IndexFilters(
            access_control_list=[PUBLIC_DOC_PAT],
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        ),
        num_to_retrieve=_NUM_HITS,
    )


@contextmanager
def _search_settings(
    highlights_disabled: bool, explain_enabled: bool
) -> Generator[None, None, None]:
    """Sets the highlight and explain settings in every module that reads them."""
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                search, "OPENSEARCH_MATCH_HIGHLIGHTS_DISABLED", highlights_disabled
            )
        )
        for module in (opensearch_document_index, search):
            stack.enter_context(
                patch.object(module, "OPENSEARCH_EXPLAIN_ENABLED", explain_enabled)
            )
        yield


@contextmanager
def _single_request_path() -> Generator[None, None, None]:
    """Makes hybrid retrieval send one request, as before the keys-only path."""
    with patch.object(OpenSearchIndexClient, "get_number_of_shards", return_value=2):
        yield


@contextmanager
def _spy_on_searches() -> Generator[MagicMock, None, None]:
    """Records the body of every search request; the real requests still run."""
    with patch.object(
        OpenSearchIndexClient,
        "_run_search",
        autospec=True,
        side_effect=OpenSearchIndexClient._run_search,
    ) as search_spy:
        yield search_spy


@contextmanager
def _index_of_public_chunks(
    number_of_shards: int,
) -> Generator[OpenSearchDocumentIndex, None, None]:
    """Creates an index of public chunks and deletes it afterwards."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    index_name = f"test_hybrid_chunk_keys_{uuid.uuid4().hex[:8]}"
    document_index = OpenSearchDocumentIndex(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        index_name=index_name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=VectorQuantization.NONE,
    )
    with OpenSearchIndexClient(index_name=index_name) as client:
        try:
            with patch.object(schema, "OPENSEARCH_INDEX_NUM_SHARDS", number_of_shards):
                document_index.verify_and_create_index_if_necessary(
                    embedding_dim=EMBEDDING_DIM,
                )
            rng = random.Random(7)
            doc_ids = [f"chunk_keys_doc_{i}" for i in range(_NUM_DOCS)]
            document_index.index(
                chunks=[
                    _make_chunk(doc_id, chunk_index, rng)
                    for doc_id in doc_ids
                    for chunk_index in range(_CHUNKS_PER_DOC)
                ],
                indexing_metadata=make_indexing_metadata(
                    doc_ids,
                    old_counts=[0] * _NUM_DOCS,
                    new_counts=[_CHUNKS_PER_DOC] * _NUM_DOCS,
                ),
            )
            client.refresh_index()
            yield document_index
        finally:
            client.delete_index()


@pytest.fixture
def document_index(
    tenant_context: None,  # noqa: ARG001
) -> Generator[OpenSearchDocumentIndex, None, None]:
    """A single-shard index of public chunks."""
    with _index_of_public_chunks(number_of_shards=1) as document_index:
        yield document_index


@pytest.mark.parametrize("highlights_disabled", [True, False])
def test_hybrid_retrieval_by_chunk_keys_matches_single_request(
    document_index: OpenSearchDocumentIndex,
    highlights_disabled: bool,
) -> None:
    query_embedding = _query_embedding()

    with (
        _search_settings(
            highlights_disabled=highlights_disabled, explain_enabled=False
        ),
        _spy_on_searches() as search_spy,
    ):
        chunk_keys_results = _hybrid_retrieval(document_index, query_embedding)
    # The hybrid query reads no stored fields; the second request fetches and
    # highlights only the top hits.
    hybrid_body, fetch_body = (
        search_call.kwargs["body"] for search_call in search_spy.call_args_list
    )
    assert hybrid_body["stored_fields"] == "_none_"
    assert "_source" not in hybrid_body
    assert "highlight" not in hybrid_body
    assert fetch_body["size"] == _NUM_HITS
    assert ("highlight" in fetch_body) is not highlights_disabled
    hybrid_call, fetch_call = search_spy.call_args_list
    assert hybrid_call.kwargs["preference"] is not None
    assert fetch_call.kwargs["preference"] == hybrid_call.kwargs["preference"]

    with (
        _search_settings(
            highlights_disabled=highlights_disabled, explain_enabled=False
        ),
        _single_request_path(),
        _spy_on_searches() as search_spy,
    ):
        single_request_results = _hybrid_retrieval(document_index, query_embedding)
    assert search_spy.call_count == 1

    assert len(chunk_keys_results) == _NUM_HITS
    assert [
        (
            chunk.document_id,
            chunk.chunk_id,
            chunk.score,
            chunk.content,
            chunk.match_highlights,
        )
        for chunk in chunk_keys_results
    ] == [
        (
            chunk.document_id,
            chunk.chunk_id,
            chunk.score,
            chunk.content,
            chunk.match_highlights,
        )
        for chunk in single_request_results
    ]
    # The query words occur in the chunks, so the comparison covers highlights.
    assert any(chunk.match_highlights for chunk in chunk_keys_results) is not (
        highlights_disabled
    )


def test_explain_keeps_single_request(
    document_index: OpenSearchDocumentIndex,
) -> None:
    """Explain describes the hybrid scoring, so it needs the one hybrid request."""
    query_embedding = _query_embedding()
    with (
        _search_settings(highlights_disabled=True, explain_enabled=True),
        _spy_on_searches() as search_spy,
    ):
        results = _hybrid_retrieval(document_index, query_embedding)
    assert len(results) == _NUM_HITS
    assert search_spy.call_count == 1
    explain_body: dict[str, Any] = search_spy.call_args.kwargs["body"]
    assert explain_body["explain"] is True
    assert "stored_fields" not in explain_body


def test_source_fetch_drops_document_made_private_after_hybrid_search(
    document_index: OpenSearchDocumentIndex,
) -> None:
    """A document whose access changes between the two requests is not returned."""
    query_embedding = _query_embedding()
    made_private: list[ChunkKeySearchHit] = []
    all_hits: list[ChunkKeySearchHit] = []

    def search_then_make_top_document_private(
        client: OpenSearchIndexClient, *args: Any, **kwargs: Any
    ) -> list[ChunkKeySearchHit]:
        chunk_key_hits = _SEARCH_FOR_CHUNK_KEYS(client, *args, **kwargs)
        top_hit = chunk_key_hits[0]
        private_chunk = make_chunk(
            top_hit.document_id,
            chunk_id=top_hit.chunk_index,
            content="private replacement",
        ).model_copy(
            update={
                "access": DocumentAccess.build(
                    user_emails=["someone_else@example.com"],
                    user_groups=[],
                    external_user_emails=[],
                    external_user_group_ids=[],
                    is_public=False,
                )
            }
        )
        document_index.index(
            chunks=[private_chunk],
            indexing_metadata=make_indexing_metadata(
                [top_hit.document_id],
                old_counts=[_CHUNKS_PER_DOC],
                new_counts=[_CHUNKS_PER_DOC],
            ),
        )
        client.refresh_index()
        made_private.append(top_hit)
        all_hits.extend(chunk_key_hits)
        return chunk_key_hits

    with (
        _search_settings(highlights_disabled=True, explain_enabled=False),
        patch.object(
            OpenSearchIndexClient,
            "search_for_chunk_keys",
            autospec=True,
            side_effect=search_then_make_top_document_private,
        ),
    ):
        results = _hybrid_retrieval(document_index, query_embedding)

    (private_hit,) = made_private
    # Access is set per document, so every chunk of that document is now
    # private. The other hits keep their hybrid order.
    expected_keys = [
        (hit.document_id, hit.chunk_index)
        for hit in all_hits
        if hit.document_id != private_hit.document_id
    ]
    assert len(expected_keys) < _NUM_HITS
    assert [(chunk.document_id, chunk.chunk_id) for chunk in results] == expected_keys


def test_multi_shard_index_keeps_single_request(
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A multi-shard search already fetches only the top hits."""
    query_embedding = _query_embedding()
    with (
        _index_of_public_chunks(number_of_shards=2) as document_index,
        _search_settings(highlights_disabled=True, explain_enabled=False),
        _spy_on_searches() as search_spy,
    ):
        results = _hybrid_retrieval(document_index, query_embedding)

    assert len(results) == _NUM_HITS
    hybrid_calls = [
        search_call
        for search_call in search_spy.call_args_list
        if "hybrid" in search_call.kwargs["body"]["query"]
    ]
    assert len(hybrid_calls) == 1
    assert search_spy.call_count == 1
    assert "stored_fields" not in hybrid_calls[0].kwargs["body"]


def test_source_fetch_is_split_into_batches(
    document_index: OpenSearchDocumentIndex,
) -> None:
    """Large result sets are fetched in batches that keep the order."""
    query_embedding = _query_embedding()
    with _search_settings(highlights_disabled=True, explain_enabled=False):
        with _spy_on_searches() as search_spy:
            one_fetch_results = _hybrid_retrieval(document_index, query_embedding)
        assert search_spy.call_count == 2

        with (
            patch.object(opensearch_document_index, "_MAX_CHUNK_KEYS_PER_FETCH", 3),
            _spy_on_searches() as search_spy,
        ):
            batched_results = _hybrid_retrieval(document_index, query_embedding)
    # One hybrid request, then ceil(10 / 3) fetches.
    assert search_spy.call_count == 1 + 4
    assert [
        (chunk.document_id, chunk.chunk_id, chunk.score) for chunk in batched_results
    ] == [
        (chunk.document_id, chunk.chunk_id, chunk.score) for chunk in one_fetch_results
    ]


def test_shard_count_failure_uses_single_request(
    document_index: OpenSearchDocumentIndex,
) -> None:
    """Search still works when the shard count cannot be read."""
    with (
        _search_settings(highlights_disabled=True, explain_enabled=False),
        patch.object(
            OpenSearchIndexClient,
            "get_number_of_shards",
            side_effect=RuntimeError("settings unavailable"),
        ),
        _spy_on_searches() as search_spy,
    ):
        results = _hybrid_retrieval(document_index, _query_embedding())
    assert len(results) == _NUM_HITS
    assert search_spy.call_count == 1


def test_recreated_index_reads_its_new_shard_count(
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Deleting and creating an index clears its cached shard count."""
    with _index_of_public_chunks(number_of_shards=1) as document_index:
        index_name = document_index._index_name
        with OpenSearchIndexClient(index_name=index_name) as client:
            assert client.get_number_of_shards() == 1
            client.delete_index()
            with patch.object(schema, "OPENSEARCH_INDEX_NUM_SHARDS", 2):
                document_index.verify_and_create_index_if_necessary(
                    embedding_dim=EMBEDDING_DIM,
                )
            assert client.get_number_of_shards() == 2
