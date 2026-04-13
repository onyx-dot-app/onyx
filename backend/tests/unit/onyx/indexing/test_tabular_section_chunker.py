"""End-to-end tests for `TabularChunker.chunk_section`.

Each test is structured as:
    INPUT    — the CSV text passed to the chunker + token budget + link
    EXPECTED — the exact chunk texts the chunker should emit
    ACT      — a single call to `chunk_section`
    ASSERT   — literal equality against the expected chunk texts

A character-level tokenizer (1 char == 1 token) is used so token-budget
arithmetic is deterministic and expected chunks can be spelled out
exactly.
"""

from onyx.connectors.models import Section
from onyx.connectors.models import TabularSection
from onyx.indexing.chunking.section_chunker import AccumulatorState
from onyx.indexing.chunking.tabular_section_chunker import TabularChunker
from onyx.natural_language_processing.utils import BaseTokenizer


class CharTokenizer(BaseTokenizer):
    def encode(self, string: str) -> list[int]:
        return [ord(c) for c in string]

    def tokenize(self, string: str) -> list[str]:
        return list(string)

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(t) for t in tokens)


def _make_chunker() -> TabularChunker:
    return TabularChunker(tokenizer=CharTokenizer())


def _tabular_section(text: str, link: str = "sheet:Test") -> Section:
    return TabularSection(text=text, link=link)


class TestTabularChunkerChunkSection:
    def test_simple_csv_all_rows_fit_one_chunk(self) -> None:
        # --- INPUT -----------------------------------------------------
        csv_text = (
            "Name,Age,City\n"
            "Alice,30,NYC\n"
            "Bob,25,SF\n"
        )
        link = "sheet:People"
        content_token_limit = 500

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            (
                "sheet:People\n"
                "Rows:\n"
                "Columns: Name, Age, City\n"
                "Name=Alice, Age=30, City=NYC\n"
                "Name=Bob, Age=25, City=SF"
            ),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        assert [p.is_continuation for p in out.payloads] == [False]
        assert all(p.links == {0: link} for p in out.payloads)
        assert out.accumulator.is_empty()

    def test_overflow_splits_into_two_deterministic_chunks(self) -> None:
        # --- INPUT -----------------------------------------------------
        # prelude = "sheet:S\nRows:\nColumns: col, val" (31 chars = 31 tokens)
        # At content_token_limit=57, row_budget = max(16, 57-31-1) = 25.
        # Each row "col=a, val=1" is 12 tokens; two rows + \n = 25 (fits),
        # three rows + 2×\n = 38 (overflows) → split after 2 rows.
        csv_text = (
            "col,val\n"
            "a,1\n"
            "b,2\n"
            "c,3\n"
            "d,4\n"
        )
        link = "sheet:S"
        content_token_limit = 57

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            (
                "sheet:S\n"
                "Rows:\n"
                "Columns: col, val\n"
                "col=a, val=1\n"
                "col=b, val=2"
            ),
            (
                "sheet:S\n"
                "Rows:\n"
                "Columns: col, val\n"
                "col=c, val=3\n"
                "col=d, val=4"
            ),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        # First chunk is fresh; subsequent chunks mark as continuations.
        assert [p.is_continuation for p in out.payloads] == [False, True]
        # Link carries through every chunk.
        assert all(p.links == {0: link} for p in out.payloads)

    def test_header_only_csv_produces_single_prelude_chunk(self) -> None:
        # --- INPUT -----------------------------------------------------
        csv_text = "col1,col2\n"
        link = "sheet:Headers"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            "sheet:Headers\nRows:\nColumns: col1, col2",
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
            AccumulatorState(),
            content_token_limit=500,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts

    def test_empty_cells_dropped_from_chunk_text(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Alice's Age is empty; Bob's City is empty. Empty cells should
        # not appear as `field=` pairs in the output.
        csv_text = (
            "Name,Age,City\n"
            "Alice,,NYC\n"
            "Bob,25,\n"
        )
        link = "sheet:P"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            (
                "sheet:P\n"
                "Rows:\n"
                "Columns: Name, Age, City\n"
                "Name=Alice, City=NYC\n"
                "Name=Bob, Age=25"
            ),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
            AccumulatorState(),
            content_token_limit=500,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts

    def test_quoted_commas_in_csv_preserved_as_one_field(self) -> None:
        # --- INPUT -----------------------------------------------------
        # "Hello, world" is quoted in the CSV, so it's a single field
        # value containing a comma — not two cells.
        csv_text = (
            'Name,Notes\n'
            'Alice,"Hello, world"\n'
        )
        link = "sheet:P"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            (
                "sheet:P\n"
                "Rows:\n"
                "Columns: Name, Notes\n"
                "Name=Alice, Notes=Hello, world"
            ),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
            AccumulatorState(),
            content_token_limit=500,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts

    def test_blank_rows_in_csv_are_skipped(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Stray blank rows in the CSV (e.g. export artifacts) shouldn't
        # produce ghost rows in the output.
        csv_text = (
            "A,B\n"
            "\n"
            "1,2\n"
            "\n"
            "\n"
            "3,4\n"
        )
        link = "sheet:S"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            (
                "sheet:S\n"
                "Rows:\n"
                "Columns: A, B\n"
                "A=1, B=2\n"
                "A=3, B=4"
            ),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
            AccumulatorState(),
            content_token_limit=500,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts

    def test_accumulator_flushes_before_tabular_chunks(self) -> None:
        # --- INPUT -----------------------------------------------------
        # A text accumulator was populated by the prior text section.
        # Tabular sections are structural boundaries, so the pending
        # text is flushed as its own chunk before the tabular content.
        pending_text = "prior paragraph from an earlier text section"
        pending_link = "prev-link"

        csv_text = (
            "a,b\n"
            "1,2\n"
        )
        link = "sheet:S"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            pending_text,  # flushed accumulator
            (
                "sheet:S\n"
                "Rows:\n"
                "Columns: a, b\n"
                "a=1, b=2"
            ),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
            AccumulatorState(
                text=pending_text,
                link_offsets={0: pending_link},
            ),
            content_token_limit=500,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        # Flushed chunk keeps the prior text's link; tabular chunk uses
        # the tabular section's link.
        assert out.payloads[0].links == {0: pending_link}
        assert out.payloads[1].links == {0: link}
        # Accumulator resets — tabular section is a structural boundary.
        assert out.accumulator.is_empty()

    def test_empty_tabular_section_returns_no_payloads_and_preserves_accumulator(
        self,
    ) -> None:
        # --- INPUT -----------------------------------------------------
        # Malformed/empty tabular section should not flush the text
        # accumulator — the caller (DocumentChunker) handles skip logic;
        # we preserve the accumulator so subsequent sections can use it.
        pending_text = "prior paragraph"
        pending_link_offsets = {0: "prev-link"}

        # --- EXPECTED --------------------------------------------------
        expected_texts: list[str] = []
        expected_accumulator_text = pending_text
        expected_accumulator_offsets = pending_link_offsets

        # --- ACT -------------------------------------------------------
        out = _make_chunker().chunk_section(
            _tabular_section("", link="sheet:Empty"),
            AccumulatorState(
                text=pending_text,
                link_offsets=pending_link_offsets,
            ),
            content_token_limit=500,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        assert out.accumulator.text == expected_accumulator_text
        assert out.accumulator.link_offsets == expected_accumulator_offsets
