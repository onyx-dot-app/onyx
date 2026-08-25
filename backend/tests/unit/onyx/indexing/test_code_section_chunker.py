import pytest
from chonkie import SentenceChunker

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import (
    CodeSection,
    IndexingDocument,
    Section,
    TextSection,
)
from onyx.indexing.chunking import DocumentChunker
from onyx.indexing.chunking.code_section_chunker import _line_anchored_link
from onyx.natural_language_processing.utils import BaseTokenizer


class CharTokenizer(BaseTokenizer):
    """1 character == 1 token. Deterministic & trivial to reason about."""

    def encode(self, string: str) -> list[int]:
        return [ord(c) for c in string]

    def tokenize(self, string: str) -> list[str]:
        return list(string)

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(t) for t in tokens)


CHUNK_LIMIT = 200


def _make_document_chunker(
    chunk_token_limit: int = CHUNK_LIMIT,
    with_mini_chunks: bool = False,
) -> DocumentChunker:
    def token_counter(text: str) -> int:
        return len(text)

    return DocumentChunker(
        tokenizer=CharTokenizer(),
        blurb_splitter=SentenceChunker(
            tokenizer_or_token_counter=token_counter,
            chunk_size=128,
            chunk_overlap=0,
            return_type="texts",
        ),
        chunk_splitter=SentenceChunker(
            tokenizer_or_token_counter=token_counter,
            chunk_size=chunk_token_limit,
            chunk_overlap=0,
            return_type="texts",
        ),
        mini_chunk_splitter=(
            SentenceChunker(
                tokenizer_or_token_counter=token_counter,
                chunk_size=150,
                chunk_overlap=0,
                return_type="texts",
            )
            if with_mini_chunks
            else None
        ),
    )


def _make_doc(sections: list[Section], doc_id: str = "doc1") -> IndexingDocument:
    return IndexingDocument(
        id=doc_id,
        source=DocumentSource.GITLAB,
        semantic_identifier=doc_id,
        title="pkg/mod.py",
        metadata={},
        sections=[],  # real sections unused — method reads processed_sections
        processed_sections=sections,
    )


def _make_python_code(num_functions: int, body_width: int = 30) -> str:
    lines: list[str] = []
    for i in range(num_functions):
        lines.append(f"def func_{i}(x):")
        lines.append(f"    y = x * {i}")
        lines.append("    return y + " + " + ".join(str(j) for j in range(body_width)))
        lines.append("")
    return "\n".join(lines)


def _chunk(dc: DocumentChunker, sections: list[Section]) -> list:
    doc = _make_doc(sections)
    return dc.chunk(
        document=doc,
        sections=sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )


# --- Whole-file fits ------------------------------------------------------------


def test_small_code_section_is_one_chunk_with_fields() -> None:
    dc = _make_document_chunker()
    code = "def f(x):\n    return x + 1\n"
    section = CodeSection(
        text=code,
        language="python",
        file_path="pkg/mod.py",
        link="https://git.example.com/repo/-/blob/main/pkg/mod.py",
    )

    chunks = _chunk(dc, [section])

    assert len(chunks) == 1
    assert chunks[0].content == code
    assert chunks[0].source_links == {
        0: "https://git.example.com/repo/-/blob/main/pkg/mod.py"
    }


# --- Syntax-boundary splitting ---------------------------------------------------


def test_oversized_code_splits_at_function_boundaries() -> None:
    dc = _make_document_chunker()
    code = _make_python_code(num_functions=12)
    section = CodeSection(
        text=code,
        language="python",
        file_path="pkg/mod.py",
        link="https://git.example.com/blob/main/pkg/mod.py",
    )

    chunks = _chunk(dc, [section])

    assert len(chunks) > 1
    for chunk in chunks:
        # Every chunk starts at a function boundary, not mid-function.
        assert chunk.content.strip("\n").startswith("def func_")
        assert len(chunk.content) <= CHUNK_LIMIT


def test_line_anchors_point_at_chunk_start_lines() -> None:
    dc = _make_document_chunker()
    code = _make_python_code(num_functions=12)
    lines = code.split("\n")
    section = CodeSection(
        text=code,
        language="python",
        file_path="pkg/mod.py",
        link="https://git.example.com/blob/main/pkg/mod.py",
    )

    chunks = _chunk(dc, [section])

    assert len(chunks) > 1
    for chunk in chunks:
        link = chunk.source_links[0]
        assert "#L" in link
        start_line = int(link.split("#L")[1].split("-")[0])
        # 1-based line number must point at the chunk's first code line.
        assert lines[start_line - 1] == chunk.content.strip("\n").split("\n")[0]


def test_unknown_language_falls_back_to_token_splitting() -> None:
    dc = _make_document_chunker()
    # A made-up language forces the tree-sitter lookup to fail.
    code = "x " * 300
    section = CodeSection(
        text=code,
        language="not_a_language",
        file_path="weird.xyz",
        link="https://git.example.com/blob/main/weird.xyz",
    )

    chunks = _chunk(dc, [section])

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.content) <= CHUNK_LIMIT


# --- Interaction with other sections ----------------------------------------------


def test_prose_buffer_flushes_before_code() -> None:
    """Prose accumulated before a code section becomes its own chunk — code
    never merges with buffered text."""
    dc = _make_document_chunker()
    prose = TextSection(text="Some short prose.", link="prose-link")
    code = CodeSection(
        text="def f():\n    return 1\n",
        language="python",
        file_path="a.py",
        link="code-link",
    )

    chunks = _chunk(dc, [prose, code])

    assert len(chunks) == 2
    assert chunks[0].content == "Some short prose."
    assert chunks[1].content == "def f():\n    return 1\n"


def test_code_chunks_have_no_mini_chunks() -> None:
    dc = _make_document_chunker(with_mini_chunks=True)
    prose = TextSection(text="Some short prose.", link="prose-link")
    code = CodeSection(
        text="def f():\n    return 1\n",
        language="python",
        file_path="a.py",
        link="code-link",
    )

    chunks = _chunk(dc, [prose, code])

    assert chunks[0].mini_chunk_texts is not None
    assert chunks[1].mini_chunk_texts is None


# --- Link anchoring helper ---------------------------------------------------------


@pytest.mark.parametrize(
    "link,start,end,expected",
    [
        ("https://x/blob/main/a.py", 5, 9, "https://x/blob/main/a.py#L5-L9"),
        ("https://x/blob/main/a.py", 5, 5, "https://x/blob/main/a.py#L5"),
        ("https://x/a.py#L1", 5, 9, "https://x/a.py#L1"),  # existing fragment kept
        ("", 5, 9, ""),
    ],
)
def test_line_anchored_link(link: str, start: int, end: int, expected: str) -> None:
    assert _line_anchored_link(link, start, end) == expected


# --- Sensitive-format exclusion ---------------------------------------------------


def test_sensitive_file_is_dropped_even_with_explicit_language() -> None:
    dc = _make_document_chunker()
    section = CodeSection(
        text="AWS_SECRET_ACCESS_KEY=abc123\n",
        # A supplied language must not bypass the path-based exclusion.
        language="python",
        file_path="deploy/.env",
        link="https://git.example.com/repo/-/blob/main/deploy/.env",
    )

    chunks = _chunk(dc, [section])

    # The document chunker may emit a contentless fallback chunk, but the
    # credential text itself must never reach the index.
    assert all("AWS_SECRET_ACCESS_KEY" not in chunk.content for chunk in chunks)
    assert all(not chunk.content.strip() for chunk in chunks)
