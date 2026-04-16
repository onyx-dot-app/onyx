"""Per-section sheet descriptor chunk builder."""

from onyx.connectors.models import Section
from onyx.indexing.chunking.tabular_section_chunker.analysis import analyze_sheet
from onyx.indexing.chunking.tabular_section_chunker.analysis import SheetAnalysis
from onyx.indexing.chunking.tabular_section_chunker.util import pack_lines
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.utils.csv_utils import parse_csv_string
from onyx.utils.csv_utils import read_csv_header


MAX_NUMERIC_COLS = 12
MAX_CATEGORICAL_COLS = 6
MAX_CATEGORICAL_WITH_SAMPLES = 4
MAX_DISTINCT_SAMPLES = 8


def build_sheet_descriptor_chunks(
    section: Section,
    tokenizer: BaseTokenizer,
    max_tokens: int,
) -> list[str]:
    """Build sheet descriptor chunk(s) from a parsed CSV section.

    Output (lines joined by "\\n"; lines that overflow ``max_tokens`` on
    their own are skipped; ``section.heading`` is prepended to every
    emitted chunk so retrieval keeps sheet context after a split):

        {section.heading}                                                     # optional
        Sheet overview.
        This sheet has {N} rows and {M} columns.
        Columns: {col1}, {col2}, ...
        Time range: {start} to {end}.                                         # optional
        Numeric columns (aggregatable by sum, average, min, max): ...         # optional
        Categorical columns (groupable, can be counted by value): ...         # optional
        Identifier column: {col}.                                             # optional
        Values seen in {col}: {v1}, {v2}, ...                                 # optional, repeated
    """
    text = section.text or ""
    parsed_rows = list(parse_csv_string(text))
    headers = parsed_rows[0].header if parsed_rows else read_csv_header(text)
    if not headers:
        return []

    a = analyze_sheet(headers, parsed_rows)
    lines = [
        _overview_line(a),
        _columns_line(headers),
        _time_range_line(a),
        _numeric_cols_line(headers, a),
        _categorical_cols_line(headers, a),
        _id_col_line(headers, a),
        _values_seen_line(headers, a),
    ]
    return pack_lines(
        [line for line in lines if line],
        prefix=section.heading or "",
        tokenizer=tokenizer,
        max_tokens=max_tokens,
    )


def _overview_line(a: SheetAnalysis) -> str:
    return (
        "Sheet overview.\n"
        f"This sheet has {a.row_count} rows and {a.num_cols} columns."
    )


def _columns_line(headers: list[str]) -> str:
    return "Columns: " + ", ".join(_label(h) for h in headers)


def _time_range_line(a: SheetAnalysis) -> str:
    if not (a.date_min and a.date_max):
        return ""
    return f"Time range: {a.date_min} to {a.date_max}."


def _numeric_cols_line(headers: list[str], a: SheetAnalysis) -> str:
    if not a.numeric_cols:
        return ""
    names = ", ".join(_label(headers[i]) for i in a.numeric_cols[:MAX_NUMERIC_COLS])
    return f"Numeric columns (aggregatable by sum, average, min, max): {names}"


def _categorical_cols_line(headers: list[str], a: SheetAnalysis) -> str:
    if not a.categorical_cols:
        return ""
    names = ", ".join(
        _label(headers[i]) for i in a.categorical_cols[:MAX_CATEGORICAL_COLS]
    )
    return f"Categorical columns (groupable, can be counted by value): {names}"


def _id_col_line(headers: list[str], a: SheetAnalysis) -> str:
    if a.id_col is None:
        return ""
    return f"Identifier column: {_label(headers[a.id_col])}."


def _values_seen_line(headers: list[str], a: SheetAnalysis) -> str:
    rows: list[str] = []
    for ci in a.categorical_cols[:MAX_CATEGORICAL_WITH_SAMPLES]:
        sample = sorted(a.categorical_values.get(ci, []))[:MAX_DISTINCT_SAMPLES]
        if sample:
            rows.append(f"Values seen in {_label(headers[ci])}: " + ", ".join(sample))
    return "\n".join(rows)


def _label(name: str) -> str:
    return f"{name} ({name.replace('_', ' ')})" if "_" in name else name
