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
        csv_text = "Name,Age,City\n" "Alice,30,NYC\n" "Bob,25,SF\n"
        link = "sheet:People"
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
        # prelude = "sheet:S\nColumns: col, val" (25 chars = 25 tokens)
        # At content_token_limit=57, row_budget = max(16, 57-31-1) = 25.
        # Each row "col=a, val=1" is 12 tokens; two rows + \n = 25 (fits),
        # three rows + 2×\n = 38 (overflows) → split after 2 rows.
        csv_text = "col,val\n" "a,1\n" "b,2\n" "c,3\n" "d,4\n"
        link = "sheet:S"
        content_token_limit = 57

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            ("sheet:S\n" "Columns: col, val\n" "col=a, val=1\n" "col=b, val=2"),
            ("sheet:S\n" "Columns: col, val\n" "col=c, val=3\n" "col=d, val=4"),
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

    # Add back in shortly
    # def test_header_only_csv_produces_single_prelude_chunk(self) -> None:
    #     # --- INPUT -----------------------------------------------------
    #     csv_text = "col1,col2\n"
    #     link = "sheet:Headers"

    #     # --- EXPECTED --------------------------------------------------
    #     expected_texts = [
    #         "sheet:Headers\nColumns: col1, col2",
    #     ]

    #     # --- ACT -------------------------------------------------------
    #     out = _make_chunker().chunk_section(
    #         _tabular_section(csv_text, link=link),
    #         AccumulatorState(),
    #         content_token_limit=500,
    #     )

    #     # --- ASSERT ----------------------------------------------------
    #     assert [p.text for p in out.payloads] == expected_texts

    def test_empty_cells_dropped_from_chunk_text(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Alice's Age is empty; Bob's City is empty. Empty cells should
        # not appear as `field=` pairs in the output.
        csv_text = "Name,Age,City\n" "Alice,,NYC\n" "Bob,25,\n"
        link = "sheet:P"

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
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
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
        link = "sheet:P"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            ("sheet:P\n" "Columns: Name, Notes\n" "Name=Alice, Notes=Hello, world"),
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
        csv_text = "A,B\n" "\n" "1,2\n" "\n" "\n" "3,4\n"
        link = "sheet:S"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            ("sheet:S\n" "Columns: A, B\n" "A=1, B=2\n" "A=3, B=4"),
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

        csv_text = "a,b\n" "1,2\n"
        link = "sheet:S"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            pending_text,  # flushed accumulator
            ("sheet:S\n" "Columns: a, b\n" "a=1, b=2"),
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

    def test_multi_row_packing_under_budget_emits_single_chunk(self) -> None:
        # --- INPUT -----------------------------------------------------
        # Three small rows (20 tokens each) under a generous
        # content_token_limit=100 should pack into ONE chunk — prelude
        # emitted once, rows stacked beneath it.
        csv_text = (
            "x\n" "aaaaaaaaaaaaaaaaaa\n" "bbbbbbbbbbbbbbbbbb\n" "cccccccccccccccccc\n"
        )
        link = "S"
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
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
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
        link = "S"
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
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
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
        link = "S"
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
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
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
        link = "S"
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
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
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
        link = "sheet:M"

        # --- EXPECTED --------------------------------------------------
        expected_texts = [
            (
                "sheet:M\n"
                "Columns: MTTR_hours (MTTR hours), id, owner_name (owner name)\n"
                "MTTR_hours=3, id=42, owner_name=Alice"
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
        link = "S"
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
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
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
        link = "LongSheetName"
        content_token_limit = 15

        # --- EXPECTED --------------------------------------------------
        expected_texts = ["Columns: x\nx=y"]

        # --- ACT -------------------------------------------------------
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
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
        link = "S"
        content_token_limit = 20

        # --- EXPECTED --------------------------------------------------
        expected_texts = ["S\nABC=1, DEF=2"]

        # --- ACT -------------------------------------------------------
        out = _make_chunker().chunk_section(
            _tabular_section(csv_text, link=link),
            AccumulatorState(),
            content_token_limit=content_token_limit,
        )

        # --- ASSERT ----------------------------------------------------
        assert [p.text for p in out.payloads] == expected_texts
