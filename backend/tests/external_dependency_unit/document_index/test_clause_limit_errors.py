"""External dependency tests for oversized search queries: OpenSearch rejects
them under HTTP 400 or 500, the client classifies both as clause-limit errors
from the nested cause, and the analyzer term limits exclude them."""

import random
import string
import uuid
from collections.abc import Callable, Generator
from unittest.mock import MagicMock, patch

import pytest
from opensearchpy import TransportError

import onyx.document_index.opensearch.client as client_module
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.db.enums import VectorQuantization
from onyx.document_index.interfaces import KeywordTermCounts, TenantState
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    is_clause_limit_error,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.natural_language_processing.english_stopwords import strip_stopwords
from onyx.tools.tool_implementations.search.constants import (
    QUERY_MAX_DISTINCT_TERMS,
    QUERY_MAX_TERMS,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)

_TENANT_STATE = TenantState(
    tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
)
_FILTERS = IndexFilters(access_control_list=None)


def _distinct_words(count: int) -> str:
    rng = random.Random(count)
    return " ".join(
        "".join(rng.choices(string.ascii_lowercase, k=7)) for _ in range(count)
    )


@pytest.fixture(scope="module")
def document_index(
    tenant_context: None,  # noqa: ARG001
) -> Generator[OpenSearchDocumentIndex, None, None]:
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")
    index_name = f"test_clause_limit_{uuid.uuid4().hex[:8]}"
    index = OpenSearchDocumentIndex(
        tenant_state=_TENANT_STATE,
        index_name=index_name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=VectorQuantization.NONE,
    )
    client = OpenSearchIndexClient(index_name=index_name)
    try:
        index.verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
        index.index(
            chunks=[make_chunk("clause_limit_doc", content="rollback ownership")],
            indexing_metadata=make_indexing_metadata(
                ["clause_limit_doc"], old_counts=[0], new_counts=[1]
            ),
        )
        client.refresh_index()
        yield index
    finally:
        if client.index_exists():
            client.delete_index()


def _hybrid(index: OpenSearchDocumentIndex, query: str) -> None:
    index.hybrid_retrieval(
        query=query,
        query_embedding=[0.1] * EMBEDDING_DIM,
        final_keywords=strip_stopwords(query),
        query_type=QueryType.SEMANTIC,
        filters=_FILTERS,
        num_to_retrieve=10,
    )


def _keyword(index: OpenSearchDocumentIndex, query: str) -> None:
    index.keyword_retrieval(query=query, filters=_FILTERS, num_to_retrieve=10)


@pytest.mark.parametrize("search", [_hybrid, _keyword])
@pytest.mark.parametrize(
    ("word_count", "status_code"),
    # Nested clauses overflow first (HTTP 500); a larger query fails while
    # the query is built (HTTP 400).
    [(600, 500), (1_200, 400)],
)
def test_oversized_queries_are_clause_limit_errors(
    document_index: OpenSearchDocumentIndex,
    search: Callable[[OpenSearchDocumentIndex, str], None],
    word_count: int,
    status_code: int,
) -> None:
    record_error = MagicMock()
    with (
        patch.object(client_module, "record_opensearch_search_error", record_error),
        pytest.raises(TransportError) as raised,
    ):
        search(document_index, _distinct_words(word_count))

    assert raised.value.status_code == status_code
    assert is_clause_limit_error(raised.value)
    assert record_error.call_args.args[1] == "too_many_clauses"


@pytest.mark.parametrize("search", [_hybrid, _keyword])
def test_ordinary_query_is_not_rejected(
    document_index: OpenSearchDocumentIndex,
    search: Callable[[OpenSearchDocumentIndex, str], None],
) -> None:
    search(document_index, _distinct_words(300))


def test_other_search_errors_are_not_clause_limit_errors(
    document_index: OpenSearchDocumentIndex,  # noqa: ARG001
) -> None:
    client = OpenSearchIndexClient(index_name=f"missing_{uuid.uuid4().hex[:8]}")
    with pytest.raises(TransportError) as raised:
        client.search(body={"query": {"match_all": {}}}, search_pipeline_id=None)

    assert raised.value.status_code == 404
    assert not is_clause_limit_error(raised.value)


def test_error_without_a_body_is_not_a_clause_limit_error() -> None:
    assert not is_clause_limit_error(
        TransportError(500, "search_phase_execution_exception")
    )


def test_term_counts_use_the_hybrid_keyword_text(
    document_index: OpenSearchDocumentIndex,
) -> None:
    # Stopwords are dropped from the keyword text before analysis.
    assert document_index.count_keyword_terms(
        "the rollback of the rollback"
    ) == KeywordTermCounts(total=2, distinct=1)


@pytest.mark.parametrize("word_count", [600, 1_200])
def test_term_limits_exclude_queries_the_index_rejects(
    document_index: OpenSearchDocumentIndex, word_count: int
) -> None:
    query = _distinct_words(word_count)

    counts = document_index.count_keyword_terms(query)

    assert counts.distinct > QUERY_MAX_DISTINCT_TERMS
    with pytest.raises(TransportError) as raised:
        _hybrid(document_index, query)
    assert is_clause_limit_error(raised.value)


def test_term_limits_admit_queries_the_index_accepts(
    document_index: OpenSearchDocumentIndex,
) -> None:
    query = _distinct_words(300)

    counts = document_index.count_keyword_terms(query)

    assert counts.total <= QUERY_MAX_TERMS
    assert counts.distinct <= QUERY_MAX_DISTINCT_TERMS
    _hybrid(document_index, query)
