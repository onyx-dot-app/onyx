"""Per-section sheet descriptor chunk builder."""

from datetime import date
from itertools import zip_longest

from dateutil.parser import parse as parse_dt
from pydantic import BaseModel
from pydantic import Field

from onyx.connectors.models import Section
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.natural_language_processing.utils import count_tokens
from onyx.utils.csv_utils import parse_csv_string
from onyx.utils.csv_utils import ParsedRow
from onyx.utils.csv_utils import read_csv_header


MAX_NUMERIC_COLS = 12
MAX_CATEGORICAL_COLS = 6
MAX_CATEGORICAL_WITH_SAMPLES = 4
MAX_DISTINCT_SAMPLES = 8
CATEGORICAL_DISTINCT_THRESHOLD = 20
ID_NAME_TOKENS = {"id", "uuid", "uid", "guid", "key"}


class SheetAnalysis(BaseModel):
    row_count: int
    num_cols: int
    numeric_cols: list[int] = Field(default_factory=list)
    categorical_cols: list[int] = Field(default_factory=list)
    categorical_values: dict[int, list[str]] = Field(default_factory=dict)
    id_col: int | None = None
    date_min: date | None = None
    date_max: date | None = None


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

    a = _analyze(headers, parsed_rows)
    lines = [
        _overview_line(a),
        _columns_line(headers),
        _time_range_line(a),
        _numeric_cols_line(headers, a),
        _categorical_cols_line(headers, a),
        _id_col_line(headers, a),
        _values_seen_line(headers, a),
    ]
    return _pack_lines(
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


def _is_numeric(value: str) -> bool:
    try:
        float(value.replace(",", ""))
        return True
    except ValueError:
        return False


def _try_date(value: str) -> date | None:
    if len(value) < 4 or not any(c in value for c in "-/T"):
        return None
    try:
        return parse_dt(value).date()
    except (ValueError, OverflowError, TypeError):
        return None


def _is_id_name(name: str) -> bool:
    lowered = name.lower().strip().replace("-", "_")
    return lowered in ID_NAME_TOKENS or any(
        lowered.endswith(f"_{t}") for t in ID_NAME_TOKENS
    )


def _analyze(headers: list[str], parsed_rows: list[ParsedRow]) -> SheetAnalysis:
    a = SheetAnalysis(row_count=len(parsed_rows), num_cols=len(headers))
    columns = zip_longest(*(pr.row for pr in parsed_rows), fillvalue="")
    for idx, (header, raw_values) in enumerate(zip(headers, columns)):
        # Pull the column's non-empty values; skip if the column is blank.
        values = [v.strip() for v in raw_values if v.strip()]
        if not values:
            continue

        # Identifier: id-named column whose values are all unique. Detected
        # before classification so a numeric `id` column still gets flagged.
        distinct = set(values)
        if a.id_col is None and len(distinct) == len(values) and _is_id_name(header):
            a.id_col = idx

        # Numeric: every value parses as a number.
        if all(_is_numeric(v) for v in values):
            a.numeric_cols.append(idx)
            continue

        # Date: every value parses as a date — fold into the sheet-wide range.
        dates = [_try_date(v) for v in values]
        if all(d is not None for d in dates):
            dmin = min(filter(None, dates))
            dmax = max(filter(None, dates))
            a.date_min = dmin if a.date_min is None else min(a.date_min, dmin)
            a.date_max = dmax if a.date_max is None else max(a.date_max, dmax)
            continue

        # Categorical: low-cardinality column — keep distinct values for samples.
        if len(distinct) <= max(CATEGORICAL_DISTINCT_THRESHOLD, len(values) // 2):
            a.categorical_cols.append(idx)
            a.categorical_values[idx] = list(distinct)
    return a


def _pack_lines(
    lines: list[str],
    prefix: str,
    tokenizer: BaseTokenizer,
    max_tokens: int,
) -> list[str]:
    """Greedily pack lines into chunks ≤ max_tokens. Lines that on
    their own exceed max_tokens (after accounting for the prefix) are
    skipped. ``prefix`` is prepended to every emitted chunk."""
    prefix_tokens = count_tokens(prefix, tokenizer) + 1 if prefix else 0
    budget = max_tokens - prefix_tokens

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for line in lines:
        line_tokens = count_tokens(line, tokenizer)
        if line_tokens > budget:
            continue
        sep = 1 if current else 0
        if current_tokens + sep + line_tokens > budget:
            chunks.append(_join_with_prefix(current, prefix))
            current = [line]
            current_tokens = line_tokens
        else:
            current.append(line)
            current_tokens += sep + line_tokens
    if current:
        chunks.append(_join_with_prefix(current, prefix))
    return chunks


def _join_with_prefix(lines: list[str], prefix: str) -> str:
    body = "\n".join(lines)
    return f"{prefix}\n{body}" if prefix else body
