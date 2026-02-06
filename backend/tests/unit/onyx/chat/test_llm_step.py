"""Tests for llm_step.py, specifically sanitization and argument parsing."""

from onyx.chat.llm_step import _parse_tool_args_to_dict
from onyx.chat.llm_step import _sanitize_llm_output


class TestSanitizeLlmOutput:
    """Tests for the _sanitize_llm_output function."""

    def test_removes_null_bytes(self) -> None:
        """Test that NULL bytes are removed from strings."""
        assert _sanitize_llm_output("hello\x00world") == "helloworld"
        assert _sanitize_llm_output("\x00start") == "start"
        assert _sanitize_llm_output("end\x00") == "end"
        assert _sanitize_llm_output("\x00\x00\x00") == ""

    def test_removes_surrogates(self) -> None:
        """Test that UTF-16 surrogates are removed from strings."""
        # Low surrogate
        assert _sanitize_llm_output("hello\ud800world") == "helloworld"
        # High surrogate
        assert _sanitize_llm_output("hello\udfffworld") == "helloworld"
        # Middle of surrogate range
        assert _sanitize_llm_output("test\uda00value") == "testvalue"

    def test_removes_mixed_bad_characters(self) -> None:
        """Test removal of both NULL bytes and surrogates together."""
        assert _sanitize_llm_output("a\x00b\ud800c\udfffd") == "abcd"

    def test_preserves_valid_unicode(self) -> None:
        """Test that valid Unicode characters are preserved."""
        # Emojis
        assert _sanitize_llm_output("hello 👋 world") == "hello 👋 world"
        # Chinese characters
        assert _sanitize_llm_output("你好世界") == "你好世界"
        # Mixed scripts
        assert _sanitize_llm_output("Hello мир 世界") == "Hello мир 世界"

    def test_empty_string(self) -> None:
        """Test that empty strings are handled correctly."""
        assert _sanitize_llm_output("") == ""

    def test_normal_ascii(self) -> None:
        """Test that normal ASCII strings pass through unchanged."""
        assert _sanitize_llm_output("hello world") == "hello world"
        assert _sanitize_llm_output('{"key": "value"}') == '{"key": "value"}'


class TestParseToolArgsToDict:
    """Tests for the _parse_tool_args_to_dict function."""

    def test_none_input(self) -> None:
        """Test that None returns empty dict."""
        assert _parse_tool_args_to_dict(None) == {}

    def test_dict_input(self) -> None:
        """Test that dict input is returned with parsed JSON string values."""
        result = _parse_tool_args_to_dict({"key": "value", "num": 42})
        assert result == {"key": "value", "num": 42}

    def test_dict_with_json_string_values(self) -> None:
        """Test that JSON string values in dict are parsed."""
        result = _parse_tool_args_to_dict({"queries": '["q1", "q2"]'})
        assert result == {"queries": ["q1", "q2"]}

    def test_json_string_input(self) -> None:
        """Test that JSON string is parsed to dict."""
        result = _parse_tool_args_to_dict('{"key": "value"}')
        assert result == {"key": "value"}

    def test_double_encoded_json(self) -> None:
        """Test that double-encoded JSON string is parsed correctly."""
        # This is: '"{\\"key\\": \\"value\\"}"'
        double_encoded = '"\\"{\\\\\\"key\\\\\\": \\\\\\"value\\\\\\"}\\"'
        # Actually let's use a simpler approach
        import json

        inner = {"key": "value"}
        single_encoded = json.dumps(inner)  # '{"key": "value"}'
        double_encoded = json.dumps(single_encoded)  # '"{\\"key\\": \\"value\\"}"'
        result = _parse_tool_args_to_dict(double_encoded)
        assert result == {"key": "value"}

    def test_invalid_json_returns_empty_dict(self) -> None:
        """Test that invalid JSON returns empty dict."""
        assert _parse_tool_args_to_dict("not json") == {}
        assert _parse_tool_args_to_dict("{invalid}") == {}

    def test_non_dict_json_returns_empty_dict(self) -> None:
        """Test that non-dict JSON (like arrays) returns empty dict."""
        assert _parse_tool_args_to_dict("[1, 2, 3]") == {}
        assert _parse_tool_args_to_dict('"just a string"') == {}

    def test_non_string_non_dict_returns_empty_dict(self) -> None:
        """Test that non-string, non-dict types return empty dict."""
        assert _parse_tool_args_to_dict(123) == {}
        assert _parse_tool_args_to_dict(["list"]) == {}

    # Sanitization tests

    def test_dict_input_sanitizes_null_bytes(self) -> None:
        """Test that NULL bytes in dict values are sanitized."""
        result = _parse_tool_args_to_dict({"query": "hello\x00world"})
        assert result == {"query": "helloworld"}

    def test_dict_input_sanitizes_surrogates(self) -> None:
        """Test that surrogates in dict values are sanitized."""
        result = _parse_tool_args_to_dict({"query": "hello\ud800world"})
        assert result == {"query": "helloworld"}

    def test_json_string_sanitizes_null_bytes(self) -> None:
        """Test that NULL bytes in JSON string are sanitized before parsing."""
        # JSON with NULL byte in value
        json_str = '{"query": "hello\x00world"}'
        result = _parse_tool_args_to_dict(json_str)
        assert result == {"query": "helloworld"}

    def test_json_string_sanitizes_surrogates(self) -> None:
        """Test that surrogates in JSON string are sanitized before parsing."""
        json_str = '{"query": "hello\ud800world"}'
        result = _parse_tool_args_to_dict(json_str)
        assert result == {"query": "helloworld"}

    def test_nested_dict_values_sanitized(self) -> None:
        """Test that nested JSON string values are also sanitized."""
        # Dict with a JSON string value that contains bad characters
        result = _parse_tool_args_to_dict({"queries": '["q1\x00", "q2\ud800"]'})
        assert result == {"queries": ["q1", "q2"]}

    def test_preserves_valid_unicode_in_dict(self) -> None:
        """Test that valid Unicode is preserved in dict values."""
        result = _parse_tool_args_to_dict({"query": "hello 👋 世界"})
        assert result == {"query": "hello 👋 世界"}

    def test_preserves_valid_unicode_in_json(self) -> None:
        """Test that valid Unicode is preserved in JSON string."""
        json_str = '{"query": "hello 👋 世界"}'
        result = _parse_tool_args_to_dict(json_str)
        assert result == {"query": "hello 👋 世界"}
