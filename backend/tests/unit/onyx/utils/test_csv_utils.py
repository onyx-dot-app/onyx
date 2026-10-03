import pytest

from onyx.utils.csv_utils import (
    detect_csv_delimiter,
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


class TestDetectCsvDelimiter:
    """`csv.reader` defaults to a comma; a .csv is not always comma-separated."""

    ROWS = ["Name;Region;Units", "Widget;EU;12", "Gadget;US;7"]

    @pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
    def test_detects_the_delimiter_the_file_was_written_with(
        self, delimiter: str
    ) -> None:
        text = "\n".join(row.replace(";", delimiter) for row in self.ROWS) + "\n"

        assert detect_csv_delimiter(text) == delimiter

    @pytest.mark.parametrize(
        "text",
        [
            # A separator inside a quoted field is not a separator.
            'Name,Note\nWidget,"a; b"\nGadget,"c; d"\n',
            # Rows that do not line up leave the default in place.
            "Note\na; b\nc; d\n",
            "name,value\nAlice,1\nBob,2,extra\n",
            "",
            "\n\n",
        ],
    )
    def test_falls_back_to_a_comma(self, text: str) -> None:
        assert detect_csv_delimiter(text) == ","

    def test_a_single_column_header_is_not_split(self) -> None:
        """csv.Sniffer splits `Note` on the `t` inside it; this must not."""
        assert detect_csv_delimiter("Note\nalpha\nbeta\n") == ","

    def test_a_whitespace_only_line_is_not_a_row(self) -> None:
        assert detect_csv_delimiter("Name;Region\nWidget;EU\n   \nGadget;US\n") == ";"

    def test_a_comma_that_lines_up_is_kept(self) -> None:
        """A `|` that occurs the same number of times in every row is data."""
        assert detect_csv_delimiter("id,tags|x|y\n1,a|b|c\n2,d|e|f\n") == ","

    def test_the_row_the_sample_cuts_is_left_out(self) -> None:
        """Fewer than the sampled rows fit in the sample, so it ends inside a row."""
        cell = "x" * 4000
        text = "a;b;c\n" + "".join(f"{i};{cell};{cell}\n" for i in range(60))

        assert detect_csv_delimiter(text) == ";"

    def test_the_sample_can_end_inside_a_quoted_line_break(self) -> None:
        cell = '"' + ("y" * 70 + "\n") * 60 + '"'
        text = "a;b;c\n" + "".join(f"{i};{cell};end\n" for i in range(40))

        assert detect_csv_delimiter(text) == ";"
