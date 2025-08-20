from datetime import datetime

import pytest

from onyx.chat.models import LlmDoc
from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.stream_processing.citation_processing import CitationProcessor
from onyx.chat.stream_processing.utils import DocumentIdOrderMapping
from onyx.configs.constants import DocumentSource
from onyx.server.query_and_chat.streaming_models import CitationInfo


"""
This module contains tests for the citation extraction functionality in Onyx,
specifically the substitution of the number of document cited in the UI. (The LLM
will see the sources post re-ranking and relevance check, the UI before these steps.)
This module is a derivative of test_citation_processing.py.

The tests focusses specifically on the substitution of the number of document cited in the UI.

Key components:
- mock_docs: A list of mock LlmDoc objects used for testing.
- mock_doc_mapping: A dictionary mapping document IDs to their initial ranks.
- mock_doc_mapping_rerank: A dictionary mapping document IDs to their ranks after re-ranking/relevance check.
- process_text: A helper function that simulates the citation extraction process.
- test_citation_extraction: A parametrized test function covering various citation scenarios.

To add new test cases:
1. Add a new tuple to the @pytest.mark.parametrize decorator of test_citation_extraction.
2. Each tuple should contain:
   - A descriptive test name (string)
   - Input tokens (list of strings)
   - Expected output text (string)
   - Expected citations (list of document IDs)
"""


mock_docs = [
    LlmDoc(
        document_id=f"doc_{int(id/2)}",
        content="Document is a doc",
        blurb=f"Document #{id}",
        semantic_identifier=f"Doc {id}",
        source_type=DocumentSource.WEB,
        metadata={},
        updated_at=datetime.now(),
        link=f"https://{int(id/2)}.com" if int(id / 2) % 2 == 0 else None,
        source_links={0: "https://mintlify.com/docs/settings/broken-links"},
        match_highlights=[],
    )
    for id in range(10)
]

mock_doc_mapping = {
    "doc_0": 1,
    "doc_1": 2,
    "doc_2": 3,
    "doc_3": 4,
    "doc_4": 5,
    "doc_5": 6,
}

mock_doc_mapping_rerank = {
    "doc_0": 2,
    "doc_1": 1,
    "doc_2": 4,
    "doc_3": 3,
    "doc_4": 6,
    "doc_5": 5,
}


@pytest.fixture
def mock_data() -> tuple[list[LlmDoc], dict[str, int], dict[str, int]]:
    return mock_docs, mock_doc_mapping, mock_doc_mapping_rerank


def process_text(
    tokens: list[str], mock_data: tuple[list[LlmDoc], dict[str, int], dict[str, int]]
) -> tuple[str, list[CitationInfo]]:
    mock_docs, mock_doc_id_to_rank_map, mock_doc_id_to_rank_map_rerank = mock_data
    final_mapping = DocumentIdOrderMapping(order_mapping=mock_doc_id_to_rank_map)
    display_mapping = DocumentIdOrderMapping(
        order_mapping=mock_doc_id_to_rank_map_rerank
    )
    processor = CitationProcessor(
        context_docs=mock_docs,
        final_doc_id_to_rank_map=final_mapping,
        display_doc_id_to_rank_map=display_mapping,
        stop_stream=None,
    )

    result: list[OnyxAnswerPiece | CitationInfo] = []
    for token in tokens:
        result.extend(processor.process_token(token))
    result.extend(processor.process_token(None))

    final_answer_text = ""
    citations = []
    for piece in result:
        if isinstance(piece, OnyxAnswerPiece):
            final_answer_text += piece.answer_piece or ""
        elif isinstance(piece, CitationInfo):
            citations.append(piece)

    return final_answer_text, citations


@pytest.mark.parametrize(
    "test_name, input_tokens, expected_text, expected_citations",
    [
        (
            "Single citation",
            ["Gro", "wth! [", "1", "]", "."],
            "Growth! [[2]](https://0.com).",
            ["doc_0"],
        ),
    ],
)
def test_citation_substitution(
    mock_data: tuple[list[LlmDoc], dict[str, int], dict[str, int]],
    test_name: str,
    input_tokens: list[str],
    expected_text: str,
    expected_citations: list[str],
) -> None:
    final_answer_text, citations = process_text(input_tokens, mock_data)
    assert (
        final_answer_text.strip() == expected_text.strip()
    ), f"Test '{test_name}' failed: Final answer text does not match expected output."
    assert [
        citation.document_id for citation in citations
    ] == expected_citations, (
        f"Test '{test_name}' failed: Citations do not match expected output."
    )
