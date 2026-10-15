import csv
import io
from collections.abc import Iterator

import pytest

from onyx.utils.csv_utils import (
    csv_reader,
    parse_csv_stream,
    read_csv_header,
    sanitize_csv_cell,
    sanitize_csv_cell_or_none,
    sanitize_csv_row,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        # Formula-trigger prefixes get neutralized with a leading quote
        ("=cmd|' /C calc'!A1", "'=cmd|' /C calc'!A1"),
        ("=1+1", "'=1+1"),
        ("+1234", "'+1234"),
        ("-1234", "'-1234"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tleading-tab", "'\tleading-tab"),
        ("\rleading-cr", "'\rleading-cr"),
        # Email local parts can legally start with a formula trigger
        ("=evil@example.com", "'=evil@example.com"),
        # Normal values pass through untouched
        ("hello world", "hello world"),
        ("user@example.com", "user@example.com"),
        ("1234", "1234"),
        ("", ""),
        # Formula chars not in the leading position are fine
        ("a=b", "a=b"),
        ("foo + bar", "foo + bar"),
    ],
)
def test_sanitize_csv_cell(value: str, expected: str) -> None:
    assert sanitize_csv_cell(value) == expected


def test_sanitize_csv_cell_or_none() -> None:
    assert sanitize_csv_cell_or_none(None) is None
    assert sanitize_csv_cell_or_none("=SUM(A1)") == "'=SUM(A1)"
    assert sanitize_csv_cell_or_none("safe") == "safe"


def test_sanitize_csv_row_sanitizes_values_and_preserves_none() -> None:
    row: dict[str, str | None] = {
        "user_message": '=HYPERLINK("http://evil.example")',
        "ai_response": "a normal response",
        "feedback_text": None,
        "user_email": "@user@example.com",
    }

    assert sanitize_csv_row(row) == {
        "user_message": '\'=HYPERLINK("http://evil.example")',
        "ai_response": "a normal response",
        "feedback_text": None,
        "user_email": "'@user@example.com",
    }


def test_sanitize_csv_row_keys_unchanged() -> None:
    row: dict[str, str | None] = {"=key": "value"}
    # Keys come from our own model fields, not user input — only values are
    # sanitized.
    assert sanitize_csv_row(row) == {"=key": "value"}


# --- The field size limit is process-global ---------------------------------

_LONG_FIELD = "x" * 200_000
_CSV_WITH_LONG_FIELD = f'name,notes\na,"{_LONG_FIELD}"\n'


@pytest.fixture
def lowered_field_size_limit() -> Iterator[None]:
    """Put the csv limit back where Python starts it, as if nothing had raised
    it yet. Reading must work regardless of what ran before."""
    previous = csv.field_size_limit(131_072)
    try:
        yield
    finally:
        csv.field_size_limit(previous)


@pytest.mark.usefixtures("lowered_field_size_limit")
def test_csv_reader_reads_a_field_longer_than_the_default_limit() -> None:
    rows = list(csv_reader(io.StringIO(_CSV_WITH_LONG_FIELD)))

    assert rows[1][1] == _LONG_FIELD


@pytest.mark.usefixtures("lowered_field_size_limit")
def test_read_csv_header_survives_a_long_field() -> None:
    assert read_csv_header(_CSV_WITH_LONG_FIELD) == ["name", "notes"]


@pytest.mark.usefixtures("lowered_field_size_limit")
def test_parse_csv_stream_survives_a_long_field() -> None:
    rows = list(parse_csv_stream(io.StringIO(_CSV_WITH_LONG_FIELD)))

    assert rows[0].row[1] == _LONG_FIELD


def test_importing_the_module_does_not_raise_the_limit() -> None:
    # The limit belongs at the point of use. If importing set it, a caller
    # reaching csv.reader another way would silently get the default.
    previous = csv.field_size_limit(131_072)
    try:
        assert csv.field_size_limit() == 131_072
    finally:
        csv.field_size_limit(previous)
