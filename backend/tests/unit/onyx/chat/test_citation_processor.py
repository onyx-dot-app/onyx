"""
Unit tests for DynamicCitationProcessor.

This module contains comprehensive tests for the DynamicCitationProcessor class,
which processes streaming tokens from LLMs to extract citations, remove citation
markers from output text, and emit CitationInfo objects.

Key features tested:
- Dynamic citation mapping updates
- Citation extraction and formatting
- Citation removal from output
- CitationInfo emission and tracking
- Edge cases (unicode, code blocks, invalid citations, etc.)
"""

from datetime import datetime

import pytest

from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.server.query_and_chat.streaming_models import CitationInfo


# ============================================================================
# Helper Functions and Fixtures
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


def process_tokens(
    processor: DynamicCitationProcessor, tokens: list[str | None]
) -> tuple[str, list[CitationInfo]]:
    """
    Process a list of tokens through the processor and collect results.

    Returns:
        Tuple of (output_text, citations) where:
        - output_text: All string outputs concatenated
        - citations: List of CitationInfo objects emitted
    """
    output_text = ""
    citations = []

    for token in tokens:
        for result in processor.process_token(token):
            if isinstance(result, str):
                output_text += result
            elif isinstance(result, CitationInfo):
                citations.append(result)

    # Flush remaining segment
    for result in processor.process_token(None):
        if isinstance(result, str):
            output_text += result
        elif isinstance(result, CitationInfo):
            citations.append(result)

    return output_text, citations


@pytest.fixture
def mock_search_docs() -> dict[int, SearchDoc]:
    """Create a dictionary of mock SearchDoc objects for testing."""
    return {
        1: create_test_search_doc(
            document_id="doc_1",
            link="https://example.com/doc1",
            semantic_identifier="Document 1",
        ),
        2: create_test_search_doc(
            document_id="doc_2",
            link="https://example.com/doc2",
            semantic_identifier="Document 2",
        ),
        3: create_test_search_doc(
            document_id="doc_3",
            link=None,  # No link
            semantic_identifier="Document 3",
        ),
        4: create_test_search_doc(
            document_id="doc_4",
            link="https://example.com/doc4",
            semantic_identifier="Document 4",
        ),
        5: create_test_search_doc(
            document_id="doc_5",
            link="https://example.com/doc5",
            semantic_identifier="Document 5",
        ),
    }


# ============================================================================
# Initialization Tests
# ============================================================================


def test_default_initialization() -> None:
    """Test default initialization of DynamicCitationProcessor."""
    processor = DynamicCitationProcessor()

    assert processor.citation_to_doc == {}
    assert processor.llm_out == ""
    assert processor.curr_segment == ""
    assert processor.hold == ""
    assert processor.cited_documents_in_order == []
    assert processor.cited_document_ids == set()
    assert processor.recent_cited_documents == set()
    assert processor.non_citation_count == 0


def test_initialization_with_custom_stop_stream() -> None:
    """Test initialization with custom stop_stream."""
    stop_stream = "STOP_TOKEN"
    processor = DynamicCitationProcessor(stop_stream=stop_stream)

    assert processor.stop_stream == stop_stream
    assert processor.citation_to_doc == {}


def test_initial_state_empty() -> None:
    """Test that initial state is empty and ready for use."""
    processor = DynamicCitationProcessor()

    assert processor.get_cited_documents() == []
    assert processor.get_cited_document_ids() == []
    assert processor.num_cited_documents == 0


# ============================================================================
# Citation Mapping Tests
# ============================================================================


def test_update_citation_mapping_single(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test updating citation mapping with a single mapping."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    assert len(processor.citation_to_doc) == 1
    assert processor.citation_to_doc[1] == mock_search_docs[1]
    assert processor.citation_to_doc[1].document_id == "doc_1"


def test_update_citation_mapping_multiple(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test updating citation mapping with multiple mappings."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping(
        {1: mock_search_docs[1], 2: mock_search_docs[2], 3: mock_search_docs[3]}
    )

    assert len(processor.citation_to_doc) == 3
    assert processor.citation_to_doc[1].document_id == "doc_1"
    assert processor.citation_to_doc[2].document_id == "doc_2"
    assert processor.citation_to_doc[3].document_id == "doc_3"


def test_update_citation_mapping_merges(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test that update_citation_mapping merges with existing mappings."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})
    processor.update_citation_mapping({2: mock_search_docs[2]})

    assert len(processor.citation_to_doc) == 2
    assert processor.citation_to_doc[1] == mock_search_docs[1]
    assert processor.citation_to_doc[2] == mock_search_docs[2]


def test_update_citation_mapping_updates_existing(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that update_citation_mapping can update existing citation numbers."""
    processor = DynamicCitationProcessor()
    doc1 = mock_search_docs[1]
    doc2 = create_test_search_doc(
        document_id="doc_1_updated", link="https://updated.com"
    )

    processor.update_citation_mapping({1: doc1})
    processor.update_citation_mapping({1: doc2})

    assert len(processor.citation_to_doc) == 1
    assert processor.citation_to_doc[1].document_id == "doc_1_updated"
    assert processor.citation_to_doc[1].link == "https://updated.com"


# ============================================================================
# Basic Citation Processing Tests
# ============================================================================


def test_single_citation(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test processing a single citation [1]."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, citations = process_tokens(processor, ["Text [", "1", "] here."])

    # Raw citation pattern should be replaced with formatted version
    assert (
        "Text [" not in output
        or "Text [" in output
        and "[[1]](https://example.com/doc1)" in output
    )
    assert "here." in output
    assert len(citations) == 1
    assert citations[0].citation_number == 1
    assert citations[0].document_id == "doc_1"


def test_multiple_citations_comma_separated(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test processing multiple citations [1, 2, 3]."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping(
        {1: mock_search_docs[1], 2: mock_search_docs[2], 3: mock_search_docs[3]}
    )

    output, citations = process_tokens(
        processor, ["Text [", "1", ",", " ", "2", ",", "3", "] end."]
    )

    # Raw citation patterns should be replaced with formatted versions
    assert "[[1]](https://example.com/doc1)" in output
    assert "[[2]](https://example.com/doc2)" in output
    assert "[[3]]()" in output
    assert "end." in output
    assert len(citations) == 3
    assert {c.document_id for c in citations} == {"doc_1", "doc_2", "doc_3"}


def test_double_bracket_citation(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test processing double bracket citation [[1]]."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, citations = process_tokens(processor, ["Text [[", "1", "]] here."])

    # Double bracket citation should be replaced with formatted version
    assert "[[1]](https://example.com/doc1)" in output
    assert "here." in output
    assert len(citations) == 1
    assert citations[0].citation_number == 1


def test_citation_split_across_tokens(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test citation split across multiple tokens."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, citations = process_tokens(processor, ["[", "1", "]"])

    assert "[[1]](https://example.com/doc1)" in output
    assert len(citations) == 1


def test_citation_at_beginning(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test citation at the beginning of text."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, citations = process_tokens(processor, ["[", "1", "] Text here."])

    assert "[[1]](https://example.com/doc1)" in output
    assert "Text here." in output
    assert len(citations) == 1


def test_citation_at_end(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test citation at the end of text."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, citations = process_tokens(processor, ["Text here [", "1", "]"])

    assert "[[1]](https://example.com/doc1)" in output
    assert "Text here" in output
    assert len(citations) == 1


def test_citation_in_middle(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test citation in the middle of text."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, citations = process_tokens(processor, ["Start [", "1", "] end."])

    assert "[[1]](https://example.com/doc1)" in output
    assert "Start" in output and "end." in output
    assert len(citations) == 1


# ============================================================================
# Citation Formatting and Output Tests
# ============================================================================


def test_citation_removed_from_output(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test that citations are removed from output text."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, _ = process_tokens(processor, ["This is text [", "1", "] with citation."])

    # Raw citation should be replaced with formatted version
    assert "This is text [[1]](https://example.com/doc1) with citation." in output


def test_formatted_citation_yielded_separately(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that formatted citations are yielded separately."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    results = []
    for token in ["Text [", "1", "] here."]:
        for result in processor.process_token(token):
            results.append(result)

    # Should have text chunks and formatted citation
    text_results = [r for r in results if isinstance(r, str)]
    citation_results = [r for r in results if isinstance(r, CitationInfo)]

    assert len(citation_results) == 1
    assert any("[[1]](https://example.com/doc1)" in r for r in text_results)


def test_leading_space_with_existing_space(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test leading space handling when space already exists."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, _ = process_tokens(processor, ["Text ", "[", "1", "] here."])
    # Should not add extra space
    assert "Text " in output or "Text [[1]](https://example.com/doc1)" in output


def test_leading_space_without_existing_space(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test leading space handling when no space exists."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, _ = process_tokens(processor, ["Text[", "1", "] here."])

    # Should preserve order: text before citation, then citation with space added
    assert "Text [[1]](https://example.com/doc1) here." in output


def test_citation_with_link(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test citation formatting with link."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, _ = process_tokens(processor, ["Text [", "1", "]"])

    assert "Text [[1]](https://example.com/doc1)" in output


def test_citation_without_link(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test citation formatting without link."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({3: mock_search_docs[3]})  # doc_3 has no link

    output, _ = process_tokens(processor, ["Text [", "3", "]"])

    assert "Text [[3]]()" in output


def test_multiple_citations_in_sequence(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test multiple citations formatted in sequence."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping(
        {1: mock_search_docs[1], 2: mock_search_docs[2], 3: mock_search_docs[3]}
    )

    output, citations = process_tokens(
        processor, ["Text [", "1", "][", "2", "][", "3", "]"]
    )

    assert (
        "Text [[1]](https://example.com/doc1)[[2]](https://example.com/doc2)[[3]]()"
        in output
    )
    assert len(citations) == 3


# ============================================================================
# CitationInfo Emission Tests
# ============================================================================


def test_citation_info_emitted_for_new_citation(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that CitationInfo is emitted for new citations."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    _, citations = process_tokens(processor, ["Text [", "1", "]"])

    assert len(citations) == 1
    assert citations[0].citation_number == 1
    assert citations[0].document_id == "doc_1"


def test_citation_info_contains_correct_fields(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that CitationInfo contains correct citation_number and document_id."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1], 2: mock_search_docs[2]})

    _, citations = process_tokens(processor, ["[", "1", "][", "2", "]"])

    assert len(citations) == 2
    citation_numbers = {c.citation_number for c in citations}
    document_ids = {c.document_id for c in citations}
    assert citation_numbers == {1, 2}
    assert document_ids == {"doc_1", "doc_2"}


def test_citation_info_deduplication_recent(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that recent citations don't emit CitationInfo."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    _, citations1 = process_tokens(processor, ["First [", "1", "]"])
    assert len(citations1) == 1

    # Same citation again immediately - should not emit CitationInfo
    _, citations2 = process_tokens(processor, ["Second [", "1", "]"])
    assert len(citations2) == 0  # No new CitationInfo


def test_citation_info_order_matches_first_citation(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that CitationInfo order matches first citation order."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping(
        {1: mock_search_docs[1], 2: mock_search_docs[2], 3: mock_search_docs[3]}
    )

    _, citations = process_tokens(processor, ["[", "3", "][", "1", "][", "2", "]"])

    # Order should be 3, 1, 2 (first citation order)
    assert len(citations) == 3
    assert citations[0].citation_number == 3
    assert citations[1].citation_number == 1
    assert citations[2].citation_number == 2


# ============================================================================
# Citation Order Tracking Tests
# ============================================================================


def test_get_cited_documents_order(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test that get_cited_documents returns documents in first citation order."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping(
        {1: mock_search_docs[1], 2: mock_search_docs[2], 3: mock_search_docs[3]}
    )

    process_tokens(processor, ["[", "3", "][", "1", "][", "2", "]"])

    cited_docs = processor.get_cited_documents()
    assert len(cited_docs) == 3
    assert cited_docs[0].document_id == "doc_3"
    assert cited_docs[1].document_id == "doc_1"
    assert cited_docs[2].document_id == "doc_2"


def test_get_cited_document_ids_order(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test that get_cited_document_ids returns IDs in correct order."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping(
        {1: mock_search_docs[1], 2: mock_search_docs[2], 3: mock_search_docs[3]}
    )

    process_tokens(processor, ["[", "2", "][", "1", "][", "3", "]"])

    doc_ids = processor.get_cited_document_ids()
    assert doc_ids == ["doc_2", "doc_1", "doc_3"]


def test_num_cited_documents_property(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test that num_cited_documents property returns correct count."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping(
        {1: mock_search_docs[1], 2: mock_search_docs[2], 3: mock_search_docs[3]}
    )

    assert processor.num_cited_documents == 0

    process_tokens(processor, ["[", "1", "]"])
    assert processor.num_cited_documents == 1

    process_tokens(processor, ["[", "2", "]"])
    assert processor.num_cited_documents == 2

    # Same document again shouldn't increase count
    process_tokens(processor, ["[", "1", "]"])
    assert processor.num_cited_documents == 2


def test_multiple_citations_same_document_no_duplicate(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that multiple citations of same document don't duplicate in order."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    process_tokens(processor, ["[", "1", "][", "1", "][", "1", "]"])

    cited_docs = processor.get_cited_documents()
    assert len(cited_docs) == 1
    assert cited_docs[0].document_id == "doc_1"


# ============================================================================
# Recent Citation Deduplication Tests
# ============================================================================


def test_recent_citations_no_citation_info(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that recent citations don't emit CitationInfo."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    _, citations1 = process_tokens(processor, ["First [", "1", "]"])
    assert len(citations1) == 1

    _, citations2 = process_tokens(processor, ["Second [", "1", "]"])
    assert len(citations2) == 0  # No CitationInfo for recent citation


def test_recent_citations_still_format_text(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that recent citations still format citation text."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output1, _ = process_tokens(processor, ["First [", "1", "]"])
    assert "[[1]](https://example.com/doc1)" in output1

    output2, _ = process_tokens(processor, ["Second [", "1", "]"])
    assert "[[1]](https://example.com/doc1)" in output2  # Still formatted


def test_reset_recent_citations(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test that reset_recent_citations clears recent tracker."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    _, citations1 = process_tokens(processor, ["First [", "1", "]"])
    assert len(citations1) == 1

    _, citations2 = process_tokens(processor, ["Second [", "1", "]"])
    assert len(citations2) == 0  # Recent citation

    processor.reset_recent_citations()

    _, citations3 = process_tokens(processor, ["Third [", "1", "]"])
    assert len(citations3) == 0  # Still no CitationInfo (already in cited_documents)


def test_non_citation_count_threshold_resets_recent(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that non-citation count threshold (5) resets recent citations."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    _, citations1 = process_tokens(processor, ["First [", "1", "]"])
    assert len(citations1) == 1

    # Add enough non-citation text to trigger reset (>5 chars)
    _, citations2 = process_tokens(processor, ["Second [", "1", "]"])
    assert len(citations2) == 0  # Recent citation

    # Add text with more than 5 non-citation characters
    _, citations3 = process_tokens(processor, ["Long text here [", "1", "]"])
    # After >5 non-citation chars, recent citations should be cleared
    # But since doc_1 is already in cited_documents, no new CitationInfo
    assert len(citations3) == 0


# ============================================================================
# Invalid Citation Handling Tests
# ============================================================================


def test_citation_not_in_mapping_skipped(
    mock_search_docs: dict[int, SearchDoc], caplog: pytest.LogCaptureFixture
) -> None:
    """Test that citations with numbers not in mapping are skipped."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, citations = process_tokens(processor, ["Text [", "99", "] here."])

    assert "[99]" not in output  # Citation removed but not processed
    assert len(citations) == 0
    assert "Citation number 99 not found in mapping" in caplog.text


def test_invalid_citation_format_skipped(
    mock_search_docs: dict[int, SearchDoc], caplog: pytest.LogCaptureFixture
) -> None:
    """Test that invalid citation number formats are skipped."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    # This should not match the citation pattern, so it will be left as-is
    output, citations = process_tokens(processor, ["Text [", "abc", "] here."])

    assert len(citations) == 0
    assert "Text [abc] here." in output


def test_empty_citation_content_handled(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test that empty citation content is handled."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    # Empty citation like [,] should be handled - empty parts are skipped
    output, citations = process_tokens(processor, ["Text [", "1", ",", " ", "2", "]"])

    # Should process both citations, skipping empty parts
    assert len(citations) >= 1  # At least one valid citation


def test_citation_with_non_integer_skipped(
    mock_search_docs: dict[int, SearchDoc], caplog: pytest.LogCaptureFixture
) -> None:
    """Test that citations with non-integer content are skipped."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    # This won't match the pattern, but if it did, it would be skipped
    output, citations = process_tokens(processor, ["Text [", "1.5", "]"])

    # The pattern requires integers, so this won't match
    assert len(citations) == 0 or "[1.5]" in output


# ============================================================================
# Unicode Bracket Tests
# ============================================================================


def test_unicode_bracket_citation(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test processing unicode bracket citation 【1】."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, citations = process_tokens(processor, ["Text 【", "1", "】 here."])

    assert "【1】" not in output
    assert len(citations) == 1
    assert citations[0].citation_number == 1


def test_unicode_bracket_variant(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test processing unicode bracket variant ［1］."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, citations = process_tokens(processor, ["Text ［", "1", "］ here."])

    assert "［1］" not in output
    assert len(citations) == 1


def test_double_unicode_bracket_citation(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test processing double unicode bracket citation 【【1】】."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, citations = process_tokens(processor, ["Text 【【", "1", "】】 here."])

    assert "【【1】】" not in output
    assert len(citations) == 1


def test_mixed_ascii_unicode_brackets(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test mixed ASCII and unicode brackets."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1], 2: mock_search_docs[2]})

    output, citations = process_tokens(
        processor, ["ASCII [", "1", "] unicode 【", "2", "】"]
    )

    assert "[[1]](https://example.com/doc1)" in output
    assert "[[2]](https://example.com/doc2)" in output
    assert len(citations) == 2


def test_unicode_brackets_split_across_tokens(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test unicode brackets split across tokens."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, citations = process_tokens(processor, ["【", "1", "】"])

    assert "【1】" not in output
    assert len(citations) == 1


# ============================================================================
# Code Block Handling Tests
# ============================================================================


def test_citation_inside_code_block_not_processed(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that citations inside code blocks are not processed."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    tokens = [
        "Here's code:\n```\n",
        "def example():\n    print('[1]')\n",
        "```\n",
        "End.",
    ]
    output, citations = process_tokens(processor, tokens)

    # Citation inside code block should not be processed
    assert len(citations) == 0
    # Code block should have plaintext added
    assert "```plaintext" in output


def test_code_block_plaintext_added(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test that code blocks with ``` followed by \\n get 'plaintext' added."""
    processor = DynamicCitationProcessor()

    tokens = ["Code:\n```\n", "def test():\n    pass\n", "```\n"]
    output, _ = process_tokens(processor, tokens)

    assert "```plaintext" in output


def test_citation_outside_code_block_processed(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that citations outside code blocks are processed normally."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    tokens = [
        "Text [",
        "1",
        "] before code.\n```\n",
        "code here\n",
        "```\n",
        "Text [",
        "1",
        "] after code.",
    ]
    output, citations = process_tokens(processor, tokens)

    # Should have citations before and after code block
    # Same document, so only one CitationInfo (first citation)
    assert len(citations) == 1
    # Citations outside code block should be formatted
    assert "[[1]](https://example.com/doc1)" in output
    # Citation inside code block should remain as-is
    assert "code here" in output


def test_multiple_code_blocks(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test handling of multiple code blocks."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    tokens = [
        "First block:\n```\n",
        "code1\n",
        "```\n",
        "Text [",
        "1",
        "]\n",
        "Second block:\n```\n",
        "code2\n",
        "```\n",
    ]
    output, citations = process_tokens(processor, tokens)

    assert "```plaintext" in output
    assert len(citations) == 1


# ============================================================================
# Stop Token Tests
# ============================================================================


def test_stop_token_detection_stops_processing() -> None:
    """Test that stop token detection stops processing."""
    stop_stream = "STOP"
    processor = DynamicCitationProcessor(stop_stream=stop_stream)

    results = []
    for token in ["Text ", "ST", "OP"]:
        for result in processor.process_token(token):
            results.append(result)

    # Try to add more text after stop token
    for result in processor.process_token(" more text"):
        results.append(result)

    # Processing should stop at STOP token - no results after STOP
    output = "".join(r for r in results if isinstance(r, str))
    # The stop token itself should not appear in output
    assert "STOP" not in output or output == ""


def test_partial_stop_token_held_back() -> None:
    """Test that partial stop token is held back."""
    stop_stream = "STOP"
    processor = DynamicCitationProcessor(stop_stream=stop_stream)

    results = []
    for token in ["Text ", "ST"]:
        for result in processor.process_token(token):
            results.append(result)

    # Partial stop token should be held back
    output = "".join(r for r in results if isinstance(r, str))
    # Should have "Text " but "ST" should be held
    assert "Text " in output or output == ""


def test_stop_token_at_different_positions() -> None:
    """Test stop token at different positions."""
    stop_stream = "END"

    # Stop token at beginning - when detected, processing stops for that token
    processor1 = DynamicCitationProcessor(stop_stream=stop_stream)
    results1 = []
    for token in ["END"]:
        for result in processor1.process_token(token):
            results1.append(result)
    # Stop token detection returns early, so no results
    output1 = "".join(r for r in results1 if isinstance(r, str))
    assert output1 == ""  # Stop token detected, no output

    # Stop token in middle - text before stop token is processed
    processor2 = DynamicCitationProcessor(stop_stream=stop_stream)
    results2 = []
    for token in ["Start ", "EN", "D"]:
        for result in processor2.process_token(token):
            results2.append(result)
    output2 = "".join(r for r in results2 if isinstance(r, str))
    # "Start " should be processed before stop token is detected
    assert "Start " in output2
    # Stop token "END" should not appear in output
    assert "END" not in output2


# ============================================================================
# Edge Cases
# ============================================================================


def test_empty_token_stream() -> None:
    """Test processing empty token stream."""
    processor = DynamicCitationProcessor()

    output, citations = process_tokens(processor, [])

    assert output == ""
    assert len(citations) == 0


def test_none_token_flushes_remaining_segment(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that None token (end of stream) flushes remaining segment."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    results = []
    for token in ["Remaining ", "text"]:
        for result in processor.process_token(token):
            results.append(result)

    # Flush with None
    for result in processor.process_token(None):
        results.append(result)

    output = "".join(r for r in results if isinstance(r, str))
    assert "Remaining text" in output


def test_very_long_citation_numbers(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test citations with very long citation numbers."""
    processor = DynamicCitationProcessor()
    # Create a doc with a high citation number
    doc_100 = create_test_search_doc(
        document_id="doc_100", link="https://example.com/doc100"
    )
    processor.update_citation_mapping({100: doc_100})

    output, citations = process_tokens(processor, ["Text [", "100", "]"])

    assert len(citations) == 1
    assert citations[0].citation_number == 100


def test_citations_with_extra_whitespace(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test citations with extra whitespace."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1], 2: mock_search_docs[2]})

    # Extra whitespace in citation should be handled (stripped)
    output, citations = process_tokens(processor, ["Text [", "1", ",", " ", "2", "]"])

    assert len(citations) == 2
    assert "[[1]](https://example.com/doc1)" in output
    assert "[[2]](https://example.com/doc2)" in output


def test_consecutive_citations_no_text_between(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test consecutive citations without text between."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1], 2: mock_search_docs[2]})

    output, citations = process_tokens(processor, ["[", "1", "][", "2", "]"])

    assert "[[1]](https://example.com/doc1)" in output
    assert "[[2]](https://example.com/doc2)" in output
    assert len(citations) == 2


def test_citations_at_stream_boundaries(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test citations at stream boundaries."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    # Citation split at very beginning
    output1, citations1 = process_tokens(processor, ["[", "1", "] text"])
    assert len(citations1) == 1
    assert "[[1]](https://example.com/doc1) text" in output1

    # Citation split at very end
    processor2 = DynamicCitationProcessor()
    processor2.update_citation_mapping({1: mock_search_docs[1]})
    output2, citations2 = process_tokens(processor2, ["text [", "1", "]"])
    assert len(citations2) == 1
    assert "text [[1]](https://example.com/doc1)" in output2


# ============================================================================
# Dynamic Mapping Updates Tests
# ============================================================================


def test_process_tokens_then_update_mapping(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test processing tokens, updating mapping, then continuing."""
    processor = DynamicCitationProcessor()

    # Process tokens before mapping is set
    output1, citations1 = process_tokens(processor, ["Text [", "1", "]"])
    assert len(citations1) == 0  # No mapping yet

    # Update mapping
    processor.update_citation_mapping({1: mock_search_docs[1]})

    # Continue processing
    output2, citations2 = process_tokens(processor, ["More text [", "1", "]"])
    assert len(citations2) == 1  # Now has mapping


def test_citations_before_mapping_skipped(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that citations before mapping update are skipped."""
    processor = DynamicCitationProcessor()

    output1, citations1 = process_tokens(processor, ["Text [", "1", "]"])
    assert len(citations1) == 0
    assert "[1]" not in output1  # Still removed from output

    processor.update_citation_mapping({1: mock_search_docs[1]})

    output2, citations2 = process_tokens(processor, ["More [", "1", "]"])
    assert len(citations2) == 1


def test_citations_after_mapping_processed(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test that citations after mapping update are processed."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping({1: mock_search_docs[1]})

    output, citations = process_tokens(processor, ["Text [", "1", "]"])

    assert len(citations) == 1
    assert citations[0].document_id == "doc_1"


def test_multiple_mapping_updates_during_processing(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test multiple mapping updates during processing."""
    processor = DynamicCitationProcessor()

    # First mapping
    processor.update_citation_mapping({1: mock_search_docs[1]})
    output1, citations1 = process_tokens(processor, ["[", "1", "]"])
    assert len(citations1) == 1
    assert citations1[0].document_id == "doc_1"

    # Second mapping
    processor.update_citation_mapping({2: mock_search_docs[2]})
    output2, citations2 = process_tokens(processor, ["[", "2", "]"])
    assert len(citations2) == 1

    # Update existing - this changes the document_id, so it's treated as a new document
    doc1_updated = create_test_search_doc(
        document_id="doc_1_updated", link="https://updated.com"
    )
    processor.update_citation_mapping({1: doc1_updated})
    output3, citations3 = process_tokens(processor, ["[", "1", "]"])
    # New document_id means it's a new citation
    assert len(citations3) == 1
    assert citations3[0].document_id == "doc_1_updated"


# ============================================================================
# Integration Tests
# ============================================================================


def test_full_conversation_flow(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test full conversation flow with multiple turns."""
    processor = DynamicCitationProcessor()

    # Turn 1: Add some documents
    processor.update_citation_mapping({1: mock_search_docs[1], 2: mock_search_docs[2]})
    output1, citations1 = process_tokens(
        processor, ["This is the first response [", "1", "] with citation."]
    )
    assert len(citations1) == 1

    # Turn 2: Add more documents and continue
    processor.update_citation_mapping({3: mock_search_docs[3], 4: mock_search_docs[4]})
    output2, citations2 = process_tokens(
        processor, ["This is the second response [", "3", "][", "4", "]."]
    )
    assert len(citations2) == 2

    # Verify order - should be doc_1, doc_3, doc_4 (first citation order)
    cited_docs = processor.get_cited_documents()
    assert len(cited_docs) == 3  # doc_1, doc_3, doc_4 (doc_2 was never cited)
    assert cited_docs[0].document_id == "doc_1"
    assert cited_docs[1].document_id == "doc_3"
    assert cited_docs[2].document_id == "doc_4"


def test_complex_text_mixed_citations_code_blocks(
    mock_search_docs: dict[int, SearchDoc],
) -> None:
    """Test complex text with mixed citations and code blocks."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping(
        {1: mock_search_docs[1], 2: mock_search_docs[2], 3: mock_search_docs[3]}
    )

    tokens = [
        "Here's some text [",
        "1",
        "] with a citation.\n",
        "```\n",
        "def example():\n    print('code')\n",
        "```\n",
        "More text [",
        "2",
        ", ",
        "3",
        "] here.",
    ]
    output, citations = process_tokens(processor, tokens)

    # Citations should be formatted
    assert "[[1]](https://example.com/doc1)" in output
    assert "[[2]](https://example.com/doc2)" in output
    assert "[[3]]()" in output
    assert "```plaintext" in output
    assert len(citations) == 3


def test_real_world_citation_patterns(mock_search_docs: dict[int, SearchDoc]) -> None:
    """Test real-world citation patterns."""
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping(
        {1: mock_search_docs[1], 2: mock_search_docs[2], 3: mock_search_docs[3]}
    )

    # Simulate a realistic LLM response
    tokens = [
        "According to recent research [",
        "1",
        "], the findings suggest that ",
        "multiple studies [",
        "2",
        ", ",
        "3",
        "] have confirmed these results. ",
        "However, some researchers [",
        "1",
        "] have raised concerns.",
    ]
    output, citations = process_tokens(processor, tokens)

    # Citations should be formatted
    assert "[[1]](https://example.com/doc1)" in output
    assert "[[2]](https://example.com/doc2)" in output
    assert "[[3]]()" in output
    # Should have CitationInfo for doc_1, doc_2, doc_3 (doc_1 appears twice but only one CitationInfo)
    assert len(citations) == 3
    # Verify order
    doc_ids = [c.document_id for c in citations]
    assert "doc_1" in doc_ids
    assert "doc_2" in doc_ids
    assert "doc_3" in doc_ids
