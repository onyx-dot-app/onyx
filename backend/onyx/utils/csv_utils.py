import csv
import io
from collections.abc import Generator

from pydantic import BaseModel


class ParsedRow(BaseModel):
    header: list[str]
    row: list[str]


def normalize_csv_newlines(text: str) -> str:
    """Normalize Windows (\\r\\n) and old-Mac (\\r) line endings to Unix (\\n).

    io.StringIO does not split on bare \\r, so csv.reader raises
    "new-line character seen in unquoted field" for files that use \\r as
    the row separator (e.g. old Mac-format CSVs from Google Drive).
    Call this as a fallback when csv.reader raises csv.Error.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_csv_header(csv_text: str) -> list[str]:
    """Return the first non-blank row (the header) of a CSV string, or
    [] if the text has no usable header.
    """
    if not csv_text.strip():
        return []
    for row in csv.reader(io.StringIO(csv_text)):
        if any(c.strip() for c in row):
            return row
    return []


def parse_csv_string(csv_text: str) -> Generator[ParsedRow, None, None]:
    """
    Takes in a string in the form of a CSV and yields back
    each row + header in the csv.
    """
    if not csv_text.strip():
        return

    reader = csv.reader(io.StringIO(csv_text))
    header: list[str] | None = None
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        if header is None:
            header = row
            continue
        yield ParsedRow(header=header, row=row)
