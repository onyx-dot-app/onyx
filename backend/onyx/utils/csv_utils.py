import csv
import io
from collections.abc import Generator

from pydantic import BaseModel

_NEWLINE_CSV_ERROR = "new-line character seen in unquoted field"


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


def parse_csv_string(csv_text: str) -> Generator[ParsedRow, None, None]:
    """Yield each data row paired with its header from a CSV string.

    Falls back to normalized line endings when csv.reader raises the
    specific "new-line character" error (e.g. old Mac-format CSVs).
    """

    def _parse(text: str) -> list[ParsedRow]:
        reader = csv.reader(io.StringIO(text))
        header: list[str] | None = None
        rows: list[ParsedRow] = []
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            if header is None:
                header = row
                continue
            rows.append(ParsedRow(header=header, row=row))
        return rows

    if not csv_text.strip():
        return
    try:
        rows = _parse(csv_text)
    except csv.Error as e:
        if _NEWLINE_CSV_ERROR not in str(e):
            raise csv.Error(f"parse_csv_string failed: {e}") from e
        try:
            rows = _parse(normalize_csv_newlines(csv_text))
        except csv.Error as e2:
            raise csv.Error(f"parse_csv_string failed: {e2}") from e2
    yield from rows
