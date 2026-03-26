from onyx.utils.text_processing import decode_escapes
from onyx.utils.text_processing import has_unescaped_quote
from onyx.utils.text_processing import is_zero_width_char
from onyx.utils.text_processing import make_url_compatible
from onyx.utils.text_processing import normalize_curly_quotes


class TestNormalizeCurlyQuotes:
    """Tests for the normalize_curly_quotes function."""

    def test_returns_plain_string_unchanged(self) -> None:
        input_text = "plain text"
        assert normalize_curly_quotes(input_text) == input_text

    def test_normalizes_left_single_quote(self) -> None:
        assert normalize_curly_quotes("‘text") == "'text"

    def test_normalizes_right_single_quote(self) -> None:
        assert normalize_curly_quotes("text’") == "text'"

    def test_normalizes_left_double_quote(self) -> None:
        assert normalize_curly_quotes("“text") == '"text'

    def test_normalizes_right_double_quote(self) -> None:
        assert normalize_curly_quotes("text”") == 'text"'


class TestIsZeroWidthChar:
    """Tests for the is_zero_width_char function."""

    def test_returns_true_for_known_zero_width_character(self) -> None:
        assert is_zero_width_char("\u200b") is True

    def test_returns_false_for_normal_characters(self) -> None:
        assert is_zero_width_char("a") is False

class TestDecodeEscapes:
    """Test for the decode_escapes function."""

    def test_decode_escapes(self) -> None:
        input_text = "Line1\\nLine2\\tTabbed\\u2019s"
        expected_output = "Line1\nLine2\tTabbed\u2019s"
        assert decode_escapes(input_text) == expected_output


class TestMakeUrlCompatible:
    """Test for the make_url_compatible function."""

    def test_returns_empty_string_unchanged(self) -> None:
        assert make_url_compatible("") == ""

    def test_returns_already_compatible_string_unchanged(self) -> None:
        assert make_url_compatible("already_compatible") == "already_compatible"

    def test_converts_spaces_to_underscores(self) -> None:
        assert make_url_compatible("A B") == "A_B"

    def test_encodes_reserved_characters(self) -> None:
        assert make_url_compatible("A B/C") == "A_B%2FC"


class TestHasUnescapedQuote:
    """Test for the has_unescaped_quote function."""

    def test_returns_true_for_unescaped_quote(self) -> None:
        assert has_unescaped_quote('"hello"') is True

    def test_returns_false_for_escaped_quote(self) -> None:
        assert has_unescaped_quote(r'\"hello\"') is False
