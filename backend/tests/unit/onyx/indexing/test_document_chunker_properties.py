"""Property tests for text chunking: connectors send sections of any size and
shape, and search finds only the text that some chunk holds."""

from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from onyx.configs.constants import SECTION_SEPARATOR
from onyx.connectors.models import Section, SectionType
from onyx.indexing.chunking import text_section_chunker as text_chunker_module
from onyx.utils.text_processing import clean_text
from tests.unit.onyx.indexing.test_document_chunker import (
    CharTokenizer,
    _make_doc,
    _make_document_chunker,
)

_PIECES = st.sampled_from(
    [
        "word",
        "Word",
        " ",
        "  ",
        ". ",
        "! ",
        "? ",
        ".",
        "\n",
        "\n\n",
        "\t",
        "é",
        "中文",
        "😀",
        "a" * 30,
        "x\x00y",
        "\x0b",
    ]
)
_TEXT = st.lists(_PIECES, min_size=1, max_size=20).map("".join)


def _chunk_texts(sections: list[str], limit: int) -> list[str]:
    doc = _make_doc(
        sections=[
            Section(type=SectionType.TEXT, text=text, link=f"l{index}")
            for index, text in enumerate(sections)
        ],
        title=None,
    )
    chunks = _make_document_chunker(limit).chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=limit,
    )
    return [chunk.content for chunk in chunks]


def _run_end(chunk: str, texts: list[str], index: int) -> int | None:
    """The index after the run of whole sections from `index` that `chunk`
    joins with SECTION_SEPARATOR, or None if it is not such a run."""
    rest = chunk
    while index < len(texts) and rest.startswith(texts[index]):
        rest = rest[len(texts[index]) :]
        index += 1
        if not rest:
            return index
        if not rest.startswith(SECTION_SEPARATOR):
            return None
        rest = rest[len(SECTION_SEPARATOR) :]
    return None


def _assert_covers(sections: list[str], chunks: list[str]) -> None:
    """The chunks hold the cleaned sections in order with nothing lost or
    added: each chunk is a run of whole sections joined by SECTION_SEPARATOR,
    or the next piece of one section that is too large for a chunk. A buffer
    of whitespace only is not indexed."""
    texts = [text for text in map(clean_text, sections) if text]
    index, offset = 0, 0
    for chunk in chunks:
        while True:
            assert index < len(texts), f"extra chunk {chunk!r}"
            end = _run_end(chunk, texts, index) if offset == 0 else None
            if end is not None:
                index = end
                break
            if texts[index].startswith(chunk, offset):
                offset += len(chunk)
                if offset == len(texts[index]):
                    index, offset = index + 1, 0
                break
            # A whole section of whitespace only can be left out.
            assert offset == 0 and not texts[index].strip(), (
                chunk,
                texts[index][offset:],
            )
            index += 1
    assert offset == 0, texts[index][offset:]
    assert all(not text.strip() for text in texts[index:]), texts[index:]


@settings(max_examples=150, deadline=None, derandomize=True)
@given(
    sections=st.lists(_TEXT, max_size=6),
    limit=st.integers(8, 80),
    strict=st.booleans(),
)
def test_chunks_cover_the_sections_in_order(
    sections: list[str], limit: int, strict: bool
) -> None:
    with patch.object(text_chunker_module, "STRICT_CHUNK_TOKEN_LIMIT", strict):
        chunks = _chunk_texts(sections, limit)

    _assert_covers(sections, [chunk for chunk in chunks if chunk])


@settings(max_examples=150, deadline=None, derandomize=True)
@given(sections=st.lists(_TEXT, max_size=6), limit=st.integers(8, 80))
def test_strict_chunks_stay_within_the_token_limit(
    sections: list[str], limit: int
) -> None:
    with patch.object(text_chunker_module, "STRICT_CHUNK_TOKEN_LIMIT", True):
        chunks = _chunk_texts(sections, limit)

    tokenizer = CharTokenizer()
    assert all(len(tokenizer.encode(chunk)) <= limit for chunk in chunks)
