"""Pins how the `offset` param turns into `from` / `pagination_depth` in the
hybrid and keyword query bodies (pure DSL builders, no live OpenSearch)."""

import pytest

from onyx.context.search.models import IndexFilters
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.constants import (
    DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES,
)
from onyx.document_index.opensearch.constants import (
    DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW,
)
from onyx.document_index.opensearch.search import DocumentQuery
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

_TENANT_STATE = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
_FILTERS = IndexFilters(access_control_list=None)


def _hybrid_body(num_hits: int, offset: int = 0) -> dict:
    return DocumentQuery.get_hybrid_search_query(
        query_text="test query",
        query_vector=[0.1, 0.2, 0.3],
        num_hits=num_hits,
        tenant_state=_TENANT_STATE,
        index_filters=_FILTERS,
        include_hidden=False,
        offset=offset,
    )


def _keyword_body(num_hits: int, offset: int = 0) -> dict:
    return DocumentQuery.get_keyword_search_query(
        query_text="test query",
        num_hits=num_hits,
        tenant_state=_TENANT_STATE,
        index_filters=_FILTERS,
        include_hidden=False,
        offset=offset,
    )


def test_hybrid_no_offset_body_unchanged() -> None:
    body = _hybrid_body(num_hits=50)
    assert "from" not in body
    assert body["size"] == 50
    assert (
        body["query"]["hybrid"]["pagination_depth"]
        == DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES
    )


def test_hybrid_offset_sets_from_and_keeps_pagination_depth() -> None:
    body = _hybrid_body(num_hits=50, offset=50)
    assert body["from"] == 50
    assert body["size"] == 50
    # offset + num_hits is still within the default candidate pool.
    assert (
        body["query"]["hybrid"]["pagination_depth"]
        == DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES
    )


def test_hybrid_deep_offset_bumps_pagination_depth() -> None:
    offset = DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES + 200
    body = _hybrid_body(num_hits=50, offset=offset)
    # pagination_depth must cover the requested window.
    assert body["query"]["hybrid"]["pagination_depth"] == offset + 50


def test_hybrid_offset_beyond_max_window_raises() -> None:
    with pytest.raises(ValueError):
        _hybrid_body(num_hits=50, offset=DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW)


def test_keyword_no_offset_body_unchanged() -> None:
    body = _keyword_body(num_hits=50)
    assert "from" not in body
    assert body["size"] == 50


def test_keyword_offset_sets_from() -> None:
    body = _keyword_body(num_hits=50, offset=100)
    assert body["from"] == 100
    assert body["size"] == 50


def test_keyword_offset_beyond_max_window_raises() -> None:
    with pytest.raises(ValueError):
        _keyword_body(num_hits=50, offset=DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW)
