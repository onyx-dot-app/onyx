import pytest
from chonkie import SentenceChunker

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import SECTION_SEPARATOR
from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import Section
from onyx.connectors.models import SectionType
from onyx.indexing.chunking import DocumentChunker
from onyx.indexing.chunking import text_section_chunker as text_chunker_module
from onyx.natural_language_processing.utils import BaseTokenizer


class CharTokenizer(BaseTokenizer):
    """1 character == 1 token. Deterministic & trivial to reason about."""

    def encode(self, string: str) -> list[int]:
        return [ord(c) for c in string]

    def tokenize(self, string: str) -> list[str]:
        return list(string)

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(t) for t in tokens)


# With a char-level tokenizer, each char is a token. 200 is comfortably
# above BLURB_SIZE (128) so the blurb splitter won't get weird on small text.
CHUNK_LIMIT = 200


def _make_document_chunker(
    chunk_token_limit: int = CHUNK_LIMIT,
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
    )


def _make_doc(
    sections: list[Section],
    title: str | None = "Test Doc",
    doc_id: str = "doc1",
) -> IndexingDocument:
    return IndexingDocument(
        id=doc_id,
        source=DocumentSource.WEB,
        semantic_identifier=doc_id,
        title=title,
        metadata={},
        sections=[],  # real sections unused — method reads processed_sections
        processed_sections=sections,
    )


# --- Empty / degenerate input -------------------------------------------------


def test_empty_processed_sections_returns_single_empty_safety_chunk() -> None:
    """No sections at all should still yield one empty chunk (the
    `or not chunks` safety branch at the end)."""
    dc = _make_document_chunker()
    doc = _make_doc(sections=[])

    chunks = dc.chunk(
        document=doc,
        sections=[],
        title_prefix="TITLE\n",
        metadata_suffix_semantic="meta_sem",
        metadata_suffix_keyword="meta_kw",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 1
    assert chunks[0].content == ""
    assert chunks[0].chunk_id == 0
    assert chunks[0].title_prefix == "TITLE\n"
    assert chunks[0].metadata_suffix_semantic == "meta_sem"
    assert chunks[0].metadata_suffix_keyword == "meta_kw"
    # safe default link offsets
    assert chunks[0].source_links == {0: ""}


def test_empty_section_on_first_position_without_title_is_skipped() -> None:
    """Doc has no title, first section has empty text — the guard
    `(not document.title or section_idx > 0)` means it IS skipped."""
    dc = _make_document_chunker()
    doc = _make_doc(
        sections=[Section(type=SectionType.TEXT, text="", link="l0")],
        title=None,
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    # skipped → no real content, but safety branch still yields 1 empty chunk
    assert len(chunks) == 1
    assert chunks[0].content == ""


def test_empty_section_on_later_position_is_skipped_even_with_title() -> None:
    """Index > 0 empty sections are skipped regardless of title."""
    dc = _make_document_chunker()
    doc = _make_doc(
        sections=[
            Section(type=SectionType.TEXT, text="Alpha.", link="l0"),
            Section(type=SectionType.TEXT, text="", link="l1"),  # should be skipped
            Section(type=SectionType.TEXT, text="Beta.", link="l2"),
        ],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 1
    assert "Alpha." in chunks[0].content
    assert "Beta." in chunks[0].content
    # link offsets should only contain l0 and l2 (no l1)
    assert "l1" not in (chunks[0].source_links or {}).values()


# --- Single text section ------------------------------------------------------


def test_single_small_text_section_becomes_one_chunk() -> None:
    dc = _make_document_chunker()
    doc = _make_doc(
        sections=[Section(type=SectionType.TEXT, text="Hello world.", link="https://a")]
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="TITLE\n",
        metadata_suffix_semantic="ms",
        metadata_suffix_keyword="mk",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.content == "Hello world."
    assert chunk.source_links == {0: "https://a"}
    assert chunk.title_prefix == "TITLE\n"
    assert chunk.metadata_suffix_semantic == "ms"
    assert chunk.metadata_suffix_keyword == "mk"
    assert chunk.section_continuation is False
    assert chunk.image_file_id is None


# --- Multiple text sections combined -----------------------------------------


def test_multiple_small_sections_combine_into_one_chunk() -> None:
    dc = _make_document_chunker()
    sections = [
        Section(type=SectionType.TEXT, text="Part one.", link="l1"),
        Section(type=SectionType.TEXT, text="Part two.", link="l2"),
        Section(type=SectionType.TEXT, text="Part three.", link="l3"),
    ]
    doc = _make_doc(sections=sections)

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 1
    expected = SECTION_SEPARATOR.join(["Part one.", "Part two.", "Part three."])
    assert chunks[0].content == expected

    # link_offsets: indexed by shared_precompare_cleanup length of the
    # chunk_text *before* each section was appended.
    #   "" -> "", len 0
    #   "Part one." -> "partone", len 7
    #   "Part one.\n\nPart two." -> "partoneparttwo", len 14
    assert chunks[0].source_links == {0: "l1", 7: "l2", 14: "l3"}


def test_sections_overflow_into_second_chunk() -> None:
    """Two sections that together exceed content_token_limit should
    finalize the first as one chunk and start a new one."""
    dc = _make_document_chunker()
    # char-level: 120 char section → 120 tokens. 2 of these plus separator
    # exceed a 200-token limit, forcing a flush.
    a = "A" * 120
    b = "B" * 120
    doc = _make_doc(
        sections=[
            Section(type=SectionType.TEXT, text=a, link="la"),
            Section(type=SectionType.TEXT, text=b, link="lb"),
        ],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 2
    assert chunks[0].content == a
    assert chunks[1].content == b
    # first chunk is not a continuation; second starts a new section → not either
    assert chunks[0].section_continuation is False
    assert chunks[1].section_continuation is False
    # chunk_ids should be sequential starting at 0
    assert chunks[0].chunk_id == 0
    assert chunks[1].chunk_id == 1
    # links routed appropriately
    assert chunks[0].source_links == {0: "la"}
    assert chunks[1].source_links == {0: "lb"}


# --- Image section handling --------------------------------------------------


def test_image_only_section_produces_single_chunk_with_image_id() -> None:
    dc = _make_document_chunker()
    doc = _make_doc(
        sections=[
            Section(
                type=SectionType.IMAGE,
                text="summary of image",
                link="https://img",
                image_file_id="img-abc",
            )
        ],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 1
    assert chunks[0].image_file_id == "img-abc"
    assert chunks[0].content == "summary of image"
    assert chunks[0].source_links == {0: "https://img"}


def test_image_section_flushes_pending_text_and_creates_its_own_chunk() -> None:
    """A buffered text section followed by an image section:
    the pending text should be flushed first, then the image chunk."""
    dc = _make_document_chunker()
    doc = _make_doc(
        sections=[
            Section(type=SectionType.TEXT, text="Pending text.", link="ltext"),
            Section(
                type=SectionType.IMAGE,
                text="image summary",
                link="limage",
                image_file_id="img-1",
            ),
            Section(type=SectionType.TEXT, text="Trailing text.", link="ltail"),
        ],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 3

    # 0: flushed pending text
    assert chunks[0].content == "Pending text."
    assert chunks[0].image_file_id is None
    assert chunks[0].source_links == {0: "ltext"}

    # 1: image chunk
    assert chunks[1].content == "image summary"
    assert chunks[1].image_file_id == "img-1"
    assert chunks[1].source_links == {0: "limage"}

    # 2: trailing text, started fresh after image
    assert chunks[2].content == "Trailing text."
    assert chunks[2].image_file_id is None
    assert chunks[2].source_links == {0: "ltail"}


def test_image_section_without_link_gets_empty_links_dict() -> None:
    """If an image section has no link, links param is {} (not {0: ""})."""
    dc = _make_document_chunker()
    doc = _make_doc(
        sections=[
            Section(
                type=SectionType.IMAGE,
                text="img",
                link=None,
                image_file_id="img-xyz",
            ),
        ],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 1
    assert chunks[0].image_file_id == "img-xyz"
    # to_doc_aware_chunk falls back to {0: ""} when given an empty dict
    assert chunks[0].source_links == {0: ""}


# --- Oversized section splitting ---------------------------------------------


def test_oversized_section_is_split_across_multiple_chunks() -> None:
    """A section whose text exceeds content_token_limit should be passed
    through chunk_splitter and yield >1 chunks; only the first is not a
    continuation."""
    dc = _make_document_chunker()
    # Build a section whose char-count is well over CHUNK_LIMIT (200), made
    # of many short sentences so chonkie's SentenceChunker can split cleanly.
    section_text = (
        "Alpha beta gamma. Delta epsilon zeta. Eta theta iota. "
        "Kappa lambda mu. Nu xi omicron. Pi rho sigma. Tau upsilon phi. "
        "Chi psi omega. One two three. Four five six. Seven eight nine. "
        "Ten eleven twelve. Thirteen fourteen fifteen. "
        "Sixteen seventeen eighteen. Nineteen twenty."
    )
    assert len(section_text) > CHUNK_LIMIT

    doc = _make_doc(
        sections=[Section(type=SectionType.TEXT, text=section_text, link="big-link")],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) >= 2
    # First chunk is fresh, rest are continuations
    assert chunks[0].section_continuation is False
    for c in chunks[1:]:
        assert c.section_continuation is True
    # Every produced chunk should carry the section's link
    for c in chunks:
        assert c.source_links == {0: "big-link"}
    # Concatenated content should roughly cover the original (allowing
    # for chunker boundary whitespace differences).
    joined = "".join(c.content for c in chunks)
    for word in ("Alpha", "omega", "twenty"):
        assert word in joined


def test_oversized_section_flushes_pending_text_first() -> None:
    """A buffered text section followed by an oversized section should
    flush the pending chunk first, then emit the split chunks."""
    dc = _make_document_chunker()
    pending = "Pending buffered text."
    big = (
        "Alpha beta gamma. Delta epsilon zeta. Eta theta iota. "
        "Kappa lambda mu. Nu xi omicron. Pi rho sigma. Tau upsilon phi. "
        "Chi psi omega. One two three. Four five six. Seven eight nine. "
        "Ten eleven twelve. Thirteen fourteen fifteen. Sixteen seventeen."
    )
    assert len(big) > CHUNK_LIMIT

    doc = _make_doc(
        sections=[
            Section(type=SectionType.TEXT, text=pending, link="l-pending"),
            Section(type=SectionType.TEXT, text=big, link="l-big"),
        ],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    # First chunk is the flushed pending text
    assert chunks[0].content == pending
    assert chunks[0].source_links == {0: "l-pending"}
    assert chunks[0].section_continuation is False

    # Remaining chunks correspond to the oversized section
    assert len(chunks) >= 2
    for c in chunks[1:]:
        assert c.source_links == {0: "l-big"}
    # Within the oversized section, the first is fresh and the rest are
    # continuations.
    assert chunks[1].section_continuation is False
    for c in chunks[2:]:
        assert c.section_continuation is True


# --- Title prefix / metadata propagation -------------------------------------


def test_title_prefix_and_metadata_propagate_to_all_chunks() -> None:
    dc = _make_document_chunker()
    doc = _make_doc(
        sections=[
            Section(type=SectionType.TEXT, text="A" * 120, link="la"),
            Section(type=SectionType.TEXT, text="B" * 120, link="lb"),
        ],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="MY_TITLE\n",
        metadata_suffix_semantic="MS",
        metadata_suffix_keyword="MK",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 2
    for chunk in chunks:
        assert chunk.title_prefix == "MY_TITLE\n"
        assert chunk.metadata_suffix_semantic == "MS"
        assert chunk.metadata_suffix_keyword == "MK"


# --- chunk_id monotonicity ---------------------------------------------------


def test_chunk_ids_are_sequential_starting_at_zero() -> None:
    dc = _make_document_chunker()
    doc = _make_doc(
        sections=[
            Section(type=SectionType.TEXT, text="A" * 120, link="la"),
            Section(type=SectionType.TEXT, text="B" * 120, link="lb"),
            Section(type=SectionType.TEXT, text="C" * 120, link="lc"),
        ],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert [c.chunk_id for c in chunks] == list(range(len(chunks)))


# --- Overflow accumulation behavior ------------------------------------------


def test_overflow_flush_then_subsequent_section_joins_new_chunk() -> None:
    """After an overflow flush starts a new chunk, the next fitting section
    should combine into that same new chunk (not spawn a third)."""
    dc = _make_document_chunker()
    # 120 + 120 > 200 → first two sections produce two chunks.
    # Third section is small (20 chars) → should fit with second.
    doc = _make_doc(
        sections=[
            Section(type=SectionType.TEXT, text="A" * 120, link="la"),
            Section(type=SectionType.TEXT, text="B" * 120, link="lb"),
            Section(type=SectionType.TEXT, text="C" * 20, link="lc"),
        ],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 2
    assert chunks[0].content == "A" * 120
    assert chunks[1].content == ("B" * 120) + SECTION_SEPARATOR + ("C" * 20)
    # link_offsets on second chunk: lb at 0, lc at precompare-len("BBBB...")=120
    assert chunks[1].source_links == {0: "lb", 120: "lc"}


def test_small_section_after_oversized_starts_a_fresh_chunk() -> None:
    """After an oversized section is emitted as its own chunks, the internal
    accumulator should be empty so a following small section starts a new
    chunk instead of being swallowed."""
    dc = _make_document_chunker()
    big = (
        "Alpha beta gamma. Delta epsilon zeta. Eta theta iota. "
        "Kappa lambda mu. Nu xi omicron. Pi rho sigma. Tau upsilon phi. "
        "Chi psi omega. One two three. Four five six. Seven eight nine. "
        "Ten eleven twelve. Thirteen fourteen fifteen. Sixteen seventeen."
    )
    assert len(big) > CHUNK_LIMIT
    doc = _make_doc(
        sections=[
            Section(type=SectionType.TEXT, text=big, link="l-big"),
            Section(type=SectionType.TEXT, text="Tail text.", link="l-tail"),
        ],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    # All-but-last chunks belong to the oversized section; the very last is
    # the tail text starting fresh (not a continuation).
    assert len(chunks) >= 2
    assert chunks[-1].content == "Tail text."
    assert chunks[-1].source_links == {0: "l-tail"}
    assert chunks[-1].section_continuation is False
    # And earlier oversized chunks never leaked the tail link
    for c in chunks[:-1]:
        assert c.source_links == {0: "l-big"}


# --- STRICT_CHUNK_TOKEN_LIMIT fallback path ----------------------------------


def test_strict_chunk_token_limit_subdivides_oversized_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When STRICT_CHUNK_TOKEN_LIMIT is enabled and chonkie's chunk_splitter
    still produces a piece larger than content_token_limit (e.g. a single
    no-period run), the code must fall back to _split_oversized_chunk."""
    monkeypatch.setattr(text_chunker_module, "STRICT_CHUNK_TOKEN_LIMIT", True)
    dc = _make_document_chunker()
    # 500 non-whitespace chars with no sentence boundaries — chonkie will
    # return it as one oversized piece (>200) which triggers the fallback.
    run = "a" * 500
    doc = _make_doc(sections=[Section(type=SectionType.TEXT, text=run, link="l-run")])

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    # With CHUNK_LIMIT=200 and a 500-char run we expect ceil(500/200)=3 sub-chunks.
    assert len(chunks) == 3
    # First is fresh, rest are continuations (is_continuation=(j != 0))
    assert chunks[0].section_continuation is False
    assert chunks[1].section_continuation is True
    assert chunks[2].section_continuation is True
    # All carry the section link
    for c in chunks:
        assert c.source_links == {0: "l-run"}
    # NOTE: we do NOT assert the chunks are at or below content_token_limit.
    # _split_oversized_chunk joins tokens with " ", which means the resulting
    # chunk contents can exceed the limit when tokens are short. That's a
    # quirk of the current implementation and this test pins the window
    # slicing, not the post-join length.


def test_strict_chunk_token_limit_disabled_allows_oversized_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same pathological input, but with STRICT disabled: the oversized
    split is emitted verbatim as a single chunk (current behavior)."""
    monkeypatch.setattr(text_chunker_module, "STRICT_CHUNK_TOKEN_LIMIT", False)
    dc = _make_document_chunker()
    run = "a" * 500
    doc = _make_doc(sections=[Section(type=SectionType.TEXT, text=run, link="l-run")])

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 1
    assert chunks[0].content == run
    assert chunks[0].section_continuation is False


# --- First-section-with-empty-text-but-document-has-title edge case ----------


def test_first_empty_section_with_title_is_processed_not_skipped() -> None:
    """The guard `(not document.title or section_idx > 0)` means: when
    the doc has a title AND it's the first section, an empty text section
    is NOT skipped. This pins current behavior so a refactor can't silently
    change it."""
    dc = _make_document_chunker()
    doc = _make_doc(
        sections=[
            Section(
                type=SectionType.TEXT, text="", link="l0"
            ),  # empty first section, kept
            Section(type=SectionType.TEXT, text="Real content.", link="l1"),
        ],
        title="Has A Title",
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 1
    assert chunks[0].content == "Real content."
    # First (empty) section did register a link_offset at 0 before being
    # overwritten; that offset is then reused when "Real content." is added,
    # because shared_precompare_cleanup("") is still "". End state: {0: "l1"}
    assert chunks[0].source_links == {0: "l1"}


# --- clean_text is applied to section text -----------------------------------


def test_clean_text_strips_control_chars_from_section_content() -> None:
    """clean_text() should remove control chars before the text enters the
    accumulator — verifies the call isn't dropped by a refactor."""
    dc = _make_document_chunker()
    # NUL + BEL are control chars below 0x20 and not \n or \t → should be
    # stripped by clean_text.
    dirty = "Hello\x00 World\x07!"
    doc = _make_doc(sections=[Section(type=SectionType.TEXT, text=dirty, link="l1")])

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 1
    assert chunks[0].content == "Hello World!"


# --- None-valued fields ------------------------------------------------------


def test_section_with_none_text_behaves_like_empty_string() -> None:
    """`section.text` may be None — the method coerces via
    `str(section.text or "")`, so a None-text section behaves identically
    to an empty one (skipped unless it's the first section of a titled doc)."""
    dc = _make_document_chunker()
    doc = _make_doc(
        sections=[
            Section(type=SectionType.TEXT, text="Alpha.", link="la"),
            Section(type=SectionType.TEXT, text=None, link="lnone"),  # idx 1 → skipped
            Section(type=SectionType.TEXT, text="Beta.", link="lb"),
        ],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 1
    assert "Alpha." in chunks[0].content
    assert "Beta." in chunks[0].content
    assert "lnone" not in (chunks[0].source_links or {}).values()


# --- Trailing empty chunk suppression ----------------------------------------


def test_no_trailing_empty_chunk_when_last_section_was_image() -> None:
    """If the final section was an image (which emits its own chunk and
    resets chunk_text), the safety `or not chunks` branch should NOT fire
    because chunks is non-empty. Pin this explicitly."""
    dc = _make_document_chunker()
    doc = _make_doc(
        sections=[
            Section(type=SectionType.TEXT, text="Leading text.", link="ltext"),
            Section(
                type=SectionType.IMAGE,
                text="img summary",
                link="limg",
                image_file_id="img-final",
            ),
        ],
    )

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    assert len(chunks) == 2
    assert chunks[0].content == "Leading text."
    assert chunks[0].image_file_id is None
    assert chunks[1].content == "img summary"
    assert chunks[1].image_file_id == "img-final"
    # Crucially: no third empty chunk got appended at the end.


def test_no_trailing_empty_chunk_when_last_section_was_oversized() -> None:
    """Same guarantee for oversized sections: their splits fully clear the
    accumulator, and the trailing safety branch should be a no-op."""
    dc = _make_document_chunker()
    big = (
        "Alpha beta gamma. Delta epsilon zeta. Eta theta iota. "
        "Kappa lambda mu. Nu xi omicron. Pi rho sigma. Tau upsilon phi. "
        "Chi psi omega. One two three. Four five six. Seven eight nine. "
        "Ten eleven twelve. Thirteen fourteen fifteen. Sixteen seventeen."
    )
    assert len(big) > CHUNK_LIMIT
    doc = _make_doc(sections=[Section(type=SectionType.TEXT, text=big, link="l-big")])

    chunks = dc.chunk(
        document=doc,
        sections=doc.processed_sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=CHUNK_LIMIT,
    )

    # Every chunk should be non-empty — no dangling "" chunk at the tail.
    assert all(c.content.strip() for c in chunks)
