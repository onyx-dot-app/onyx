from onyx.utils.text_processing import normalize_curly_quotes
from onyx.utils.text_processing import ZERO_WIDTH_CHARS
from onyx.utils.text_processing import is_zero_width_char
from onyx.utils.text_processing import decode_escapes
from onyx.utils.text_processing import make_url_compatible
from onyx.utils.text_processing import has_unescaped_quote
from onyx.utils.text_processing import has_unescaped_quote

class TestNormalizeCurlyQuotes:
    """Tests for the normalize_curly_quotes function."""
    
    def test_normalize_curly_quotes(self) -> None:
        input_text = "“quote” with curly ‘single’ and “double” quotes."
        expected_output = "\"quote\" with curly 'single' and \"double\" quotes."
        assert normalize_curly_quotes(input_text) == expected_output
    
class TestIsZeroWidthChar:
    """Tests for the is_zero_width_char function."""

    def test_returns_true_for_all_zero_width_characters(self) -> None:
        for char in {"\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"}:
            assert is_zero_width_char(char) is True

    def test_returns_false_for_normal_characters(self) -> None:
        assert is_zero_width_char("a") is False

class TestDecodeEscapes:
    """Test for the decode_escapes function."""

    def test_decode_escapes(self) -> None:
        input_text = "Line1\\nLine2\\tTabbed\\u2019s"
        expected_output = "Line1\nLine2\tTabbed’s"
        assert decode_escapes(input_text) == expected_output
        
class TestMakeUrlCompatible:
    """Test for the make_url_compatible function."""

    def test_make_url_compatible(self) -> None:
        assert make_url_compatible("A B/C") == "A_B%2FC"
        
class TestHasUnescapedQuote:
    """Test for the has_unescaped_quote function."""

    def test_returns_true_for_unescaped_quote(self) -> None:
        assert has_unescaped_quote('"hello"') is True

    def test_returns_false_for_escaped_quote(self) -> None:
        assert has_unescaped_quote(r'\"hello\"') is False