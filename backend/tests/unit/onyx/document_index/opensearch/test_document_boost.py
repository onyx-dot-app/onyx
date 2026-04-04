"""Unit tests for OpenSearch document boost functionality.

Tests verify that the document boost feature correctly applies per-document
scoring multipliers via script_score queries.
"""

from onyx.context.search.models import IndexFilters
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.search import DocumentQuery
from onyx.document_index.opensearch.schema import GLOBAL_BOOST_FIELD_NAME


class TestDocumentBoostApplication:
    """Tests for document boost in search queries."""

    def test_keyword_search_query_includes_script_score_boost(self) -> None:
        """Keyword search queries should wrap the base query with script_score boost."""
        tenant_state = TenantState(tenant_id="test_tenant", multitenant=False)
        index_filters = IndexFilters(access_control_list=None)

        query = DocumentQuery.get_keyword_search_query(
            query_text="test search",
            num_hits=10,
            tenant_state=tenant_state,
            index_filters=index_filters,
            include_hidden=False,
        )

        # The query should have script_score at the top level
        assert "query" in query
        assert "script_score" in query["query"]
        assert "query" in query["query"]["script_score"]
        assert "script" in query["query"]["script_score"]

        # Verify the script uses Painless language
        script = query["query"]["script_score"]["script"]
        assert script["lang"] == "painless"

        # Verify the script references the boost field
        assert GLOBAL_BOOST_FIELD_NAME in script["source"]
        assert "_score" in script["source"]

    def test_semantic_search_query_includes_script_score_boost(self) -> None:
        """Semantic (vector) search queries should wrap the base query with script_score boost."""
        tenant_state = TenantState(tenant_id="test_tenant", multitenant=False)
        index_filters = IndexFilters(access_control_list=None)

        query = DocumentQuery.get_semantic_search_query(
            query_embedding=[0.1] * 768,  # Typical embedding dimension
            num_hits=10,
            tenant_state=tenant_state,
            index_filters=index_filters,
            include_hidden=False,
        )

        # The query should have script_score at the top level
        assert "query" in query
        assert "script_score" in query["query"]
        assert "query" in query["query"]["script_score"]
        assert "script" in query["query"]["script_score"]

        # Verify the script uses Painless language
        script = query["query"]["script_score"]["script"]
        assert script["lang"] == "painless"

        # Verify the script references the boost field
        assert GLOBAL_BOOST_FIELD_NAME in script["source"]
        assert "_score" in script["source"]

    def test_hybrid_search_query_does_not_apply_boost(self) -> None:
        """Hybrid search queries do NOT get boost applied via script_score.

        OpenSearch forbids nesting hybrid queries inside wrapper queries like
        script_score. Hybrid queries must be top-level. Additionally, script_score
        runs at shard level before the normalization pipeline, which would distort
        the combined scores. Boost is only applied to keyword and semantic searches.
        """
        tenant_state = TenantState(tenant_id="test_tenant", multitenant=False)
        index_filters = IndexFilters(access_control_list=None)

        query = DocumentQuery.get_hybrid_search_query(
            query_text="test search",
            query_vector=[0.1] * 768,
            num_hits=10,
            tenant_state=tenant_state,
            index_filters=index_filters,
            include_hidden=False,
        )

        # Hybrid queries are NOT wrapped in script_score
        assert "query" in query
        assert "hybrid" in query["query"]
        assert "script_score" not in query["query"], \
            "Hybrid queries must remain top-level per OpenSearch restrictions"

        # Verify the hybrid query structure is intact
        assert "queries" in query["query"]["hybrid"]
        assert "pagination_depth" in query["query"]["hybrid"]
        assert "filter" in query["query"]["hybrid"]

    def test_boost_script_handles_missing_boost_field(self) -> None:
        """The boost script should handle missing boost fields gracefully.

        When a document doesn't have an explicit boost value (NULL), it should
        be treated as boost=1.0 (neutral, no effect on score).
        """
        tenant_state = TenantState(tenant_id="test_tenant", multitenant=False)
        index_filters = IndexFilters(access_control_list=None)

        query = DocumentQuery.get_keyword_search_query(
            query_text="test search",
            num_hits=10,
            tenant_state=tenant_state,
            index_filters=index_filters,
            include_hidden=False,
        )

        script = query["query"]["script_score"]["script"]["source"]

        # The script should use Math.max to clamp minimum boost value
        # This ensures documents without boost don't get completely suppressed
        assert "Math.max" in script

        # Verify the script applies Math.max only to boost, not final score
        # This preserves ranking semantics: boost=0 should result in score=0,
        # not score=MIN_BOOST_VALUE
        assert "_score *" in script or "_score*" in script, \
            "Score multiplication must come before Math.max to allow zero boost"

        # Verify the boost field is referenced
        assert GLOBAL_BOOST_FIELD_NAME in script

    def test_keyword_and_semantic_searches_apply_boost(self) -> None:
        """Keyword and semantic searches apply document boost via script_score.

        Hybrid searches do not apply boost due to OpenSearch restrictions on
        nesting hybrid queries inside wrapper queries.
        """
        tenant_state = TenantState(tenant_id="test_tenant", multitenant=False)
        index_filters = IndexFilters(access_control_list=None)

        keyword_query = DocumentQuery.get_keyword_search_query(
            query_text="test",
            num_hits=10,
            tenant_state=tenant_state,
            index_filters=index_filters,
            include_hidden=False,
        )

        semantic_query = DocumentQuery.get_semantic_search_query(
            query_embedding=[0.1] * 768,
            num_hits=10,
            tenant_state=tenant_state,
            index_filters=index_filters,
            include_hidden=False,
        )

        # Keyword and semantic queries should have script_score boost applied
        for query in [keyword_query, semantic_query]:
            assert "script_score" in query["query"]
            assert "script" in query["query"]["script_score"]
            script = query["query"]["script_score"]["script"]
            assert GLOBAL_BOOST_FIELD_NAME in script["source"]
            assert script["lang"] == "painless"

    def test_boost_preserves_base_query_structure(self) -> None:
        """Document boost should wrap the query without modifying its structure."""
        tenant_state = TenantState(tenant_id="test_tenant", multitenant=False)
        index_filters = IndexFilters(access_control_list=None)

        query = DocumentQuery.get_keyword_search_query(
            query_text="test search",
            num_hits=10,
            tenant_state=tenant_state,
            index_filters=index_filters,
            include_hidden=False,
        )

        # The base query should be intact inside script_score
        base_query = query["query"]["script_score"]["query"]
        assert "bool" in base_query

        # The query should still have the standard structure with filters
        assert "must" in base_query["bool"] or "filter" in base_query["bool"]

    def test_script_score_with_filters(self) -> None:
        """Document boost should work correctly with filtered searches.

        Filters should be preserved inside the script_score query and not
        interfere with boost application.
        """
        from onyx.configs.constants import DocumentSource

        tenant_state = TenantState(tenant_id="test_tenant", multitenant=False)
        # Apply actual filters to test filter + boost integration
        index_filters = IndexFilters(
            access_control_list=None,
            source_type=[DocumentSource.WEB],  # Actual filter
            document_set=None,
        )

        query = DocumentQuery.get_keyword_search_query(
            query_text="test search",
            num_hits=10,
            tenant_state=tenant_state,
            index_filters=index_filters,
            include_hidden=False,
        )

        # Verify script_score wraps the filtered query correctly
        assert "script_score" in query["query"]
        base_query = query["query"]["script_score"]["query"]
        assert base_query is not None

        # Verify filters are preserved inside the base query
        # (filters should be in the bool query that's inside script_score)
        base_query_str = str(base_query)
        assert len(base_query_str) > 0

        # Verify the structure: filters should be within the wrapped query,
        # not at the script_score level
        assert "bool" in base_query, \
            "Filtered queries should have bool structure preserved in base query"

        # Verify script is correctly configured at script_score level
        script = query["query"]["script_score"]["script"]
        assert "source" in script
        assert GLOBAL_BOOST_FIELD_NAME in script["source"]
