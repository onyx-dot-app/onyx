import csv
import io
from collections.abc import Generator, Iterable, Iterator, Mapping

from pydantic import BaseModel

# Python's csv default field size limit is 131072 bytes (128 KiB), which
# real-world data (long descriptions, pasted docs, base64 blobs) routinely
# exceeds — the parser then raises `Error: field larger than field limit
# (131072)` and fails the whole row, aborting indexing of the CSV section
# (ONYX-BACKEND-H6FM). Bump to 128 MiB, matching the order of magnitude the
# salesforce connector already opts into for bulk exports.
_CSV_FIELD_SIZE_LIMIT_BYTES = 128 * 1024 * 1024
csv.field_size_limit(_CSV_FIELD_SIZE_LIMIT_BYTES)

_NEWLINE_CSV_ERROR = "new-line character seen in unquoted field"

# The separators a spreadsheet actually writes into a file named ".csv". Excel
# writes the list separator of the machine's locale, which is a semicolon across
# most of Europe, and a tab-separated export is routinely saved as .csv.
CSV_DELIMITERS = (",", ";", "\t", "|")

# How much of the file the detection looks at. A separator that holds for the
# first rows holds for the file.
_DELIMITER_SAMPLE_CHARS = 64 * 1024
_DELIMITER_SAMPLE_ROWS = 20


def _consistent_column_count(sample: str, delimiter: str, truncated: bool) -> int:
    """Columns per row under `delimiter`, or 0 when the rows disagree.

    A separator the file was not written with either does not occur at all (one
    column) or occurs by accident, and then the rows do not line up. Requiring
    the same count on every row is what keeps a comma inside a sentence, or a
    semicolon inside a quoted field, from being read as a separator.

    When `truncated` is set, the sample is a prefix of a longer file, so the row
    it ends in stops wherever the read did, between two fields or inside a
    quoted one. That row is left out rather than counted as having fewer columns.
    """
    rows: list[list[str]] = []
    try:
        for index, row in enumerate(
            csv.reader(io.StringIO(sample, newline=""), delimiter=delimiter)
        ):
            if index >= _DELIMITER_SAMPLE_ROWS:
                break
            # A blank or whitespace-only line says nothing about the separator.
            if any(cell.strip() for cell in row):
                rows.append(row)
        else:
            if truncated and len(rows) > 1:
                rows.pop()
    except csv.Error:
        return 0
    count = 0
    for row in rows:
        if count and len(row) != count:
            return 0
        count = len(row)
    return count if count > 1 else 0


def detect_csv_delimiter(csv_text: str) -> str:
    """Return the separator `csv_text` was written with, defaulting to a comma.

    `csv.reader` defaults to a comma, and reading a semicolon-separated export
    with one does not fail: every row comes back as a single field holding the
    whole line.

    A comma that lines up is kept: it is the format's own separator, so a `;` or
    `|` that happens to occur the same number of times in every row is data.
    Otherwise the separator that lines up into the most columns wins.

    Python's own `csv.Sniffer` is not used: it searches the whole candidate
    space and on a single-column file splits the header `Note` into `No` and
    `e`. Choosing among a fixed set, and only when the column counts line up,
    cannot do that.
    """
    truncated = len(csv_text) > _DELIMITER_SAMPLE_CHARS
    sample = csv_text[:_DELIMITER_SAMPLE_CHARS]
    if _consistent_column_count(sample, ",", truncated):
        return ","
    best_delimiter, best_columns = ",", 0
    for delimiter in CSV_DELIMITERS:
        columns = _consistent_column_count(sample, delimiter, truncated)
        if columns > best_columns:
            best_delimiter, best_columns = delimiter, columns
    return best_delimiter


# Leading characters that spreadsheet software (Excel, LibreOffice, Google
# Sheets) interprets as the start of a formula. Exporting user-supplied text
# beginning with one of these enables CSV/formula injection (e.g. DDE payloads
# like `=cmd|' /C calc'!A1`) against whoever opens the export.
_FORMULA_PREFIX_CHARS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: str) -> str:
    """Neutralize spreadsheet formula injection in a CSV cell.

    Prefixes values that start with a formula-trigger character with a
    single quote, which spreadsheet software treats as "render as text".
    """
    if value.startswith(_FORMULA_PREFIX_CHARS):
        return "'" + value
    return value


def sanitize_csv_cell_or_none(value: str | None) -> str | None:
    """sanitize_csv_cell that passes None through."""
    return sanitize_csv_cell(value) if value is not None else None


def sanitize_csv_row(row: Mapping[str, str | None]) -> dict[str, str | None]:
    """Apply sanitize_csv_cell to every non-None value of a CSV row dict."""
    return {key: sanitize_csv_cell_or_none(value) for key, value in row.items()}


class ParsedRow(BaseModel):
    header: list[str]
    row: list[str]


def normalize_csv_newlines(text: str) -> str:
    """Normalize Windows (\\r\\n) and old-Mac (\\r) line endings to Unix (\\n).

    io.StringIO does not split on bare \\r, so csv.reader raises
    "new-line character seen in unquoted field" for files that use \\r as
    the row separator (e.g. old Mac-format CSVs from Google Drive).
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_csv_header(csv_text: str) -> list[str]:
    """Return the first non-blank row (the header) of a CSV string, or
    [] if the text has no usable header.

    Falls back to normalized line endings when csv.reader raises the
    specific "new-line character" error.
    """

    def _read(text: str) -> list[str]:
        for row in csv.reader(io.StringIO(text)):
            if any(c.strip() for c in row):
                return row
        return []

    if not csv_text.strip():
        return []
    try:
        return _read(csv_text)
    except csv.Error as e:
        if _NEWLINE_CSV_ERROR not in str(e):
            raise csv.Error(f"read_csv_header failed: {e}") from e
    try:
        return _read(normalize_csv_newlines(csv_text))
    except csv.Error as e:
        raise csv.Error(f"read_csv_header failed: {e}") from e


def parse_csv_stream(lines: Iterable[str]) -> Iterator[ParsedRow]:
    """Stream each data row paired with its header from a CSV line source (a file
    handle or any iterable of lines), header first, without buffering the input.

    Assumes clean line endings; `parse_csv_string` wraps this for in-memory
    strings that may use bare-``\\r`` (old Mac) row separators.
    """
    reader = csv.reader(lines)
    header: list[str] | None = None
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        if header is None:
            header = row
            continue
        yield ParsedRow(header=header, row=row)


def parse_csv_string(csv_text: str) -> Generator[ParsedRow, None, None]:
    """Yield each data row paired with its header from a CSV string.

    Falls back to normalized line endings when csv.reader raises the
    specific "new-line character" error (e.g. old Mac-format CSVs).
    """
    if not csv_text.strip():
        return
    try:
        rows = list(parse_csv_stream(io.StringIO(csv_text)))
    except csv.Error as e:
        if _NEWLINE_CSV_ERROR not in str(e):
            raise csv.Error(f"parse_csv_string failed: {e}") from e
        try:
            rows = list(parse_csv_stream(io.StringIO(normalize_csv_newlines(csv_text))))
        except csv.Error as e2:
            raise csv.Error(f"parse_csv_string failed: {e2}") from e2
    yield from rows
