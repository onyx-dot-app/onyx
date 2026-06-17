import pytest

from onyx.utils.csv_utils import sanitize_csv_cell
from onyx.utils.csv_utils import sanitize_csv_cell_or_none
from onyx.utils.csv_utils import sanitize_csv_row


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
