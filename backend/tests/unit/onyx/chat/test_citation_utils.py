"""
Unit tests for citation_utils module.

This module tests the collapse_citations function which renumbers citations
in text to use the smallest possible numbers while respecting existing mappings.
"""

from datetime import datetime

from onyx.chat.citation_processor import CitationMapping
from onyx.chat.citation_utils import collapse_citations
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc


# ============================================================================
# Helper Functions
# ============================================================================


def create_test_search_doc(
    document_id: str = "test-doc-1",
    link: str | None = "https://example.com/doc1",
    chunk_ind: int = 0,
    semantic_identifier: str = "Test Document",
    blurb: str = "Test blurb",
    source_type: DocumentSource = DocumentSource.WEB,
    boost: int = 1,
    hidden: bool = False,
    metadata: dict | None = None,
    score: float | None = None,
    match_highlights: list[str] | None = None,
) -> SearchDoc:
    """Create a test SearchDoc instance with default or custom values."""
    return SearchDoc(
        document_id=document_id,
        chunk_ind=chunk_ind,
        semantic_identifier=semantic_identifier,
        link=link,
        blurb=blurb,
        source_type=source_type,
        boost=boost,
        hidden=hidden,
        metadata=metadata or {},
        score=score,
        match_highlights=match_highlights or [],
        updated_at=datetime.now(),
    )


# ============================================================================
# Basic Functionality Tests
# ============================================================================


class TestCollapseCitationsBasic:
    """Basic functionality tests for collapse_citations."""

    def test_empty_text_and_mappings(self) -> None:
        """Test with empty text and empty mappings."""
        text, mapping = collapse_citations("", {}, {})
        assert text == ""
        assert mapping == {}

    def test_text_without_citations(self) -> None:
        """Test text without any citations remains unchanged."""
        input_text = "This is some text without any citations."
        text, mapping = collapse_citations(input_text, {}, {})
        assert text == input_text
        assert mapping == {}

    def test_empty_existing_mapping_starts_from_one(self) -> None:
        """Test that with empty existing mapping, new citations start from 1."""
        doc1 = create_test_search_doc(document_id="doc_50")
        doc2 = create_test_search_doc(document_id="doc_60")
        new_mapping: CitationMapping = {50: doc1, 60: doc2}

        text, mapping = collapse_citations("See [50] and [60].", {}, new_mapping)

        # Should start from 1 when existing mapping is empty
        assert text == "See [1] and [2]."
        assert set(mapping.keys()) == {1, 2}
        assert mapping[1].document_id == "doc_50"
        assert mapping[2].document_id == "doc_60"

    def test_single_citation_no_existing(self) -> None:
        """Test collapsing a single citation with no existing mappings."""
        doc = create_test_search_doc(document_id="doc_25")
        new_mapping: CitationMapping = {25: doc}

        text, mapping = collapse_citations("See [25] for details.", {}, new_mapping)

        assert text == "See [1] for details."
        assert 1 in mapping
        assert mapping[1].document_id == "doc_25"
        assert len(mapping) == 1

    def test_multiple_citations_no_existing(self) -> None:
        """Test collapsing multiple citations with no existing mappings."""
        doc1 = create_test_search_doc(document_id="doc_100")
        doc2 = create_test_search_doc(document_id="doc_200")
        doc3 = create_test_search_doc(document_id="doc_300")
        new_mapping: CitationMapping = {100: doc1, 200: doc2, 300: doc3}

        text, mapping = collapse_citations(
            "See [100], [200], and [300].", {}, new_mapping
        )

        assert text == "See [1], [2], and [3]."
        assert mapping[1].document_id == "doc_100"
        assert mapping[2].document_id == "doc_200"
        assert mapping[3].document_id == "doc_300"
        assert len(mapping) == 3


class TestCollapseCitationsWithExisting:
    """Tests for collapse_citations with existing citation mappings."""

    def test_continues_from_existing_mapping(self) -> None:
        """Test that new citations start from the next available number."""
        existing_doc = create_test_search_doc(document_id="existing_doc")
        existing_mapping: CitationMapping = {1: existing_doc}

        new_doc = create_test_search_doc(document_id="new_doc")
        new_mapping: CitationMapping = {50: new_doc}

        text, mapping = collapse_citations(
            "See [50] for more.", existing_mapping, new_mapping
        )

        assert text == "See [2] for more."
        assert 1 in mapping
        assert 2 in mapping
        assert mapping[1].document_id == "existing_doc"
        assert mapping[2].document_id == "new_doc"
        assert len(mapping) == 2

    def test_reuses_existing_citation_for_same_document(self) -> None:
        """Test that citations to existing documents use the existing number."""
        doc = create_test_search_doc(document_id="shared_doc")
        existing_mapping: CitationMapping = {1: doc}

        # Same document referenced with a different citation number
        new_doc = create_test_search_doc(document_id="shared_doc")
        new_mapping: CitationMapping = {50: new_doc}

        text, mapping = collapse_citations(
            "See [50] again.", existing_mapping, new_mapping
        )

        assert text == "See [1] again."
        assert len(mapping) == 1
        assert mapping[1].document_id == "shared_doc"

    def test_mixed_existing_and_new_documents(self) -> None:
        """Test with a mix of existing and new documents."""
        existing_doc1 = create_test_search_doc(document_id="doc_a")
        existing_doc2 = create_test_search_doc(document_id="doc_b")
        existing_mapping: CitationMapping = {1: existing_doc1, 2: existing_doc2}

        # 30 refers to existing doc_a, 31 is new, 32 refers to existing doc_b
        new_doc_a = create_test_search_doc(document_id="doc_a")
        new_doc_c = create_test_search_doc(document_id="doc_c")
        new_doc_b = create_test_search_doc(document_id="doc_b")
        new_mapping: CitationMapping = {30: new_doc_a, 31: new_doc_c, 32: new_doc_b}

        text, mapping = collapse_citations(
            "Refs: [30], [31], [32].", existing_mapping, new_mapping
        )

        # [30] -> [1] (doc_a exists as 1)
        # [31] -> [3] (doc_c is new, next available)
        # [32] -> [2] (doc_b exists as 2)
        assert text == "Refs: [1], [3], [2]."
        assert len(mapping) == 3
        assert mapping[1].document_id == "doc_a"
        assert mapping[2].document_id == "doc_b"
        assert mapping[3].document_id == "doc_c"

    def test_existing_mapping_unchanged(self) -> None:
        """Test that existing mapping values are not modified."""
        existing_doc = create_test_search_doc(
            document_id="existing", link="https://existing.com"
        )
        existing_mapping: CitationMapping = {5: existing_doc}

        new_doc = create_test_search_doc(document_id="new_doc")
        new_mapping: CitationMapping = {100: new_doc}

        text, mapping = collapse_citations("[100]", existing_mapping, new_mapping)

        # Existing mapping should be preserved with its original key
        assert 5 in mapping
        assert mapping[5].document_id == "existing"
        assert mapping[5].link == "https://existing.com"
        # New citation should get next available number (6)
        assert 6 in mapping
        assert mapping[6].document_id == "new_doc"


class TestCollapseCitationsMultipleCitations:
    """Tests for multiple citation formats and edge cases."""

    def test_same_citation_multiple_times(self) -> None:
        """Test the same citation appearing multiple times in text."""
        doc = create_test_search_doc(document_id="doc_25")
        new_mapping: CitationMapping = {25: doc}

        text, mapping = collapse_citations(
            "[25] says X. Also [25] says Y.", {}, new_mapping
        )

        assert text == "[1] says X. Also [1] says Y."
        assert len(mapping) == 1
        assert mapping[1].document_id == "doc_25"

    def test_comma_separated_citations(self) -> None:
        """Test comma-separated citations like [1, 2, 3]."""
        doc1 = create_test_search_doc(document_id="doc_10")
        doc2 = create_test_search_doc(document_id="doc_20")
        new_mapping: CitationMapping = {10: doc1, 20: doc2}

        text, mapping = collapse_citations("[10, 20]", {}, new_mapping)

        assert text == "[1, 2]"
        assert len(mapping) == 2

    def test_double_bracket_citations(self) -> None:
        """Test double bracket citations like [[25]]."""
        doc = create_test_search_doc(document_id="doc_25")
        new_mapping: CitationMapping = {25: doc}

        text, mapping = collapse_citations("See [[25]] for info.", {}, new_mapping)

        assert text == "See [[1]] for info."
        assert mapping[1].document_id == "doc_25"

    def test_same_doc_different_old_numbers(self) -> None:
        """Test same document appearing with different citation numbers."""
        doc = create_test_search_doc(document_id="same_doc")
        # Same document with two different citation numbers
        new_mapping: CitationMapping = {
            50: doc,
            60: create_test_search_doc(document_id="same_doc"),
        }

        text, mapping = collapse_citations("[50] and [60]", {}, new_mapping)

        # Both should map to the same new number
        assert text == "[1] and [1]"
        assert len(mapping) == 1
        assert mapping[1].document_id == "same_doc"


class TestCollapseCitationsUnicodeBrackets:
    """Tests for unicode bracket variants."""

    def test_unicode_brackets_chinese(self) -> None:
        """Test Chinese-style brackets 【】."""
        doc = create_test_search_doc(document_id="doc_25")
        new_mapping: CitationMapping = {25: doc}

        text, mapping = collapse_citations("See 【25】 for details.", {}, new_mapping)

        assert text == "See 【1】 for details."
        assert mapping[1].document_id == "doc_25"

    def test_unicode_brackets_fullwidth(self) -> None:
        """Test fullwidth brackets ［］."""
        doc = create_test_search_doc(document_id="doc_25")
        new_mapping: CitationMapping = {25: doc}

        text, mapping = collapse_citations("See ［25］ for details.", {}, new_mapping)

        assert text == "See ［1］ for details."
        assert mapping[1].document_id == "doc_25"

    def test_double_unicode_brackets(self) -> None:
        """Test double unicode brackets 【【25】】."""
        doc = create_test_search_doc(document_id="doc_25")
        new_mapping: CitationMapping = {25: doc}

        text, mapping = collapse_citations("See 【【25】】 for info.", {}, new_mapping)

        assert text == "See 【【1】】 for info."
        assert mapping[1].document_id == "doc_25"


class TestCollapseCitationsEdgeCases:
    """Edge case tests for collapse_citations."""

    def test_citation_not_in_mapping(self) -> None:
        """Test citations in text that aren't in the new mapping are preserved."""
        doc = create_test_search_doc(document_id="doc_25")
        new_mapping: CitationMapping = {25: doc}

        # [99] is not in the mapping, should remain unchanged
        text, mapping = collapse_citations("[25] and [99]", {}, new_mapping)

        assert text == "[1] and [99]"
        assert len(mapping) == 1

    def test_non_sequential_existing_mapping(self) -> None:
        """Test with non-sequential existing mapping numbers."""
        existing_mapping: CitationMapping = {
            5: create_test_search_doc(document_id="doc_5"),
            10: create_test_search_doc(document_id="doc_10"),
        }

        new_doc = create_test_search_doc(document_id="new_doc")
        new_mapping: CitationMapping = {99: new_doc}

        text, mapping = collapse_citations("[99]", existing_mapping, new_mapping)

        # Next available should be max(5, 10) + 1 = 11
        assert text == "[11]"
        assert 5 in mapping
        assert 10 in mapping
        assert 11 in mapping
        assert len(mapping) == 3

    def test_preserves_text_around_citations(self) -> None:
        """Test that text around citations is preserved exactly."""
        doc = create_test_search_doc(document_id="doc_1")
        new_mapping: CitationMapping = {100: doc}

        input_text = "According to the source [100], this is true.\n\nNext paragraph."
        text, mapping = collapse_citations(input_text, {}, new_mapping)

        assert text == "According to the source [1], this is true.\n\nNext paragraph."

    def test_citation_at_start_of_text(self) -> None:
        """Test citation at the very start of text."""
        doc = create_test_search_doc(document_id="doc_1")
        new_mapping: CitationMapping = {50: doc}

        text, mapping = collapse_citations("[50] is the answer.", {}, new_mapping)

        assert text == "[1] is the answer."

    def test_citation_at_end_of_text(self) -> None:
        """Test citation at the very end of text."""
        doc = create_test_search_doc(document_id="doc_1")
        new_mapping: CitationMapping = {50: doc}

        text, mapping = collapse_citations("The answer is [50]", {}, new_mapping)

        assert text == "The answer is [1]"

    def test_adjacent_citations(self) -> None:
        """Test citations immediately adjacent to each other."""
        doc1 = create_test_search_doc(document_id="doc_1")
        doc2 = create_test_search_doc(document_id="doc_2")
        new_mapping: CitationMapping = {50: doc1, 60: doc2}

        text, mapping = collapse_citations("[50][60]", {}, new_mapping)

        assert text == "[1][2]"

    def test_empty_new_mapping_with_existing(self) -> None:
        """Test with existing mapping but no new citations to process."""
        existing_doc = create_test_search_doc(document_id="existing")
        existing_mapping: CitationMapping = {1: existing_doc}

        text, mapping = collapse_citations("No citations here.", existing_mapping, {})

        assert text == "No citations here."
        assert mapping == existing_mapping


class TestCollapseCitationsOrdering:
    """Tests for citation ordering behavior."""

    def test_assigns_numbers_in_order_of_appearance(self) -> None:
        """Test that new numbers are assigned based on order in new_mapping iteration."""
        doc1 = create_test_search_doc(document_id="doc_a")
        doc2 = create_test_search_doc(document_id="doc_b")
        doc3 = create_test_search_doc(document_id="doc_c")
        # Note: dict order is preserved in Python 3.7+
        new_mapping: CitationMapping = {300: doc1, 100: doc2, 200: doc3}

        text, mapping = collapse_citations("[300] [100] [200]", {}, new_mapping)

        # The mapping iteration order determines assignment:
        # 300 -> 1 (first in new_mapping)
        # 100 -> 2 (second in new_mapping)
        # 200 -> 3 (third in new_mapping)
        assert mapping[1].document_id == "doc_a"
        assert mapping[2].document_id == "doc_b"
        assert mapping[3].document_id == "doc_c"
        assert text == "[1] [2] [3]"

    def test_multiple_existing_citations_preserved(self) -> None:
        """Test that all existing citations are preserved in output mapping."""
        existing_mapping: CitationMapping = {
            1: create_test_search_doc(document_id="doc_1"),
            2: create_test_search_doc(document_id="doc_2"),
            3: create_test_search_doc(document_id="doc_3"),
        }

        new_doc = create_test_search_doc(document_id="new_doc")
        new_mapping: CitationMapping = {99: new_doc}

        text, mapping = collapse_citations("[99]", existing_mapping, new_mapping)

        assert text == "[4]"
        # All existing plus the new one
        assert len(mapping) == 4
        assert mapping[1].document_id == "doc_1"
        assert mapping[2].document_id == "doc_2"
        assert mapping[3].document_id == "doc_3"
        assert mapping[4].document_id == "new_doc"


class TestCollapseCitationsComplexScenarios:
    """Complex real-world scenario tests."""

    def test_research_agent_scenario(self) -> None:
        """Test a realistic research agent scenario with multiple tool calls."""
        # First search returned citations 1-5
        existing_mapping: CitationMapping = {
            1: create_test_search_doc(document_id="wiki_python"),
            2: create_test_search_doc(document_id="docs_typing"),
            3: create_test_search_doc(document_id="blog_best_practices"),
        }

        # Second search returned citations starting at 100 (to avoid conflicts)
        # Some docs are the same as before
        new_mapping: CitationMapping = {
            100: create_test_search_doc(document_id="wiki_python"),  # Same as 1
            101: create_test_search_doc(document_id="new_tutorial"),  # New
            102: create_test_search_doc(document_id="docs_typing"),  # Same as 2
            103: create_test_search_doc(document_id="another_new"),  # New
        }

        text, mapping = collapse_citations(
            "According to [100] and [101], also see [102] and [103].",
            existing_mapping,
            new_mapping,
        )

        # [100] -> [1] (wiki_python exists as 1)
        # [101] -> [4] (new_tutorial is new, next after 3)
        # [102] -> [2] (docs_typing exists as 2)
        # [103] -> [5] (another_new is new)
        assert text == "According to [1] and [4], also see [2] and [5]."
        assert len(mapping) == 5
        assert mapping[1].document_id == "wiki_python"
        assert mapping[2].document_id == "docs_typing"
        assert mapping[3].document_id == "blog_best_practices"
        assert mapping[4].document_id == "new_tutorial"
        assert mapping[5].document_id == "another_new"

    def test_long_text_with_many_citations(self) -> None:
        """Test processing longer text with many citations."""
        # Create docs for citations 50-55
        new_mapping: CitationMapping = {
            i: create_test_search_doc(document_id=f"doc_{i}") for i in range(50, 56)
        }

        text = """
        This is a comprehensive document with multiple citations.

        First, we discuss [50] which provides background information.
        Then [51] and [52] offer contrasting viewpoints.

        The middle section references [53] extensively, as seen here [53].

        Finally, [54] and [55] conclude the analysis. Note that [50]
        is referenced again for context.
        """

        result_text, mapping = collapse_citations(text, {}, new_mapping)

        # All 50-55 should be collapsed to 1-6
        assert "[1]" in result_text
        assert "[2]" in result_text
        assert "[3]" in result_text
        assert "[4]" in result_text
        assert "[5]" in result_text
        assert "[6]" in result_text
        # Original numbers should not appear
        assert "[50]" not in result_text
        assert "[51]" not in result_text
        assert len(mapping) == 6
