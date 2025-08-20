from datetime import datetime

import pytest

from onyx.chat.models import LlmDoc
from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.stream_processing.citation_processing import CitationProcessor
from onyx.chat.stream_processing.utils import DocumentIdOrderMapping
from onyx.configs.constants import DocumentSource
from onyx.server.query_and_chat.streaming_models import CitationInfo


"""
This module contains tests for the citation extraction functionality in Onyx.

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


@pytest.fixture
def mock_data() -> tuple[list[LlmDoc], dict[str, int]]:
    return mock_docs, mock_doc_mapping


def process_text(
    tokens: list[str], mock_data: tuple[list[LlmDoc], dict[str, int]]
) -> tuple[str, list[CitationInfo]]:
    mock_docs, mock_doc_id_to_rank_map = mock_data
    final_mapping = DocumentIdOrderMapping(order_mapping=mock_doc_id_to_rank_map)
    display_mapping = DocumentIdOrderMapping(order_mapping=mock_doc_id_to_rank_map)
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
            "Citation at very end",
            ["Test! ", "[", "1", "]"],
            "Test! [[1]](https://0.com)",
            ["doc_0"],
        ),
        (
            "Citations with part of next citation",
            ["Test [", "1]", "[3][", "5]"],
            "Test [[1]](https://0.com)[[2]]()[[3]](https://2.com)",
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
            "Multiple citations in one sentence",
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
            "Consecutive identical citations",
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
        (
            "Citations with extraneous citations, split up completely",
            [
                "[[1]]",
                "(",
                "https://0.com",
                ") Citation at ",
                "the beginning. ",
            ],
            "[[1]](https://0.com) Citation at the beginning. ",
            ["doc_0"],
        ),
        (
            "Code block without language specification",
            [
                "Here's",
                " a code block",
                ":\n```\nd",
                "ef example():\n    pass\n",
                "```\n",
                "End of code.",
            ],
            "Here's a code block:\n```plaintext\ndef example():\n    pass\n```\nEnd of code.",
            [],
        ),
        (
            "Code block with language specification",
            [
                "Here's a Python code block:\n",
                "```",
                "python",
                "\n",
                "def greet",
                "(name):",
                "\n    ",
                "print",
                "(f'Hello, ",
                "{name}!')",
                "\n",
                "greet('World')",
                "\n```\n",
                "This function ",
                "greets the user.",
            ],
            "Here's a Python code block:\n```python\ndef greet(name):\n    "
            "print(f'Hello, {name}!')\ngreet('World')\n```\nThis function greets the user.",
            [],
        ),
        (
            "Multiple code blocks with different languages",
            [
                "JavaScript example:\n",
                "```",
                "javascript",
                "\n",
                "console",
                ".",
                "log",
                "('Hello, World!');",
                "\n```\n",
                "Python example",
                ":\n",
                "```",
                "python",
                "\n",
                "print",
                "('Hello, World!')",
                "\n```\n",
                "Both print greetings",
                ".",
            ],
            "JavaScript example:\n```javascript\nconsole.log('Hello, World!');\n"
            "```\nPython example:\n```python\nprint('Hello, World!')\n"
            "```\nBoth print greetings.",
            [],
        ),
        (
            "Code block with text block",
            [
                "Here's a code block with a text block:\n",
                "```\n",
                "# This is a comment",
                "\n",
                "x = 10  # This assigns 10 to x\n",
                "print",
                "(x)  # This prints x",
                "\n```\n",
                "The code demonstrates variable assignment.",
            ],
            "Here's a code block with a text block:\n"
            "```plaintext\n"
            "# This is a comment\n"
            "x = 10  # This assigns 10 to x\n"
            "print(x)  # This prints x\n"
            "```\n"
            "The code demonstrates variable assignment.",
            [],
        ),
        (
            "Long JSON string in code block",
            [
                "```json\n{",
                '"name": "John Doe",',
                '"age": 30,',
                '"city": "New York",',
                '"hobbies": ["reading", "swimming", "cycling"],',
                '"education": {',
                '    "degree": "Bachelor\'s",',
                '    "major": "Computer Science",',
                '    "university": "Example University"',
                "}",
                "}\n```",
            ],
            '```json\n{"name": "John Doe","age": 30,"city": "New York","hobbies": '
            '["reading", "swimming", "cycling"],"education": {    '
            '"degree": "Bachelor\'s",    "major": "Computer Science",    "university": "Example University"}}\n```',
            [],
        ),
        (
            "Citation as a single token",
            [
                "Here is some text",
                "[1]",
                ".",
                " Some other text",
            ],
            "Here is some text[[1]](https://0.com). Some other text",
            ["doc_0"],
        ),
        (
            "Comma-separated citations",
            ["Here is some text [", "1", ",", " ", "3", "]", "."],
            "Here is some text [[1]](https://0.com)[[2]]().",
            ["doc_0", "doc_1"],
        ),
        (
            "Comma-separated citations without space",
            ["Test [", "1", ",", "3", "]", " end."],
            "Test [[1]](https://0.com)[[2]]() end.",
            ["doc_0", "doc_1"],
        ),
        (
            "Comma-separated citations with multiple numbers",
            ["Multiple refs [", "1,", " ", "3", ", ", "5", "]", "."],
            "Multiple refs [[1]](https://0.com)[[2]]()[[3]](https://2.com).",
            ["doc_0", "doc_1", "doc_2"],
        ),
        (
            "Mixed single and comma-separated citations",
            ["Single [", "2", "]", " and multiple [", "1", ",3]"],
            "Single [[1]](https://0.com) and multiple [[1]](https://0.com)[[2]]()",
            ["doc_0", "doc_1"],
        ),
        (
            "Mixed single and comma-separated citations",
            ["Single [", "2", "]", " tex", "t [", "1", ",3]."],
            "Single [[1]](https://0.com) text [[1]](https://0.com)[[2]]().",
            ["doc_0", "doc_1"],
        ),
        (
            "Comma-separated citation as single token",
            ["Text ", "[1, 3,5]", " end."],
            "Text [[1]](https://0.com)[[2]]()[[3]](https://2.com) end.",
            ["doc_0", "doc_1", "doc_2"],
        ),
        (
            "Comma-separated repeated citations",
            [
                "Test! ",
                "[",
                "1",
                "]",
                ". And so",
                "me more ",
                "[",
                "2",
                ",",
                "3",
                "]",
                ".",
            ],
            "Test! [[1]](https://0.com). And some more [[1]](https://0.com)[[2]]().",
            ["doc_0", "doc_1"],
        ),
        (
            "Comma-separated Consecutive identical citations",
            ["Here is some text ", "[1, 2, 4,", "3, 1]", " end."],
            "Here is some text [[1]](https://0.com)[[2]]() end.",
            ["doc_0", "doc_1"],
        ),
        (
            "Mixed valid and invalid comma-separated citations",
            ["Here is some text ", "[1, 100, 4, 500]", " end."],
            "Here is some text [[1]](https://0.com)[100][[2]]()[500] end.",
            ["doc_0", "doc_1"],
        ),
        (
            "Invalid comma-separated citations",
            ["Some text ", "[1, and 2]"],
            "Some text [1, and 2]",
            [],
        ),
        (
            "Comma-separated citations with various token splits",
            [
                "Text [3, 7]",
                " padding [",
                "1",
                ",",
                " ",
                "3",
                ",",
                "7",
                "]",
                " padding ",
                "[",
                "3,",
                " 7]",
            ],
            "Text [[2]]()[[4]]() padding [[1]](https://0.com)[[2]]()[[4]]() padding [[2]]()[[4]]()",
            ["doc_1", "doc_3", "doc_0"],
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
