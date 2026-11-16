"""Property tests for the streaming citation processor: the model output can split
anywhere, and markdown full of brackets, digits and code fences is common."""

from typing import NamedTuple

from hypothesis import example, given, settings
from hypothesis import strategies as st

from onyx.chat.citation_processor import CitationMapping, DynamicCitationProcessor
from onyx.chat.models import CitationMode
from onyx.server.query_and_chat.streaming_models import CitationInfo
from tests.unit.onyx.chat.test_citation_processor import create_test_search_doc

_DOCS: CitationMapping = {
    number: create_test_search_doc(
        document_id=f"doc_{number}", link=f"https://example.com/{number}"
    )
    for number in (1, 2, 3)
}
# The second number points at the same document as the first.
_DOCS[4] = _DOCS[1]

_PROSE = st.sampled_from(
    [
        "word",
        " ",
        "  ",
        "\n",
        "\n\n",
        ".",
        ",",
        "!",
        "(",
        ")",
        "1",
        "42",
        "é",
        "中文",
        "`x`",
        "``",
        "a[b]",
        "[x]",
        "[ ]",
        "[]",
        "[1,]",
        "[1 2]",
        "[",
        "]",
        "【",
        "］",
        "]]",
        "[[",
        "- ",
        "1. ",
        "> ",
        "    ",
        "\t",
    ]
)
_CITATION = st.sampled_from(
    [
        "[1]",
        "[2]",
        "[4]",
        "[99]",
        "[1, 2]",
        "[1,3]",
        "[2, 99, 3]",
        "[[1]]",
        "[[3]]",
        "【1】",
        "［2］",
        "【【3】】",
    ]
)
# A citation in an info string is code: the line opens a block.
_FENCE = st.sampled_from(["```", "```py", "````", "~~~", "``` [1]", "~~~ [2] `"])


@st.composite
def _code_block(draw: st.DrawFn) -> str:
    fence = draw(_FENCE)
    body = draw(st.lists(st.one_of(_PROSE, _CITATION), max_size=8))
    # A body line that starts with a fence character could close the block.
    lines = [line.lstrip("`~ \t") for line in "".join(body).split("\n")]
    closing = fence.split(" ")[0].rstrip("py")
    return f"\n{fence}\n" + "\n".join(lines) + f"\n{closing}\n"


_MARKDOWN = st.lists(
    st.one_of(_PROSE, _PROSE, _CITATION, _FENCE, _code_block()), max_size=24
).map("".join)
_MODES = st.sampled_from(list(CitationMode))


class _Result(NamedTuple):
    text: str
    citations: list[CitationInfo]
    seen: list[int]
    cited: list[str]


def _run(chunks: list[str], mode: CitationMode) -> _Result:
    processor = DynamicCitationProcessor(citation_mode=mode, stop_stream=None)
    processor.update_citation_mapping(_DOCS)
    text: list[str] = []
    citations: list[CitationInfo] = []
    for token in [*chunks, None]:
        for result in processor.process_token(token):
            if isinstance(result, str):
                text.append(result)
            else:
                citations.append(result)
    return _Result(
        "".join(text),
        citations,
        sorted(processor.get_seen_citations()),
        processor.get_cited_document_ids(),
    )


def _comparable(result: _Result, mode: CitationMode) -> _Result:
    # REMOVE also tidies the spaces around a removed marker, and it cannot take
    # back a space that it already streamed. Only that spacing can differ.
    if mode != CitationMode.REMOVE:
        return result
    return result._replace(text="".join(result.text.split()))


def _split(text: str, cuts: list[int]) -> list[str]:
    points = sorted({cut % (len(text) + 1) for cut in cuts})
    return [
        text[start:end]
        for start, end in zip([0, *points], [*points, len(text)], strict=True)
    ]


@settings(max_examples=200, deadline=None, derandomize=True)
@given(
    text=_MARKDOWN,
    cuts=st.lists(st.integers(0, 10_000), max_size=12),
    mode=_MODES,
)
# A double bracket citation split before its last bracket.
@example(text="See [[1]] now", cuts=[6, 7, 8, 9], mode=CitationMode.HYPERLINK)
@example(text="See [[1]] now", cuts=[8], mode=CitationMode.HYPERLINK)
@example(text="See 【【1】】 now", cuts=[8], mode=CitationMode.HYPERLINK)
# A citation at the start of a token gets its leading space.
@example(text="word[1][2] end", cuts=[4, 7, 10], mode=CitationMode.HYPERLINK)
def test_output_does_not_depend_on_chunk_boundaries(
    text: str, cuts: list[int], mode: CitationMode
) -> None:
    whole = _comparable(_run([text], mode), mode)

    assert _comparable(_run(_split(text, cuts), mode), mode) == whole
    assert _comparable(_run(list(text), mode), mode) == whole


_CITATION_PATTERN = DynamicCitationProcessor().citation_pattern
_PLAIN_PROSE = (
    st.lists(_PROSE, max_size=6)
    .map("".join)
    .filter(
        lambda text: (
            not _CITATION_PATTERN.search(text)
            and "```" not in text
            and "~~~" not in text
        )
    )
)
# Code blocks start and end with a newline, so no marker spans a block edge.
_PLAIN = st.lists(st.tuples(_PLAIN_PROSE, _code_block()), max_size=4).map(
    lambda parts: "".join(prose + code for prose, code in parts)
)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(text=_PLAIN, cuts=st.lists(st.integers(0, 10_000), max_size=8), mode=_MODES)
# A citation in a fence info string, streamed one character at a time.
@example(
    text="```text [1]\ncode\n```\n",
    cuts=list(range(1, 21)),
    mode=CitationMode.HYPERLINK,
)
# The fence ends the list item's block and opens a new one.
@example(
    text="- ```\n``` [1]\ncode\n```\n",
    cuts=list(range(1, 23)),
    mode=CitationMode.HYPERLINK,
)
def test_text_without_citations_outside_code_passes_through(
    text: str, cuts: list[int], mode: CitationMode
) -> None:
    # Citation markers appear only inside fenced code blocks here.
    output, citations, seen, cited = _run(_split(text, cuts), mode)

    assert output == text
    assert citations == []
    assert seen == []
    assert cited == []
