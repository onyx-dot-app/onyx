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
from onyx.indexing.chunking.tabular_section_chunker.analysis import analyze_sheet
from onyx.indexing.chunking.tabular_section_chunker.sheet_descriptor import (
    build_sheet_descriptor_chunks,
)
from onyx.indexing.chunking.tabular_section_chunker.total_descriptor import (
    build_total_descriptor_chunks,
)
from onyx.indexing.chunking.tabular_section_chunker.total_descriptor import (
    TOTALS_HEADER,
)
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.utils.csv_utils import parse_csv_string
from onyx.utils.csv_utils import read_csv_header


class CharTokenizer(BaseTokenizer):
    def encode(self, string: str) -> list[int]:
        return [ord(c) for c in string]

    def tokenize(self, string: str) -> list[str]:
        return list(string)

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(t) for t in tokens)


def _make_chunker_no_metadata() -> TabularChunker:
    return TabularChunker(tokenizer=CharTokenizer(), ignore_metadata_chunks=True)


def _make_chunker_with_metadata() -> TabularChunker:
    return TabularChunker(tokenizer=CharTokenizer(), ignore_metadata_chunks=False)


_DEFAULT_LINK = "https://example.com/doc"


def _tabular_section(
    text: str,
    link: str = _DEFAULT_LINK,
    heading: str | None = "sheet:Test",
) -> Section:
    return TabularSection(text=text, link=link, heading=heading)


class TestTabularChunkerChunkSection:
    def test_simple_csv_all_rows_fit_one_chunk(self) -> None:
        # --- INPUT -----------------------------------------------------
        csv_text = "Name,Age,City\n" "Alice,30,NYC\n" "Bob,25,SF\n"
        heading = "sheet:People"
        content_token_limit = 500

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            (
                "sheet:People\n"
                "Columns: Name, Age, City\n"
                "Name=Alice, Age=30, City=NYC\n"
                "Name=Bob, Age=25, City=SF"
            ),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        assert [p.is_continuation for p in out.payloads] == [False]
        assert all(p.links == {0: _DEFAULT_LINK} for p in out.payloads)
        assert out.accumulator.is_empty()

    def test_overflow_splits_into_two_deterministic_chunks(self) -> None:
        # --- INPUT -----------------------------------------------------
        # prelude = "sheet:S\nColumns: col, val" (25 chars = 25 tokens)
        # At content_token_limit=57, row_budget = max(16, 57-31-1) = 25.
        # Each row "col=a, val=1" is 12 tokens; two rows + \n = 25 (fits),
        # three rows + 2×\n = 38 (overflows) → split after 2 rows.
        csv_text = "col,val\n" "a,1\n" "b,2\n" "c,3\n" "d,4\n"
        heading = "sheet:S"
        content_token_limit = 57

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            ("sheet:S\n" "Columns: col, val\n" "col=a, val=1\n" "col=b, val=2"),
            ("sheet:S\n" "Columns: col, val\n" "col=c, val=3\n" "col=d, val=4"),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        # First chunk is fresh; subsequent chunks mark as continuations.
        assert [p.is_continuation for p in out.payloads] == [False, True]
        # Link carries through every chunk.
        assert all(p.links == {0: _DEFAULT_LINK} for p in out.payloads)

    def test_header_only_csv_emits_metadata_chunk_with_no_content(self) -> None:
        # --- INPUT -----------------------------------------------------
        # A header-only CSV has no data rows, so `parse_to_chunks` emits
        # nothing. With metadata enabled, the descriptor still fires —
        # column names alone are useful retrieval signal.
        csv_text = "col1,col2\n"
        heading = "sheet:Headers"
        content_token_limit = 500

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            "sheet:Headers\n"
            "Sheet overview.\n"
            "This sheet has 0 rows and 2 columns.\n"
            "Columns: col1, col2",
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_with_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        assert [p.is_continuation for p in out.payloads] == [False]
        assert all(p.links == {0: _DEFAULT_LINK} for p in out.payloads)
        assert out.accumulator.is_empty()

    def test_empty_cells_dropped_from_chunk_text(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Alice's Age is empty; Bob's City is empty. Empty cells should
        # not appear as `field=` pairs in the output.
        csv_text = "Name,Age,City\n" "Alice,,NYC\n" "Bob,25,\n"
        heading = "sheet:P"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            (
                "sheet:P\n"
                "Columns: Name, Age, City\n"
                "Name=Alice, City=NYC\n"
                "Name=Bob, Age=25"
            ),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=500,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts

    def test_quoted_commas_in_csv_preserved_as_one_field(self) -> None:
        # --- INPUT -----------------------------------------------------
        # "Hello, world" is quoted in the CSV, so csv.reader parses it as
        # a single field. The surrounding quotes are stripped during
        # decoding, so the chunk text carries the bare value.
        csv_text = "Name,Notes\n" 'Alice,"Hello, world"\n'
        heading = "sheet:P"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            ("sheet:P\n" "Columns: Name, Notes\n" "Name=Alice, Notes=Hello, world"),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=500,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts

    def test_blank_rows_in_csv_are_skipped(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Stray blank rows in the CSV (e.g. export artifacts) shouldn't
        # produce ghost rows in the output.
        csv_text = "A,B\n" "\n" "1,2\n" "\n" "\n" "3,4\n"
        heading = "sheet:S"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            ("sheet:S\n" "Columns: A, B\n" "A=1, B=2\n" "A=3, B=4"),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
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

        csv_text = "a,b\n" "1,2\n"
        heading = "sheet:S"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            pending_text,  # flushed accumulator
            ("sheet:S\n" "Columns: a, b\n" "a=1, b=2"),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
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
        assert out.payloads[1].links == {0: _DEFAULT_LINK}
        # Accumulator resets — tabular section is a structural boundary.
        assert out.accumulator.is_empty()

    def test_multi_row_packing_under_budget_emits_single_chunk(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Three small rows (20 tokens each) under a generous
        # content_token_limit=100 should pack into ONE chunk — prelude
        # emitted once, rows stacked beneath it.
        csv_text = (
            "x\n" "aaaaaaaaaaaaaaaaaa\n" "bbbbbbbbbbbbbbbbbb\n" "cccccccccccccccccc\n"
        )
        heading = "S"
        content_token_limit = 100

        # --- EXPECTED --------------------------------------------------
        # Each formatted row "x=<18-char value>" = 20 tokens.
        # Full chunk with sheet + Columns + 3 rows =
        #   1 + 1 + 10 + 1 + (20 + 1 + 20 + 1 + 20) = 75 tokens ≤ 100.
        # Single chunk carries all three rows.
        expected_texts = [
            "S\n"
            "Columns: x\n"
            "x=aaaaaaaaaaaaaaaaaa\n"
            "x=bbbbbbbbbbbbbbbbbb\n"
            "x=cccccccccccccccccc"
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        assert [p.is_continuation for p in out.payloads] == [False]
        assert all(len(p.text) <= content_token_limit for p in out.payloads)

    def test_packing_reserves_prelude_budget_so_every_chunk_has_full_prelude(
        self,
    ) -> None:
        # --- INPUT -----------------------------------------------------
        # Budget (30) is large enough for all 5 bare rows (row_block =
        # 24 tokens) to pack as one chunk if the prelude were optional,
        # but [sheet] + Columns + 5_rows would be 41 tokens > 30. The
        # packing logic reserves space for the prelude: only 2 rows
        # pack per chunk (17 prelude overhead + 9 rows = 26 ≤ 30).
        # Every emitted chunk therefore carries its full prelude rather
        # than dropping Columns at emit time.
        csv_text = "x\n" "aa\n" "bb\n" "cc\n" "dd\n" "ee\n"
        heading = "S"
        content_token_limit = 30

        # --- EXPECTED --------------------------------------------------
        # Prelude overhead = 'S\nColumns: x\n' = 1+1+10+1 = 13.
        # Each row "x=XX" = 4 tokens, row separator "\n" = 1.
        #   3 rows: 13 + (4+1+4+1+4) = 27 ≤ 30 ✓
        #   4 rows: 13 + (4+1+4+1+4+1+4) = 32 > 30 ✗
        # → 3 rows in the first chunk, 2 rows in the second.
        expected_texts = [
            "S\nColumns: x\nx=aa\nx=bb\nx=cc",
            "S\nColumns: x\nx=dd\nx=ee",
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        # Every chunk fits under the budget AND carries its full
        # prelude — that's the whole point of this check.
        assert all(len(p.text) <= content_token_limit for p in out.payloads)
        assert all("Columns: x" in p.text for p in out.payloads)

    def test_oversized_row_splits_into_field_pieces_no_prelude(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Single-row CSV whose formatted form ("field 1=1, ..." = 53
        # tokens) exceeds content_token_limit (20). Per the chunker's
        # rules, oversized rows are split at field boundaries into
        # pieces each ≤ max_tokens, and no prelude is added to split
        # pieces (they already consume the full budget). A 53-token row
        # packs into 3 field-boundary pieces under a 20-token budget.
        csv_text = "field 1,field 2,field 3,field 4,field 5\n" "1,2,3,4,5\n"
        heading = "S"
        content_token_limit = 20

        # --- EXPECTED --------------------------------------------------
        # Row = "field 1=1, field 2=2, field 3=3, field 4=4, field 5=5"
        # Fields @ 9 tokens each, ", " sep = 2 tokens.
        #   "field 1=1, field 2=2" = 9+2+9 = 20 tokens ≤ 20 ✓
        #   + ", field 3=3"        = 20+2+9 = 31 > 20 → flush, start new
        #   "field 3=3, field 4=4" = 9+2+9 = 20 ≤ 20 ✓
        #   + ", field 5=5"        = 20+2+9 = 31 > 20 → flush, start new
        #   "field 5=5"            = 9 ≤ 20 ✓
        # ceil(53 / 20) = 3 chunks.
        expected_texts = [
            "field 1=1, field 2=2",
            "field 3=3, field 4=4",
            "field 5=5",
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        # Invariant: no chunk exceeds max_tokens.
        assert all(len(p.text) <= content_token_limit for p in out.payloads)
        # is_continuation: first chunk False, rest True.
        assert [p.is_continuation for p in out.payloads] == [False, True, True]

    def test_empty_tabular_section_flushes_accumulator_and_resets_it(
        self,
    ) -> None:
        # --- INPUT -----------------------------------------------------
        # Tabular sections are structural boundaries, so any pending text
        # buffer is flushed to a chunk before parsing the tabular content
        # — even if the tabular section itself is empty. The accumulator
        # is then reset.
        pending_text = "prior paragraph"
        pending_link_offsets = {0: "prev-link"}

        # --- EXPECTED --------------------------------------------------
        expected_texts = [pending_text]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section("", heading="sheet:Empty"),
            AccumulatorState(
                text=pending_text,
                link_offsets=pending_link_offsets,
            ),
            content_token_limit=500,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        assert out.accumulator.is_empty()

    def test_single_oversized_field_token_splits_at_id_boundaries(self) -> None:
        # --- INPUT -----------------------------------------------------
        # A single `field=value` pair that itself exceeds max_tokens can't
        # be split at field boundaries — there's only one field. The
        # chunker falls back to encoding the pair to token ids and
        # slicing at max-token-sized windows.
        #
        # CSV has one column "x" with a 50-char value. Formatted pair =
        # "x=" + 50 a's = 52 tokens. Budget = 10.
        csv_text = "x\n" + ("a" * 50) + "\n"
        heading = "S"
        content_token_limit = 10

        # --- EXPECTED --------------------------------------------------
        # 52-char pair at 10 tokens per window = 6 pieces:
        #   [0:10)  "x=aaaaaaaa"   (10)
        #   [10:20) "aaaaaaaaaa"   (10)
        #   [20:30) "aaaaaaaaaa"   (10)
        #   [30:40) "aaaaaaaaaa"   (10)
        #   [40:50) "aaaaaaaaaa"   (10)
        #   [50:52) "aa"           (2)
        # Split pieces carry no prelude (they already consume the budget).
        expected_texts = [
            "x=aaaaaaaa",
            "aaaaaaaaaa",
            "aaaaaaaaaa",
            "aaaaaaaaaa",
            "aaaaaaaaaa",
            "aa",
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        # Every piece is ≤ max_tokens — the invariant the token-level
        # fallback exists to enforce.
        assert all(len(p.text) <= content_token_limit for p in out.payloads)

    def test_underscored_column_gets_friendly_alias_in_parens(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Column headers with underscores get a space-substituted friendly
        # alias appended in parens on the `Columns:` line. Plain headers
        # pass through untouched.
        csv_text = "MTTR_hours,id,owner_name\n" "3,42,Alice\n"
        heading = "sheet:M"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            (
                "sheet:M\n"
                "Columns: MTTR_hours (MTTR hours), id, owner_name (owner name)\n"
                "MTTR_hours=3, id=42, owner_name=Alice"
            ),
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=500,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts

    def test_oversized_row_between_small_rows_preserves_flanking_chunks(
        self,
    ) -> None:
        # --- INPUT -----------------------------------------------------
        # State-machine check: small row, oversized row, small row. The
        # first small row should become a preluded chunk; the oversized
        # row flushes it and emits split fragments without prelude; then
        # the last small row picks up from wherever the split left off.
        #
        # Headers a,b,c,d. Row 1 and row 3 each have only column `a`
        # populated (tiny). Row 2 is a "fat" row with all four columns
        # populated.
        csv_text = "a,b,c,d\n" "1,,,\n" "xxx,yyy,zzz,www\n" "2,,,\n"
        heading = "S"
        content_token_limit = 20

        # --- EXPECTED --------------------------------------------------
        # Prelude = 'S\nColumns: a, b, c, d\n' = 1+1+19+1 = 22 > 20, so
        #   sheet fits with the row but full Columns header does not.
        # Row 1 formatted = "a=1" (3). build_chunk_from_scratch:
        #   cols+row = 20+3 = 23 > 20 → skip cols. sheet+row = 1+1+3 = 5
        #   ≤ 20 → chunk = "S\na=1".
        # Row 2 formatted = "a=xxx, b=yyy, c=zzz, d=www" (26 > 20) →
        #   flush "S\na=1" and split at pair boundaries:
        #     "a=xxx, b=yyy, c=zzz" (19 ≤ 20 ✓)
        #     "d=www"                (5)
        # Row 3 formatted = "a=2" (3). can_pack onto "d=www" (5):
        #   5 + 3 + 1 = 9 ≤ 20 ✓ → packs. Trailing fragment from the
        #   split absorbs the next small row, which is the current v2
        #   behavior (the fragment becomes `current_chunk` and the next
        #   small row is appended with the standard packing rules).
        expected_texts = [
            "S\na=1",
            "a=xxx, b=yyy, c=zzz",
            "d=www\na=2",
        ]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        assert all(len(p.text) <= content_token_limit for p in out.payloads)

    def test_prelude_layering_column_header_fits_but_sheet_header_does_not(
        self,
    ) -> None:
        # --- INPUT -----------------------------------------------------
        # Budget lets `Columns: x\nx=y` fit but not the additional sheet
        # header on top. The chunker should add the column header and
        # drop the sheet header.
        #
        # sheet = "LongSheetName" (13), cols = "Columns: x" (10),
        # row = "x=y" (3). Budget = 15.
        #   cols + row:        10+1+3          = 14 ≤ 15 ✓
        #   sheet + cols + row: 13+1+10+1+3    = 28 > 15 ✗
        csv_text = "x\n" "y\n"
        heading = "LongSheetName"
        content_token_limit = 15

        # --- EXPECTED --------------------------------------------------
        expected_texts = ["Columns: x\nx=y"]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts

    def test_prelude_layering_sheet_header_fits_but_column_header_does_not(
        self,
    ) -> None:
        # --- INPUT -----------------------------------------------------
        # Budget is too small for the column header but leaves room for
        # the short sheet header. The chunker should fall back to just
        # sheet + row (its layered "try cols, then try sheet on top of
        # whatever we have" logic means sheet is attempted on the bare
        # row when cols didn't fit).
        #
        # sheet = "S" (1), cols = "Columns: ABC, DEF" (17),
        # row = "ABC=1, DEF=2" (12). Budget = 20.
        #   cols + row:        17+1+12        = 30 > 20 ✗
        #   sheet + row:        1+1+12        = 14 ≤ 20 ✓
        csv_text = "ABC,DEF\n" "1,2\n"
        heading = "S"
        content_token_limit = 20

        # --- EXPECTED --------------------------------------------------
        expected_texts = ["S\nABC=1, DEF=2"]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_no_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts

    def test_metadata_chunks_appended_after_content_when_enabled(self) -> None:
        # --- INPUT -----------------------------------------------------
        # With ignore_metadata_chunks=False, the descriptor chunk is
        # appended AFTER the content chunk(s). is_continuation tracks
        # the index in the combined output, so the metadata chunk is
        # marked as a continuation.
        csv_text = "Name,Age\n" "Alice,30\n" "Bob,25\n"
        heading = "sheet:T"
        content_token_limit = 500

        # --- EXPECTED --------------------------------------------------
        content_chunk = (
            "sheet:T\n" "Columns: Name, Age\n" "Name=Alice, Age=30\n" "Name=Bob, Age=25"
        )
        descriptor_chunk = (
            "sheet:T\n"
            "Sheet overview.\n"
            "This sheet has 2 rows and 2 columns.\n"
            "Columns: Name, Age\n"
            "Numeric columns (aggregatable by sum, average, min, max): Age\n"
            "Categorical columns (groupable, can be counted by value): Name\n"
            "Values seen in Name: Alice, Bob"
        )
        totals_chunk = (
            "sheet:T\n"
            "Totals and overall aggregates across all rows. This sheet can answer "
            "whole-dataset questions about total, overall, grand total, sum across "
            "all, average, combined, mean, minimum, maximum, and count of values.\n"
            "Column Age: total (sum across all rows) = 55, average = 27.5, "
            "minimum = 25, maximum = 30, count = 2.\n"
            "Column Name most frequent value: Alice (1 occurrences).\n"
            "Total row count: 2."
        )
        expected_texts = [content_chunk, descriptor_chunk, totals_chunk]

        # --- ACT -------------------------------------------------------
        out = _make_chunker_with_metadata().chunk_section(
            _tabular_section(csv_text, heading=heading),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
        # Content first, metadata chunks follow as continuations.
        assert [p.is_continuation for p in out.payloads] == [False, True, True]


class TestTabularChunkerMalformedCsv:
    def test_bare_cr_normalized_and_parsed(self) -> None:
        """A bare \\r (old Mac line ending) is normalized inside
        parse_csv_string, so rows are recovered and the chunker never
        sees an error."""
        # "value1,line1\rline2" normalizes to two rows:
        #   row 2: col1=value1, col2=line1
        #   row 3: col1=line2  (short row — col2 absent, skipped by zip)
        csv_with_bare_cr = "col1,col2\nvalue1,line1\rline2"
        section = _tabular_section(csv_with_bare_cr)
        chunker = _make_chunker_no_metadata()
        result = chunker.chunk_section(
            section, AccumulatorState(), content_token_limit=500
        )
        assert len(result.payloads) > 0
        texts = [p.text for p in result.payloads]
        assert any("col1=value1" in t for t in texts)

    def test_bare_cr_with_metadata_chunker(self) -> None:
        """With ignore_metadata_chunks=False, bare-\\r CSVs produce both
        row chunks and descriptor chunks after normalization."""
        csv_with_bare_cr = "col1,col2\nvalue1,line1\rline2"
        section = _tabular_section(csv_with_bare_cr)
        chunker = _make_chunker_with_metadata()
        result = chunker.chunk_section(
            section, AccumulatorState(), content_token_limit=500
        )
        assert len(result.payloads) > 0
        texts = [p.text for p in result.payloads]
        assert any("col1" in t for t in texts)


class TestBuildSheetDescriptorChunks:
    """Direct tests of `build_sheet_descriptor_chunks` — the per-section
    descriptor builder that backs the metadata chunks emitted by
    `TabularChunker` when ``ignore_metadata_chunks=False``.

    A character-level tokenizer (1 char == 1 token) is used so the
    `_pack_lines` budget arithmetic is deterministic and expected
    chunks can be spelled out exactly.
    """

    @staticmethod
    def _build(
        csv_text: str,
        heading: str | None = "sheet:T",
        max_tokens: int = 500,
    ) -> list[str]:
        parsed_rows = list(parse_csv_string(csv_text))
        headers = parsed_rows[0].header if parsed_rows else read_csv_header(csv_text)
        if not headers:
            return []
        return build_sheet_descriptor_chunks(
            headers=headers,
            analysis=analyze_sheet(headers, parsed_rows),
            heading=heading or "",
            tokenizer=CharTokenizer(),
            max_tokens=max_tokens,
        )

    def test_basic_descriptor_emits_every_component(self) -> None:
        # --- INPUT -----------------------------------------------------
        # CSV exercises every optional descriptor line:
        #   - id           → numeric AND identifier (unique + id-named)
        #   - Name         → categorical (with sample values)
        #   - Age          → numeric
        #   - joined_at    → date column → contributes to time range
        csv_text = (
            "id,Name,Age,joined_at\n" "1,Alice,30,2024-01-15\n" "2,Bob,25,2024-02-20\n"
        )

        # --- EXPECTED --------------------------------------------------
        expected = [
            "sheet:T\n"
            "Sheet overview.\n"
            "This sheet has 2 rows and 4 columns.\n"
            "Columns: id, Name, Age, joined_at (joined at)\n"
            "Time range: 2024-01-15 to 2024-02-20.\n"
            "Numeric columns (aggregatable by sum, average, min, max): id, Age\n"
            "Categorical columns (groupable, can be counted by value): Name\n"
            "Identifier column: id.\n"
            "Values seen in Name: Alice, Bob"
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text) == expected

    def test_numeric_only_omits_categorical_and_values_seen_lines(self) -> None:
        # --- INPUT -----------------------------------------------------
        # All-numeric CSV: no categorical line, no identifier line, no
        # values-seen lines, no time range.
        csv_text = "x,y\n1,2\n3,4\n"

        # --- EXPECTED --------------------------------------------------
        expected = [
            "sheet:T\n"
            "Sheet overview.\n"
            "This sheet has 2 rows and 2 columns.\n"
            "Columns: x, y\n"
            "Numeric columns (aggregatable by sum, average, min, max): x, y"
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text) == expected

    def test_underscored_column_names_get_friendly_alias_in_descriptor(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Underscored headers get the same `name (name with spaces)`
        # alias used by `format_columns_header`, so retrieval matches
        # either form. The alias appears in every line that names the
        # column (Columns:, Categorical columns:, Values seen in ...).
        csv_text = "MTTR_hours,owner_name\n3,Alice\n5,Bob\n"

        # --- EXPECTED --------------------------------------------------
        expected = [
            "sheet:T\n"
            "Sheet overview.\n"
            "This sheet has 2 rows and 2 columns.\n"
            "Columns: MTTR_hours (MTTR hours), owner_name (owner name)\n"
            "Numeric columns (aggregatable by sum, average, min, max): "
            "MTTR_hours (MTTR hours)\n"
            "Categorical columns (groupable, can be counted by value): "
            "owner_name (owner name)\n"
            "Values seen in owner_name (owner name): Alice, Bob"
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text) == expected

    def test_identifier_column_detected_for_unique_id_named_column(self) -> None:
        # --- INPUT -----------------------------------------------------
        # `uuid` is unique AND its name is in the ID_NAME_TOKENS set, so
        # it gets flagged as the identifier column. Non-numeric values
        # also make it categorical.
        csv_text = "uuid,Name\nabc,Alice\ndef,Bob\n"

        # --- EXPECTED --------------------------------------------------
        expected = [
            "sheet:T\n"
            "Sheet overview.\n"
            "This sheet has 2 rows and 2 columns.\n"
            "Columns: uuid, Name\n"
            "Categorical columns (groupable, can be counted by value): uuid, Name\n"
            "Identifier column: uuid.\n"
            "Values seen in uuid: abc, def\n"
            "Values seen in Name: Alice, Bob"
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text) == expected

    def test_time_range_emitted_for_date_only_column(self) -> None:
        # --- INPUT -----------------------------------------------------
        # A column whose values all parse as dates contributes to the
        # `Time range:` line and is excluded from numeric/categorical
        # classification.
        csv_text = "joined_at\n2024-01-15\n2024-03-20\n2024-02-10\n"

        # --- EXPECTED --------------------------------------------------
        expected = [
            "sheet:T\n"
            "Sheet overview.\n"
            "This sheet has 3 rows and 1 columns.\n"
            "Columns: joined_at (joined at)\n"
            "Time range: 2024-01-15 to 2024-03-20."
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text) == expected

    def test_empty_section_returns_no_chunks(self) -> None:
        # Empty CSV text → nothing to describe.
        assert self._build("") == []

    def test_header_only_csv_emits_descriptor_with_zero_rows(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Header line alone, no data rows. Column names are still useful
        # retrieval signal, so a minimal descriptor is emitted with
        # row_count=0 and no numeric/categorical/values-seen lines.
        csv_text = "col1,col2\n"

        # --- EXPECTED --------------------------------------------------
        expected = [
            "sheet:T\n"
            "Sheet overview.\n"
            "This sheet has 0 rows and 2 columns.\n"
            "Columns: col1, col2"
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text) == expected

    def test_no_heading_means_no_prefix_line_in_chunks(self) -> None:
        # --- INPUT -----------------------------------------------------
        # heading=None → `_pack_lines` runs with prefix="", so emitted
        # chunks do not start with a heading line.
        csv_text = "Name\nAlice\nBob\n"

        # --- EXPECTED --------------------------------------------------
        expected = [
            "Sheet overview.\n"
            "This sheet has 2 rows and 1 columns.\n"
            "Columns: Name\n"
            "Categorical columns (groupable, can be counted by value): Name\n"
            "Values seen in Name: Alice, Bob"
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text, heading=None) == expected

    def test_descriptor_splits_across_chunks_with_heading_repeated(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Tight budget forces the descriptor across multiple chunks. The
        # heading is prepended to every emitted chunk so retrieval keeps
        # context after the split. Lines that exceed the budget on their
        # own are silently skipped.
        #
        # heading="S" (1 char) → prefix_tokens = 1+1 = 2; budget = 60-2 = 58.
        # Lines (and lengths under CharTokenizer):
        #   overview     = "Sheet overview.\nThis sheet has 5 rows and 1 columns." (52)
        #   columns      = "Columns: Name"                                          (13)
        #   categorical  = "Categorical columns (groupable, ...): Name"             (62)  > 58 → SKIPPED
        #   values_seen  = "Values seen in Name: Alice, Bob, Charlie, Dave, Eve"    (51)
        # Pack:
        #   [overview(52)]                                  → fits, current=52
        #   + columns(13): 52+1+13 = 66 > 58 → flush; current=[columns], 13
        #   skip categorical (oversize)
        #   + values_seen(51): 13+1+51 = 65 > 58 → flush; current=[values_seen], 51
        #   end → flush
        csv_text = "Name\nAlice\nBob\nCharlie\nDave\nEve\n"

        # --- EXPECTED --------------------------------------------------
        expected = [
            "S\nSheet overview.\nThis sheet has 5 rows and 1 columns.",
            "S\nColumns: Name",
            "S\nValues seen in Name: Alice, Bob, Charlie, Dave, Eve",
        ]

        # --- ACT -------------------------------------------------------
        out = self._build(csv_text, heading="S", max_tokens=60)

        # --- ASSERT ----------------------------------------------------
        assert out == expected
        # Every emitted chunk fits the budget.
        assert all(len(c) <= 60 for c in out)
        # The dropped categorical line never makes it into output.
        assert all("Categorical columns" not in c for c in out)

    def test_lines_exceeding_budget_are_skipped(self) -> None:
        # --- INPUT -----------------------------------------------------
        # heading="" (no prefix) → budget = max_tokens.
        # Lines:
        #   overview = "Sheet overview.\nThis sheet has 1 rows and 1 columns." (52)  > 30 → SKIPPED
        #   columns  = "Columns: x"                                            (10)
        #   numeric  = "Numeric columns (...): x"                              (59)  > 30 → SKIPPED
        # Only the columns line survives.
        csv_text = "x\n1\n"

        # --- EXPECTED --------------------------------------------------
        expected = ["Columns: x"]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text, heading="", max_tokens=30) == expected


class TestBuildTotalDescriptorChunks:
    """Direct tests of `build_total_descriptor_chunks` — emits the totals
    chunk that names aggregate vocabulary (total/sum/average/min/max/
    count/most frequent) plus per-column aggregates so whole-dataset
    questions retrieve a chunk whose text actually contains the answer.
    """

    @staticmethod
    def _build(
        csv_text: str,
        heading: str | None = "sheet:T",
        max_tokens: int = 1000,
    ) -> list[str]:
        parsed_rows = list(parse_csv_string(csv_text))
        headers = parsed_rows[0].header if parsed_rows else read_csv_header(csv_text)
        if not headers:
            return []
        return build_total_descriptor_chunks(
            headers=headers,
            analysis=analyze_sheet(headers, parsed_rows),
            heading=heading or "",
            tokenizer=CharTokenizer(),
            max_tokens=max_tokens,
        )

    def test_numeric_and_categorical_columns_emit_every_line(self) -> None:
        # --- INPUT -----------------------------------------------------
        # amount → numeric (total=600, avg=200, min=100, max=300, count=3)
        # region → categorical (US appears twice, EU once → top=US (2))
        csv_text = "amount,region\n100,US\n200,EU\n300,US\n"

        # --- EXPECTED --------------------------------------------------
        expected = [
            "sheet:T\n"
            f"{TOTALS_HEADER}\n"
            "Column amount: total (sum across all rows) = 600, average = 200, "
            "minimum = 100, maximum = 300, count = 3.\n"
            "Column region most frequent value: US (2 occurrences).\n"
            "Total row count: 3."
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text) == expected

    def test_numeric_only_sheet_has_no_categorical_line(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Both columns are all-numeric → no "most frequent value" lines.
        csv_text = "x,y\n1,2\n3,4\n"

        # --- EXPECTED --------------------------------------------------
        expected = [
            "sheet:T\n"
            f"{TOTALS_HEADER}\n"
            "Column x: total (sum across all rows) = 4, average = 2, "
            "minimum = 1, maximum = 3, count = 2.\n"
            "Column y: total (sum across all rows) = 6, average = 3, "
            "minimum = 2, maximum = 4, count = 2.\n"
            "Total row count: 2."
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text) == expected

    def test_categorical_only_sheet_has_no_numeric_line(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Non-numeric low-cardinality column → categorical only. "red"
        # wins over "blue" 2-to-1.
        csv_text = "color\nred\nblue\nred\n"

        # --- EXPECTED --------------------------------------------------
        expected = [
            "sheet:T\n"
            f"{TOTALS_HEADER}\n"
            "Column color most frequent value: red (2 occurrences).\n"
            "Total row count: 3."
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text) == expected

    def test_underscored_column_names_get_friendly_alias(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Underscored headers get the same `name (name with spaces)` alias
        # used elsewhere so retrieval matches either surface form.
        csv_text = "total_cost\n100\n200\n"

        # --- EXPECTED --------------------------------------------------
        expected = [
            "sheet:T\n"
            f"{TOTALS_HEADER}\n"
            "Column total_cost (total cost): total (sum across all rows) = 300, "
            "average = 150, minimum = 100, maximum = 200, count = 2.\n"
            "Total row count: 2."
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text) == expected

    def test_non_integer_averages_format_with_decimals(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Whole-number inputs but a fractional average. `_fmt` drops the
        # ".0" when the value is integral and falls back to `:.6g` when
        # it isn't — verify both surfaces on the same line.
        csv_text = "rate\n1\n2\n"

        # --- EXPECTED --------------------------------------------------
        # total=3 (int), avg=1.5 (fractional), min=1, max=2, count=2.
        expected = [
            "sheet:T\n"
            f"{TOTALS_HEADER}\n"
            "Column rate: total (sum across all rows) = 3, average = 1.5, "
            "minimum = 1, maximum = 2, count = 2.\n"
            "Total row count: 2."
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text) == expected

    def test_empty_section_returns_no_chunks(self) -> None:
        # No parsed rows → no totals to report; builder bails out early.
        assert self._build("") == []

    def test_header_only_csv_returns_no_chunks(self) -> None:
        # Header-only CSV yields zero data rows → `parse_csv_string`
        # returns nothing, so the builder returns an empty list.
        assert self._build("col1,col2\n") == []

    def test_no_heading_omits_prefix_line(self) -> None:
        # --- INPUT -----------------------------------------------------
        # heading=None → prefix is just TOTALS_HEADER, no leading heading
        # line in the emitted chunk.
        csv_text = "n\n5\n"

        # --- EXPECTED --------------------------------------------------
        expected = [
            f"{TOTALS_HEADER}\n"
            "Column n: total (sum across all rows) = 5, average = 5, "
            "minimum = 5, maximum = 5, count = 1.\n"
            "Total row count: 1."
        ]

        # --- ACT / ASSERT ---------------------------------------------
        assert self._build(csv_text, heading=None) == expected

    def test_tight_budget_splits_into_multiple_chunks_each_with_header(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Three numeric columns under a tight budget force pack_lines to
        # split across multiple chunks. Every emitted chunk must still
        # start with `heading + TOTALS_HEADER` so retrieval keeps context
        # on whichever chunk wins.
        csv_text = "a,b,c\n1,2,3\n4,5,6\n"

        # --- ACT -------------------------------------------------------
        # Budget chosen so the three aggregate lines can't all fit under
        # TOTALS_HEADER in a single chunk.
        out = self._build(csv_text, heading="S", max_tokens=len(TOTALS_HEADER) + 120)

        # --- ASSERT ----------------------------------------------------
        # Split actually happened.
        assert len(out) > 1
        # Each chunk carries the full prefix (heading + totals header).
        assert all(c.startswith(f"S\n{TOTALS_HEADER}\n") for c in out)
        # Collectively, every per-column aggregate and the row count line
        # must appear somewhere in the output.
        body = "\n".join(out)
        assert "Column a: total (sum across all rows) = 5" in body
        assert "Column b: total (sum across all rows) = 7" in body
        assert "Column c: total (sum across all rows) = 9" in body
        assert "Total row count: 2." in body
