"""Unit tests for search utility functions."""

from typing import NamedTuple

import pytest

from onyx.tools.tool_implementations.search.search_tool import deduplicate_queries
from onyx.tools.tool_implementations.search.search_utils import (
    weighted_reciprocal_rank_fusion,
)


# =============================================================================
# Test Data Structures
# =============================================================================


class MockDocument(NamedTuple):
    """Mock document for testing RRF."""

    document_id: str
    content: str


# =============================================================================
# Tests for weighted_reciprocal_rank_fusion
# =============================================================================


class TestWeightedReciprocalRankFusion:
    """Test suite for weighted_reciprocal_rank_fusion function."""

    def test_single_result_list(self) -> None:
        """Test RRF with a single result list."""
        doc_a = MockDocument("doc_a", "Content A")
        doc_b = MockDocument("doc_b", "Content B")
        doc_c = MockDocument("doc_c", "Content C")

        ranked_results = [[doc_a, doc_b, doc_c]]
        weights = [1.0]

        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
        )

        # With a single list, order should be preserved
        assert len(result) == 3
        assert result[0].document_id == "doc_a"
        assert result[1].document_id == "doc_b"
        assert result[2].document_id == "doc_c"

    def test_two_identical_lists_equal_weights(self) -> None:
        """Test RRF with two identical lists and equal weights."""
        doc_a = MockDocument("doc_a", "Content A")
        doc_b = MockDocument("doc_b", "Content B")
        doc_c = MockDocument("doc_c", "Content C")

        ranked_results = [
            [doc_a, doc_b, doc_c],
            [doc_a, doc_b, doc_c],
        ]
        weights = [1.0, 1.0]

        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
        )

        # Order should be preserved, but items appear only once
        assert len(result) == 3
        assert result[0].document_id == "doc_a"
        assert result[1].document_id == "doc_b"
        assert result[2].document_id == "doc_c"

    def test_two_different_lists_equal_weights(self) -> None:
        """Test RRF with different result lists and equal weights."""
        doc_a = MockDocument("doc_a", "Content A")
        doc_b = MockDocument("doc_b", "Content B")
        doc_c = MockDocument("doc_c", "Content C")
        doc_d = MockDocument("doc_d", "Content D")

        ranked_results = [
            [doc_a, doc_b, doc_c],
            [doc_c, doc_a, doc_d],
        ]
        weights = [1.0, 1.0]

        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
        )

        # doc_a and doc_c should rank highest (appear in both lists)
        assert len(result) == 4
        # doc_a appears at rank 1 and 2 in the two lists
        # doc_c appears at rank 3 and 1 in the two lists
        # Both should be at top, exact order depends on tiebreaking
        top_two_ids = {result[0].document_id, result[1].document_id}
        assert top_two_ids == {"doc_a", "doc_c"}

    def test_weighted_lists_higher_weight_dominates(self) -> None:
        """Test that higher weighted list influences ranking more."""
        doc_a = MockDocument("doc_a", "Content A")
        doc_b = MockDocument("doc_b", "Content B")
        doc_c = MockDocument("doc_c", "Content C")

        # First list has higher weight
        ranked_results = [
            [doc_a, doc_b],  # weight 2.0
            [doc_c, doc_a],  # weight 1.0
        ]
        weights = [2.0, 1.0]

        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
        )

        # doc_a should be first (rank 1 in list 1 with weight 2.0, rank 2 in list 2 with weight 1.0)
        # RRF score for doc_a: 2.0/(50+1) + 1.0/(50+2) = 2.0/51 + 1.0/52 = 0.0392 + 0.0192 = 0.0584
        # RRF score for doc_b: 2.0/(50+2) = 2.0/52 = 0.0385
        # RRF score for doc_c: 1.0/(50+1) = 1.0/51 = 0.0196
        assert len(result) == 3
        assert result[0].document_id == "doc_a"
        assert result[1].document_id == "doc_b"
        assert result[2].document_id == "doc_c"

    def test_empty_result_list(self) -> None:
        """Test RRF with empty result list."""
        ranked_results: list[list[MockDocument]] = [[]]
        weights = [1.0]

        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
        )

        assert len(result) == 0

    def test_multiple_empty_lists(self) -> None:
        """Test RRF with multiple empty result lists."""
        ranked_results: list[list[MockDocument]] = [[], [], []]
        weights = [1.0, 1.0, 1.0]

        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
        )

        assert len(result) == 0

    def test_mixed_empty_and_non_empty_lists(self) -> None:
        """Test RRF with mix of empty and non-empty lists."""
        doc_a = MockDocument("doc_a", "Content A")
        doc_b = MockDocument("doc_b", "Content B")

        ranked_results = [
            [],
            [doc_a, doc_b],
            [],
        ]
        weights = [1.0, 1.0, 1.0]

        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
        )

        assert len(result) == 2
        assert result[0].document_id == "doc_a"
        assert result[1].document_id == "doc_b"

    def test_mismatched_weights_raises_error(self) -> None:
        """Test that mismatched weights and results raises ValueError."""
        doc_a = MockDocument("doc_a", "Content A")

        ranked_results = [[doc_a]]
        weights = [1.0, 2.0]  # Too many weights

        with pytest.raises(ValueError, match="must match"):
            weighted_reciprocal_rank_fusion(
                ranked_results=ranked_results,
                weights=weights,
                id_extractor=lambda doc: doc.document_id,
            )

    def test_custom_k_value(self) -> None:
        """Test RRF with custom k value."""
        doc_a = MockDocument("doc_a", "Content A")
        doc_b = MockDocument("doc_b", "Content B")

        ranked_results = [[doc_a, doc_b]]
        weights = [1.0]

        # With k=10, scores should be: 1/(10+1)=0.091, 1/(10+2)=0.083
        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
            k=10,
        )

        assert len(result) == 2
        assert result[0].document_id == "doc_a"
        assert result[1].document_id == "doc_b"

    def test_deduplication_preserves_first_occurrence(self) -> None:
        """Test that when same document appears in multiple lists, first occurrence is used."""
        doc_a1 = MockDocument("doc_a", "Content A - First")
        doc_a2 = MockDocument("doc_a", "Content A - Second")
        doc_b = MockDocument("doc_b", "Content B")

        ranked_results = [
            [doc_a1, doc_b],
            [doc_a2],  # Same ID as doc_a1
        ]
        weights = [1.0, 1.0]

        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
        )

        # Should use first occurrence of doc_a
        assert len(result) == 2
        doc_a_result = next(doc for doc in result if doc.document_id == "doc_a")
        assert doc_a_result.content == "Content A - First"

    def test_realistic_semantic_vs_keyword_search_scenario(self) -> None:
        """Test realistic scenario: semantic search vs keyword search with different weights."""
        # Semantic search results
        doc_a = MockDocument("doc_a", "Semantic Result A")
        doc_b = MockDocument("doc_b", "Semantic Result B")
        doc_c = MockDocument("doc_c", "Semantic Result C")

        # Keyword search results (doc_c ranks first, doc_a also appears)
        doc_d = MockDocument("doc_d", "Keyword Result D")

        ranked_results = [
            [doc_a, doc_b, doc_c],  # Semantic: weight 1.2
            [doc_c, doc_a, doc_d],  # Keyword: weight 1.0
        ]
        weights = [1.2, 1.0]

        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
        )

        # doc_a and doc_c appear in both lists and should rank highest
        assert len(result) == 4
        top_two_ids = {result[0].document_id, result[1].document_id}
        assert top_two_ids == {"doc_a", "doc_c"}

    def test_many_lists_with_varying_weights(self) -> None:
        """Test RRF with multiple lists and varying weights."""
        doc_a = MockDocument("doc_a", "Content A")
        doc_b = MockDocument("doc_b", "Content B")
        doc_c = MockDocument("doc_c", "Content C")
        doc_d = MockDocument("doc_d", "Content D")

        ranked_results = [
            [doc_a, doc_b],  # weight 1.3
            [doc_c, doc_a],  # weight 1.0
            [doc_a, doc_d],  # weight 0.7
            [doc_b, doc_a],  # weight 0.5
        ]
        weights = [1.3, 1.0, 0.7, 0.5]

        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
        )

        # doc_a appears in all 4 lists, should rank first
        assert len(result) == 4
        assert result[0].document_id == "doc_a"

    def test_zero_weight(self) -> None:
        """Test RRF with zero weight for one list."""
        doc_a = MockDocument("doc_a", "Content A")
        doc_b = MockDocument("doc_b", "Content B")
        doc_c = MockDocument("doc_c", "Content C")

        ranked_results = [
            [doc_a, doc_b],  # weight 1.0
            [doc_c],  # weight 0.0 (ignored)
        ]
        weights = [1.0, 0.0]

        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
        )

        # doc_c should rank last due to zero weight
        assert len(result) == 3
        assert result[0].document_id == "doc_a"
        assert result[1].document_id == "doc_b"
        assert result[2].document_id == "doc_c"

    def test_negative_weight(self) -> None:
        """Test RRF with negative weight (should still work mathematically)."""
        doc_a = MockDocument("doc_a", "Content A")
        doc_b = MockDocument("doc_b", "Content B")

        ranked_results = [
            [doc_a, doc_b],  # weight 1.0
            [doc_b, doc_a],  # weight -0.5 (penalizes)
        ]
        weights = [1.0, -0.5]

        result = weighted_reciprocal_rank_fusion(
            ranked_results=ranked_results,
            weights=weights,
            id_extractor=lambda doc: doc.document_id,
        )

        # doc_a should rank higher (benefits from positive weight more)
        # doc_a: 1.0/(50+1) + (-0.5)/(50+2) = 0.0196 - 0.0096 = 0.0100
        # doc_b: 1.0/(50+2) + (-0.5)/(50+1) = 0.0192 - 0.0098 = 0.0094
        assert len(result) == 2
        assert result[0].document_id == "doc_a"
        assert result[1].document_id == "doc_b"


# =============================================================================
# Tests for deduplicate_queries
# =============================================================================


class TestDeduplicateQueries:
    """Test suite for deduplicate_queries function."""

    def test_no_duplicates(self) -> None:
        """Test deduplication with no duplicate queries."""
        queries_with_weights = [
            ("first query", 1.0),
            ("second query", 2.0),
            ("third query", 1.5),
        ]

        result = deduplicate_queries(queries_with_weights)

        assert len(result) == 3
        assert ("first query", 1.0) in result
        assert ("second query", 2.0) in result
        assert ("third query", 1.5) in result

    def test_exact_duplicates(self) -> None:
        """Test deduplication with exact duplicate queries."""
        queries_with_weights = [
            ("same query", 1.0),
            ("same query", 2.0),
            ("same query", 1.5),
        ]

        result = deduplicate_queries(queries_with_weights)

        # Should have one entry with summed weights
        assert len(result) == 1
        assert result[0][0] == "same query"
        assert result[0][1] == 4.5  # 1.0 + 2.0 + 1.5

    def test_case_insensitive_duplicates(self) -> None:
        """Test that deduplication is case-insensitive."""
        queries_with_weights = [
            ("Search Query", 1.0),
            ("search query", 2.0),
            ("SEARCH QUERY", 1.5),
        ]

        result = deduplicate_queries(queries_with_weights)

        # Should have one entry with summed weights
        assert len(result) == 1
        # Should preserve the casing of first occurrence
        assert result[0][0] == "Search Query"
        assert result[0][1] == 4.5  # 1.0 + 2.0 + 1.5

    def test_mixed_duplicates_and_unique(self) -> None:
        """Test deduplication with mix of duplicates and unique queries."""
        queries_with_weights = [
            ("unique query", 1.0),
            ("duplicate query", 2.0),
            ("DUPLICATE QUERY", 1.5),
            ("another unique", 3.0),
        ]

        result = deduplicate_queries(queries_with_weights)

        assert len(result) == 3

        # Check for unique queries
        unique_queries = [q for q, w in result if q == "unique query"]
        assert len(unique_queries) == 1
        unique_weight = [w for q, w in result if q == "unique query"][0]
        assert unique_weight == 1.0

        another_unique_queries = [q for q, w in result if q == "another unique"]
        assert len(another_unique_queries) == 1
        another_weight = [w for q, w in result if q == "another unique"][0]
        assert another_weight == 3.0

        # Check for deduplicated query
        dup_queries = [q for q, w in result if q.lower() == "duplicate query"]
        assert len(dup_queries) == 1
        dup_weight = [w for q, w in result if q.lower() == "duplicate query"][0]
        assert dup_weight == 3.5  # 2.0 + 1.5

    def test_empty_list(self) -> None:
        """Test deduplication with empty list."""
        queries_with_weights: list[tuple[str, float]] = []

        result = deduplicate_queries(queries_with_weights)

        assert len(result) == 0

    def test_single_query(self) -> None:
        """Test deduplication with single query."""
        queries_with_weights = [("single query", 1.5)]

        result = deduplicate_queries(queries_with_weights)

        assert len(result) == 1
        assert result[0] == ("single query", 1.5)

    def test_preserves_first_occurrence_casing(self) -> None:
        """Test that the first occurrence's casing is preserved."""
        queries_with_weights = [
            ("First Version", 1.0),
            ("first version", 2.0),
            ("FIRST VERSION", 3.0),
        ]

        result = deduplicate_queries(queries_with_weights)

        assert len(result) == 1
        # First occurrence casing should be preserved
        assert result[0][0] == "First Version"
        assert result[0][1] == 6.0

    def test_whitespace_differences(self) -> None:
        """Test that queries with different whitespace are treated as different."""
        queries_with_weights = [
            ("query with spaces", 1.0),
            ("query  with  spaces", 2.0),  # Different spacing
            ("query with spaces", 3.0),
        ]

        result = deduplicate_queries(queries_with_weights)

        # Should have two entries (one for single space, one for double)
        assert len(result) == 2

        # Find the summed weight for single-space version
        single_space_weight = [w for q, w in result if q == "query with spaces"][0]
        assert single_space_weight == 4.0  # 1.0 + 3.0

        # Find the weight for double-space version
        double_space_weight = [w for q, w in result if q == "query  with  spaces"][0]
        assert double_space_weight == 2.0

    def test_zero_weights(self) -> None:
        """Test deduplication with zero weights."""
        queries_with_weights = [
            ("query", 0.0),
            ("query", 0.0),
            ("other query", 1.0),
        ]

        result = deduplicate_queries(queries_with_weights)

        assert len(result) == 2
        query_weight = [w for q, w in result if q == "query"][0]
        assert query_weight == 0.0
        other_weight = [w for q, w in result if q == "other query"][0]
        assert other_weight == 1.0

    def test_negative_weights(self) -> None:
        """Test deduplication with negative weights."""
        queries_with_weights = [
            ("query", 2.0),
            ("query", -1.0),
        ]

        result = deduplicate_queries(queries_with_weights)

        assert len(result) == 1
        assert result[0][0] == "query"
        assert result[0][1] == 1.0  # 2.0 + (-1.0)

    def test_realistic_scenario_semantic_and_keyword_queries(self) -> None:
        """Test realistic scenario with semantic and keyword query deduplication."""
        queries_with_weights = [
            ("What is machine learning?", 1.3),  # Semantic query
            ("what is machine learning?", 1.0),  # LLM non-custom query
            ("machine learning definition", 1.0),  # Keyword expansion
            ("machine learning basics", 1.0),  # Keyword expansion
            ("MACHINE LEARNING DEFINITION", 1.0),  # Duplicate keyword (different case)
        ]

        result = deduplicate_queries(queries_with_weights)

        # Should have 3 unique queries after deduplication
        assert len(result) == 3

        # Check that "What is machine learning?" variants were deduplicated
        ml_queries = [
            (q, w) for q, w in result if q.lower() == "what is machine learning?"
        ]
        assert len(ml_queries) == 1
        assert (
            ml_queries[0][0] == "What is machine learning?"
        )  # First occurrence casing
        assert ml_queries[0][1] == 2.3  # 1.3 + 1.0

        # Check that "machine learning definition" variants were deduplicated
        def_queries = [
            (q, w) for q, w in result if q.lower() == "machine learning definition"
        ]
        assert len(def_queries) == 1
        assert (
            def_queries[0][0] == "machine learning definition"
        )  # First occurrence casing
        assert def_queries[0][1] == 2.0  # 1.0 + 1.0

        # Check that "machine learning basics" is present with its original weight
        basics_queries = [
            (q, w) for q, w in result if q.lower() == "machine learning basics"
        ]
        assert len(basics_queries) == 1
        assert basics_queries[0][1] == 1.0

    def test_special_characters_and_punctuation(self) -> None:
        """Test deduplication with special characters and punctuation."""
        queries_with_weights = [
            ("What's the weather?", 1.0),
            ("what's the weather?", 2.0),
            ("WHAT'S THE WEATHER?", 1.5),
        ]

        result = deduplicate_queries(queries_with_weights)

        assert len(result) == 1
        assert result[0][0] == "What's the weather?"
        assert result[0][1] == 4.5

    def test_unicode_characters(self) -> None:
        """Test deduplication with unicode characters."""
        queries_with_weights = [
            ("Café", 1.0),
            ("café", 2.0),
            ("CAFÉ", 1.5),
        ]

        result = deduplicate_queries(queries_with_weights)

        assert len(result) == 1
        assert result[0][0] == "Café"
        assert result[0][1] == 4.5
