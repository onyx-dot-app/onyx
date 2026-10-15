"""Tests for the bounded "sketch" chunking of spreadsheets.

A character-level tokenizer (1 char == 1 token) keeps token budgets exact.
"""

import io
from collections.abc import Iterator

import pytest
from chonkie import SentenceChunker

import onyx.indexing.chunking.tabular_section_chunker.tabular_section_chunker as tab_mod
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import IndexingDocument, Section, TabularSection
from onyx.indexing.chunking import DocumentChunker
from onyx.indexing.chunking.section_chunker import AccumulatorState
from onyx.indexing.chunking.tabular_section_chunker import TabularChunker
from onyx.indexing.chunking.tabular_section_chunker.sketch import (
    DateOrder,
    SheetSource,
    _parse_number,
    _unit_marker,
    build_workbook_chunks,
    column_label,
    date_key,
    detect_header_row,
    profile_sheet,
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
    chunker = TabularChunker(tokenizer=CharTokenizer())

    out = chunker.chunk_workbook(sections, AccumulatorState(), MAX_TOKENS)

    texts = [p.text for p in out.payloads]
    assert texts[0].startswith("Spreadsheet book.xlsx: 2 sheets (Summary, Readme)")
    assert "Region=East, Total=20" in "\n".join(texts)
    assert all(p.links == {0: "book.xlsx"} for p in out.payloads)
    assert [p.is_continuation for p in out.payloads][0] is False


def test_document_chunker_chunks_all_sheets_of_a_document_once(
    staged_csvs: dict[str, bytes],
) -> None:
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


# --- Dates: the order is inferred from the column, never assumed ------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2024-03-05", "2024-03-05"),
        ("2024-03-05 00:00:00", "2024-03-05"),
        ("2024/03/05", "2024-03-05"),
        ("5 Mar 2024", "2024-03-05"),
        ("5 March 2024", "2024-03-05"),
        ("Mar 5, 2024", "2024-03-05"),
        # A part above 12 cannot be a month, so these settle themselves.
        ("25/03/2024", "2024-03-25"),
        ("03/25/2024", "2024-03-25"),
        ("25.03.2024", "2024-03-25"),
        # Not a real day.
        ("31.02.2024", None),
        ("2024-02-30", None),
        ("hello", None),
        ("", None),
    ],
)
def test_date_key_reads_unambiguous_values(value: str, expected: str | None) -> None:
    assert date_key(value) == expected


def test_date_key_will_not_guess_the_order() -> None:
    # 5/3/2024 is 5 March to most of the world and May 3 in the US. With no
    # order given it is not a date at all.
    assert date_key("5/3/2024") is None
    assert date_key("5.3.2024") is None
    # Told the order, it reads it.
    assert date_key("5/3/2024", DateOrder.DAY_FIRST) == "2024-03-05"
    assert date_key("5/3/2024", DateOrder.MONTH_FIRST) == "2024-05-03"


def _date_column(values: list[str]):
    rows = [["id", "day"]] + [[f"R{idx}", value] for idx, value in enumerate(values)]
    profile = profile_sheet(
        name="S", rows=iter(rows), tokenizer=CharTokenizer(), full_rows_token_budget=10
    )
    return profile.columns[1]


def test_column_infers_month_first_from_its_own_values() -> None:
    # 7/25 can only be month/day, which settles 3/5 in the same column.
    column = _date_column(["3/5/2024", "7/25/2024", "1/9/2024"])

    assert column.date_order is DateOrder.MONTH_FIRST
    assert (column.date_min, column.date_max) == ("2024-01-09", "2024-07-25")
    assert not column.dates_unresolved


def test_column_infers_day_first_from_its_own_values() -> None:
    column = _date_column(["5/3/2024", "25/7/2024", "9/1/2024"])

    assert column.date_order is DateOrder.DAY_FIRST
    assert (column.date_min, column.date_max) == ("2024-01-09", "2024-07-25")
    assert not column.dates_unresolved


def test_dots_are_not_assumed_to_be_european() -> None:
    # The separator says nothing; only a part above 12 does.
    assert _date_column(["25.03.2024", "05.07.2024"]).date_order is DateOrder.DAY_FIRST
    assert (
        _date_column(["03.25.2024", "07.05.2024"]).date_order is DateOrder.MONTH_FIRST
    )


def test_column_with_nothing_to_settle_the_order_is_not_a_date() -> None:
    # Every value could be read either way, so no range is offered at all.
    column = _date_column(["3/5/2024", "7/8/2024", "1/9/2024"])

    assert column.date_order is None
    assert column.dates_unresolved
    assert column.date_min is None


def test_unreadable_date_column_gets_no_time_range_or_monthly_totals() -> None:
    rows = [["id", "day", "amt"]] + [
        [f"R{idx}", f"{idx % 11 + 1}/{(idx + 3) % 11 + 1}/2024", "10"]
        for idx in range(400)
    ]
    text = "\n".join(_chunks([_sheet("S", rows)]))

    assert "Time range" not in text
    assert "by month" not in text


# --- A title block no longer hides the table --------------------------------


@pytest.mark.parametrize("preamble_rows", [5, 25, 150])
def test_table_is_found_below_a_long_title_block(preamble_rows: int) -> None:
    rows = [[f"Report metadata line {idx}", "", ""] for idx in range(preamble_rows)]
    rows.append(["OrderID", "Region", "Amount"])
    rows += [[f"ORD-{idx:04d}", f"r{idx % 4}", str(idx)] for idx in range(600)]

    profile = profile_sheet(
        name="Orders",
        rows=iter(rows),
        tokenizer=CharTokenizer(),
        full_rows_token_budget=1536,
    )

    assert profile.header == ["OrderID", "Region", "Amount"]
    assert profile.row_count == 600
    assert len(profile.preamble) == preamble_rows


def test_a_genuinely_single_column_sheet_is_still_text() -> None:
    rows = [["FRTR Benchmark"], ["Synthetic properties."], ["Contact: ops@x.com"]]

    profile = profile_sheet(
        name="Readme",
        rows=iter(rows),
        tokenizer=CharTokenizer(),
        full_rows_token_budget=1536,
    )

    assert profile.kind.value == "text"
    assert len(profile.text_lines) == 3


# --- Aggregates that would otherwise mislead --------------------------------


def test_percentages_are_not_summed() -> None:
    rows = [["id", "margin_pct", "price"]] + [
        [f"R{idx}", f"{40 + idx % 10}%", f"${100 + idx}"] for idx in range(400)
    ]
    text = "\n".join(_chunks([_sheet("Deals", rows)]))

    margin = next(line for line in text.split("\n") if line.startswith("margin_pct"))
    price = next(line for line in text.split("\n") if line.startswith("price:"))
    # A sum of percentages means nothing, so it is not offered.
    assert "total" not in margin
    assert "average 44.5%" in margin
    # Currency keeps both its total and its unit.
    assert "total" in price and "$" in price


def test_a_clipped_breakdown_says_it_is_clipped() -> None:
    rows = [["id", "day", "amount"]]
    for month in range(120):
        year, mon = 2015 + month // 12, month % 12 + 1
        rows.extend(
            [f"R{month:03d}{day}", f"{year}-{mon:02d}-{day:02d}", "100"]
            for day in range(1, 6)
        )
    text = "\n".join(_chunks([_sheet("Txns", rows)]))

    month_line = next(line for line in text.split("\n") if "by month" in line)
    assert "months shown)" in month_line


def test_sheets_stay_separate_when_merging_would_cost_a_breakdown() -> None:
    header = ["region", "amount"]
    few = [header] + [["East" if idx % 2 else "West", "100"] for idx in range(600)]
    many = [header] + [[f"zone{idx}", "100"] for idx in range(600)]

    alone = "\n".join(_chunks([_sheet("Jan", few)]))
    together = "\n".join(_chunks([_sheet("Jan", few), _sheet("Feb", many)]))

    assert "by region" in alone
    # Pooling the two would push `region` past the category limit and lose the
    # breakdown, so Jan keeps its own profile.
    assert "by region" in together


def test_every_sheet_is_named_even_when_the_chunk_budget_runs_out() -> None:
    sheets = [
        _sheet(
            f"Big{idx:02d}",
            [[f"s{idx}_id", f"s{idx}_cat", f"s{idx}_amt"]]
            + [[f"ID-{j:05d}", f"c{j % 6}", str(j)] for j in range(400)],
        )
        for idx in range(40)
    ]
    sheets.append(_sheet("ZTinyGlossary", [["code", "meaning"], ["ERR_42", "disk"]]))

    text = "\n".join(_chunks(sheets, max_chunks=24))

    # The overview is the index of the workbook: nothing may be invisible.
    assert all(f"Big{idx:02d}" in text for idx in range(40))
    assert "ZTinyGlossary" in text


# --- Units: the only path, so a currency column must not lose its figures ---


@pytest.mark.parametrize(
    "value,number,unit",
    [
        ("$1,250.00", 1250.0, "$"),
        ("-$5", -5.0, "$"),
        ("€500", 500.0, "€"),
        ("£20.50", 20.5, "£"),
        ("1250 €", 1250.0, "€"),
        ("-42%", -42.0, "%"),
        ("42", 42.0, ""),
        # Markers with no number behind them are not numbers.
        ("$", None, "$"),
        ("-", None, ""),
        ("", None, ""),
    ],
)
def test_currency_and_percent_are_read_with_their_unit(
    value: str, number: float | None, unit: str
) -> None:
    assert _parse_number(value) == number
    assert _unit_marker(value) == unit


def test_euro_column_keeps_its_total_and_unit() -> None:
    rows = [["id", "price"]] + [[f"R{idx}", f"€{100 + idx}"] for idx in range(400)]
    text = "\n".join(_chunks([_sheet("Deals", rows)]))

    price = next(line for line in text.split("\n") if line.startswith("price:"))
    assert "total" in price and "€" in price
