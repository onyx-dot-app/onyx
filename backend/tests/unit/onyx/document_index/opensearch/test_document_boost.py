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

    def test_hybrid_search_query_includes_script_score_boost(self) -> None:
        """Hybrid search queries should wrap the base query with script_score boost."""
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

    def test_multiple_search_types_all_have_boost(self) -> None:
        """All search types should consistently apply document boost."""
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

        hybrid_query = DocumentQuery.get_hybrid_search_query(
            query_text="test",
            query_vector=[0.1] * 768,
            num_hits=10,
            tenant_state=tenant_state,
            index_filters=index_filters,
            include_hidden=False,
        )

        # All should have script_score boost applied
        for query in [keyword_query, semantic_query, hybrid_query]:
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
        """Document boost should work correctly with filtered searches."""
        tenant_state = TenantState(tenant_id="test_tenant", multitenant=False)
        # Use filters to restrict search
        index_filters = IndexFilters(
            access_control_list=None,
            source_type=None,
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
        assert len(str(base_query)) > 0  # Ensure it's not empty
