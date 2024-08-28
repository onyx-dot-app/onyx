from datetime import datetime

import pytest

from danswer.chat.models import CitationInfo
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import LlmDoc
from danswer.configs.constants import DocumentSource
from danswer.llm.answering.stream_processing.citation_processing import (
    extract_citations_from_stream,
)
from danswer.llm.answering.stream_processing.utils import DocumentIdOrderMapping


"""
This module contains tests for the citation extraction functionality in Danswer.

The tests focus on the `extract_citations_from_stream` function, which processes
a stream of tokens and extracts citations, replacing them with properly formatted
versions including links where available.

Key components:
- mock_docs: A list of mock LlmDoc objects used for testing.
- mock_doc_mapping: A dictionary mapping document IDs to their ranks.
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


@pytest.fixture
def mock_data() -> tuple[list[LlmDoc], dict[str, int]]:
    return mock_docs, mock_doc_mapping


def process_text(
    tokens: list[str], mock_data: tuple[list[LlmDoc], dict[str, int]]
) -> tuple[str, list[CitationInfo]]:
    mock_docs, mock_doc_id_to_rank_map = mock_data
    mapping = DocumentIdOrderMapping(order_mapping=mock_doc_id_to_rank_map)
    result = list(
        extract_citations_from_stream(
            tokens=iter(tokens),
            context_docs=mock_docs,
            doc_id_to_rank_map=mapping,
            stop_stream=None,
        )
    )
    final_answer_text = ""
    citations = []
    for piece in result:
        if isinstance(piece, DanswerAnswerPiece):
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
            "Growth! [[1]](https://0.com).",
            ["doc_0"],
        ),
        (
            "Repeated citations",
            ["Test! ", "[", "1", "]", ". And so", "me more ", "[", "2", "]", "."],
            "Test! [[1]](https://0.com). And some more [[1]](https://0.com).",
            ["doc_0"],
        ),
        (
            "Citations at sentence boundaries",
            [
                "Citation at the ",
                "end of a sen",
                "tence.",
                "[",
                "2",
                "]",
                " Another sen",
                "tence.",
                "[",
                "4",
                "]",
            ],
            "Citation at the end of a sentence.[[1]](https://0.com) Another sentence.[[2]]()",
            ["doc_0", "doc_1"],
        ),
        (
            "Citations at beginning, middle, and end",
            [
                "[",
                "1",
                "]",
                " Citation at ",
                "the beginning. ",
                "[",
                "3",
                "]",
                " In the mid",
                "dle. At the end ",
                "[",
                "5",
                "]",
                ".",
            ],
            "[[1]](https://0.com) Citation at the beginning. [[2]]() In the middle. At the end [[3]](https://2.com).",
            ["doc_0", "doc_1", "doc_2"],
        ),
        (
            "Mixed valid and invalid citations",
            [
                "Mixed valid and in",
                "valid citations ",
                "[",
                "1",
                "]",
                "[",
                "99",
                "]",
                "[",
                "3",
                "]",
                "[",
                "100",
                "]",
                "[",
                "5",
                "]",
                ".",
            ],
            "Mixed valid and invalid citations [[1]](https://0.com)[99][[2]]()[100][[3]](https://2.com).",
            ["doc_0", "doc_1", "doc_2"],
        ),
        (
            "Hardest!",
            [
                "Multiple cit",
                "ations in one ",
                "sentence [",
                "1",
                "]",
                "[",
                "4",
                "]",
                "[",
                "5",
                "]",
                ". ",
            ],
            "Multiple citations in one sentence [[1]](https://0.com)[[2]]()[[3]](https://2.com).",
            ["doc_0", "doc_1", "doc_2"],
        ),
        (
            "Repeated citations with text",
            ["[", "1", "]", "Aasf", "asda", "sff  ", "[", "1", "]", " ."],
            "[[1]](https://0.com)Aasfasdasff  [[1]](https://0.com) .",
            ["doc_0"],
        ),
        (
            "Consecutive identical citations!",
            [
                "Citations [",
                "1",
                "]",
                "[",
                "1]",
                "",
                "[2",
                "",
                "]",
                ". ",
            ],
            "Citations [[1]](https://0.com).",
            ["doc_0"],
        ),
        (
            "Consecutive identical citations!",
            [
                "test [1]tt[1]t",
                "",
            ],
            "test [[1]](https://0.com)ttt",
            ["doc_0"],
        ),
        (
            "Consecutive identical citations!",
            [
                "test [1]t[1]t[1]",
                "",
            ],
            "test [[1]](https://0.com)tt",
            ["doc_0"],
        ),
        (
            "Repeated citations with text",
            ["[", "1", "]", "Aasf", "asda", "sff  ", "[", "1", "]", " ."],
            "[[1]](https://0.com)Aasfasdasff  [[1]](https://0.com) .",
            ["doc_0"],
        ),
        (
            "Repeated citations with text",
            ["[1][", "1", "]t", "[2]"],
            "[[1]](https://0.com)t",
            ["doc_0"],
        ),
        (
            "Repeated citations with text",
            ["[1][", "1", "]t]", "[2]"],
            "[[1]](https://0.com)t]",
            ["doc_0"],
        ),
        (
            "Repeated citations with text",
            ["[1][", "3", "]t]", "[2]"],
            "[[1]](https://0.com)[[2]]()t]",
            ["doc_0", "doc_1"],
        ),
        (
            "Repeated citations with text",
            ["[1", "][", "3", "]t]", "[2]"],
            "[[1]](https://0.com)[[2]]()t]",
            ["doc_0", "doc_1"],
        ),
        (
            "Citations with extraneous citations",
            [
                "[[1]](https://0.com) Citation",
                " at ",
                "the beginning. ",
                "[",
                "3",
                "]",
                " In the mid",
                "dle. At the end ",
                "[",
                "5",
                "]",
                ".",
            ],
            "[[1]](https://0.com) Citation at the beginning. [[2]]() In the middle. At the end [[3]](https://2.com).",
            ["doc_0", "doc_1", "doc_2"],
        ),
        (
            "Citations with extraneous citations, split up",
            [
                "[[1]](",
                "https://0.com) Citation at ",
                "the beginning. ",
            ],
            "[[1]](https://0.com) Citation at the beginning. ",
            ["doc_0"],
        ),
    ],
)
def test_citation_extraction(
    mock_data: tuple[list[LlmDoc], dict[str, int]],
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
