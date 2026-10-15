"""Tests for the bounded "sketch" chunking of spreadsheets.

A character-level tokenizer (1 char == 1 token) keeps token budgets exact.
"""

import io
from collections.abc import Iterator

import pytest
from chonkie import SentenceChunker

import onyx.indexing.chunking.tabular_section_chunker.tabular_section_chunker as tab_mod
from onyx.configs.constants import DocumentSource, TabularChunkingStrategy
from onyx.connectors.models import IndexingDocument, Section, TabularSection
from onyx.indexing.chunking import DocumentChunker
from onyx.indexing.chunking.section_chunker import AccumulatorState
from onyx.indexing.chunking.tabular_section_chunker import TabularChunker
from onyx.indexing.chunking.tabular_section_chunker.sketch import (
    SheetSource,
    build_workbook_chunks,
    column_label,
    detect_header_row,
)
from onyx.natural_language_processing.utils import BaseTokenizer


class CharTokenizer(BaseTokenizer):
    def encode(self, string: str) -> list[int]:
        return [ord(c) for c in string]

    def tokenize(self, string: str) -> list[str]:
        return list(string)

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(t) for t in tokens)


MAX_TOKENS = 500


def _sheet(name: str, rows: list[list[str]]) -> SheetSource:
    return SheetSource(name=name, open_rows=lambda: iter(rows))


def _chunks(
    sheets: list[SheetSource],
    max_chunks: int = 24,
    value_chunks: int = 2,
) -> list[str]:
    return build_workbook_chunks(
        file_name="book.xlsx",
        sheets=sheets,
        tokenizer=CharTokenizer(),
        max_tokens=MAX_TOKENS,
        full_rows_max_chunks=3,
        value_chunks_per_sheet=value_chunks,
        max_chunks=max_chunks,
    )


def _large_sales_rows(count: int) -> list[list[str]]:
    regions = ["West", "East", "North"]
    header = [["OrderID", "Date", "Region", "AmountUSD"]]
    return header + [
        [
            f"ORD-{idx}",
            f"2024-{(idx % 12) + 1:02d}-15 00:00:00",
            regions[idx % 3],
            str(idx % 7 + 1),
        ]
        for idx in range(1, count + 1)
    ]


# --- Header detection and column labels -------------------------------------


def test_detect_header_row_skips_title_rows() -> None:
    rows = [
        ["Quarterly report"],
        ["Date", "Region", "Revenue"],
        ["2024-01-01", "West", "10"],
    ]
    assert detect_header_row(rows) == 1


def test_detect_header_row_returns_none_when_data_starts_at_first_row() -> None:
    rows = [["PAY-001", "B"], ["PAY-002", "C"], ["PAY-003", "A"]]
    assert detect_header_row(rows) is None


def test_detect_header_row_returns_none_for_single_column_text() -> None:
    assert detect_header_row([["Title"], ["Some description"]]) is None


@pytest.mark.parametrize(
    "name,expected",
    [
        ("AcqPriceUSD", "AcqPriceUSD (acquisition Price USD)"),
        ("MTTR_hours", "MTTR_hours (MTTR hours)"),
        ("TotalMWh", "TotalMWh (Total MWh)"),
        ("ARPUUSD", "ARPUUSD (ARPU USD)"),
        ("Company Name", "Company Name"),
        ("Date", "Date"),
    ],
)
def test_column_label(name: str, expected: str) -> None:
    assert column_label(name) == expected


# --- Workbook chunks ----------------------------------------------------------


def test_small_sheet_keeps_every_row_and_readme_goes_to_overview() -> None:
    readme = _sheet("Readme", [["Sales book"], ["Orders by region and month."]])
    summary = _sheet(
        "Summary",
        [["Region", "Total"], ["West", "10"], ["East", "20"]],
    )

    chunks = _chunks([readme, summary])

    joined = "\n".join(chunks)
    assert chunks[0].startswith("Spreadsheet book.xlsx: 2 sheets (Readme, Summary)")
    assert "About: Sales book Orders by region and month." in joined
    assert "Region=West, Total=10" in joined
    assert "Region=East, Total=20" in joined
    assert all(len(chunk) <= MAX_TOKENS for chunk in chunks)


def test_large_sheet_gets_a_bounded_profile_instead_of_rows() -> None:
    chunks = _chunks([_sheet("Orders", _large_sales_rows(5000))])

    joined = "\n".join(chunks)
    # Overview plus a profile of at most two chunks; no value chunks because
    # the sheet has no free-text column.
    assert len(chunks) <= 3
    assert all(len(chunk) <= MAX_TOKENS for chunk in chunks)
    assert "Orders: 5000 rows x 4 columns" in joined
    assert (
        "Identifiers: OrderID (Order ID) ORD-1 ... ORD-5000 (5000 distinct)" in joined
    )
    assert "Time range: Date 2024-01-15 to 2024-12-15" in joined
    assert "Region values (count): East (1667); North (1667); West (1666)" in joined
    assert "AmountUSD (Amount USD): total 19997" in joined
    assert "Total AmountUSD by Region (highest first):" in joined
    assert "Total AmountUSD by month: 2024-01" in joined
    assert "ORD-2500," not in joined


def test_text_columns_get_value_chunks_and_skip_redundant_name_parts() -> None:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    rows = [["Company", "First Name", "Full Name", "Title"]]
    for idx in range(400):
        first = f"First{letters[idx % 26]}{letters[idx // 26]}"
        rows.append(
            [
                f"Acme {letters[idx % 26]}{letters[idx % 7]} Corp",
                first,
                f"{first} Last{letters[idx % 13]}",
                f"Director of {letters[idx % 26]}{letters[idx % 5]} Team",
            ]
        )

    chunks = _chunks([_sheet("People", rows)], value_chunks=2)

    joined = "\n".join(chunks)
    assert "People: more values" in joined
    assert "Full Name: " in joined
    assert "Title: " in joined
    # First names repeat inside full names, so they get no value list.
    assert "First Name (" not in joined
    assert "First Name: " not in joined
    assert len(chunks) <= 1 + 2 + 2


def test_sheets_with_the_same_columns_share_one_profile() -> None:
    chunks = _chunks(
        [
            _sheet("Jan", _large_sales_rows(3000)),
            _sheet("Feb", _large_sales_rows(3000)),
        ]
    )

    joined = "\n".join(chunks)
    assert "sheets Jan, Feb (same columns): 6000 rows" in joined
    assert joined.count("Totals across all rows:") == 1


def test_max_chunks_caps_a_workbook_with_many_sheets() -> None:
    sheets = [
        _sheet(
            f"S{idx}",
            [[f"Key{idx}", f"Value{idx}"]]
            + [[f"k{idx}-{row}" * 4, str(row)] for row in range(60)],
        )
        for idx in range(30)
    ]

    chunks = _chunks(sheets, max_chunks=10)

    assert len(chunks) == 10


# --- Chunker wiring -----------------------------------------------------------


@pytest.fixture
def staged_csvs(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, bytes]]:
    store: dict[str, bytes] = {}

    class _FakeStore:
        def read_file(
            self, file_id: str, mode: str | None = None, use_tempfile: bool = False
        ) -> io.BytesIO:
            del mode, use_tempfile
            return io.BytesIO(store[file_id])

    monkeypatch.setattr(tab_mod, "get_default_file_store", lambda: _FakeStore())
    yield store


def test_chunk_workbook_reads_staged_sheets(staged_csvs: dict[str, bytes]) -> None:
    staged_csvs["a"] = b"Region,Total\nWest,10\nEast,20\n"
    staged_csvs["b"] = b"Note\nHello\n"
    sections = [
        TabularSection(
            link="book.xlsx", csv_file_id="a", heading="book.xlsx :: Summary"
        ),
        TabularSection(
            link="book.xlsx", csv_file_id="b", heading="book.xlsx :: Readme"
        ),
    ]
    chunker = TabularChunker(
        tokenizer=CharTokenizer(), strategy=TabularChunkingStrategy.SKETCH
    )

    out = chunker.chunk_workbook(sections, AccumulatorState(), MAX_TOKENS)

    texts = [p.text for p in out.payloads]
    assert texts[0].startswith("Spreadsheet book.xlsx: 2 sheets (Summary, Readme)")
    assert "Region=East, Total=20" in "\n".join(texts)
    assert all(p.links == {0: "book.xlsx"} for p in out.payloads)
    assert [p.is_continuation for p in out.payloads][0] is False


def test_document_chunker_chunks_all_sheets_of_a_document_once(
    staged_csvs: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        tab_mod, "TABULAR_CHUNKING_STRATEGY", TabularChunkingStrategy.SKETCH
    )
    staged_csvs["a"] = b"Region,Total\nWest,10\n"
    staged_csvs["b"] = b"Region,Total\nEast,20\n"

    def token_counter(text: str) -> int:
        return len(text)

    splitter = SentenceChunker(
        tokenizer_or_token_counter=token_counter,
        chunk_size=MAX_TOKENS,
        chunk_overlap=0,
        return_type="texts",
    )
    document_chunker = DocumentChunker(
        tokenizer=CharTokenizer(),
        blurb_splitter=splitter,
        chunk_splitter=splitter,
    )
    sections: list[Section] = [
        TabularSection(link="b.xlsx", csv_file_id="a", heading="b.xlsx :: One"),
        TabularSection(link="b.xlsx", csv_file_id="b", heading="b.xlsx :: Two"),
    ]
    document = IndexingDocument(
        id="doc",
        source=DocumentSource.FILE,
        semantic_identifier="b.xlsx",
        title="b.xlsx",
        metadata={},
        sections=[],
        processed_sections=sections,
    )

    chunks = document_chunker.chunk(
        document=document,
        sections=sections,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        content_token_limit=MAX_TOKENS,
    )

    joined = "\n".join(c.content for c in chunks)
    assert joined.count("Spreadsheet b.xlsx: 2 sheets (One, Two)") == 1
    assert "Region=West, Total=10" in joined
    assert "Region=East, Total=20" in joined
