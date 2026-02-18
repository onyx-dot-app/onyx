"""Tests for llm_step.py, specifically sanitization and argument parsing."""

from onyx.chat.llm_step import _parse_tool_args_to_dict
from onyx.chat.llm_step import _sanitize_llm_output
from onyx.chat.llm_step import _XmlToolCallContentFilter
from onyx.chat.llm_step import extract_tool_calls_from_response_text
from onyx.server.query_and_chat.placement import Placement


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


class TestExtractToolCallsFromResponseText:
    def _tool_defs(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "internal_search",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "queries": {
                                "type": "array",
                                "items": {"type": "string"},
                            }
                        },
                        "required": ["queries"],
                    },
                },
            }
        ]

    def _placement(self) -> Placement:
        return Placement(turn_index=0, tab_index=0, sub_turn_index=None)

    def test_collapses_nested_arguments_duplicate(self) -> None:
        response_text = '{"name":"internal_search","arguments":{"queries":["alpha"]}}'
        tool_calls = extract_tool_calls_from_response_text(
            response_text=response_text,
            tool_definitions=self._tool_defs(),
            placement=self._placement(),
        )
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == "internal_search"
        assert tool_calls[0].tool_args == {"queries": ["alpha"]}

    def test_keeps_non_duplicated_sequence(self) -> None:
        response_text = "\n".join(
            [
                '{"name":"internal_search","arguments":{"queries":["alpha"]}}',
                '{"name":"internal_search","arguments":{"queries":["beta"]}}',
            ]
        )
        tool_calls = extract_tool_calls_from_response_text(
            response_text=response_text,
            tool_definitions=self._tool_defs(),
            placement=self._placement(),
        )
        assert len(tool_calls) == 2
        assert [call.tool_args for call in tool_calls] == [
            {"queries": ["alpha"]},
            {"queries": ["beta"]},
        ]

    def test_keeps_intentional_duplicate_tool_calls(self) -> None:
        response_text = "\n".join(
            [
                '{"name":"internal_search","arguments":{"queries":["alpha"]}}',
                '{"name":"internal_search","arguments":{"queries":["alpha"]}}',
            ]
        )
        tool_calls = extract_tool_calls_from_response_text(
            response_text=response_text,
            tool_definitions=self._tool_defs(),
            placement=self._placement(),
        )
        assert len(tool_calls) == 2
        assert [call.tool_args for call in tool_calls] == [
            {"queries": ["alpha"]},
            {"queries": ["alpha"]},
        ]

    def test_extracts_xml_style_invoke_tool_call(self) -> None:
        response_text = """
<function_calls>
<invoke name="internal_search">
<parameter name="queries" string="false">["Onyx documentation", "Onyx docs", "Onyx platform"]</parameter>
</invoke>
</function_calls>
"""
        tool_calls = extract_tool_calls_from_response_text(
            response_text=response_text,
            tool_definitions=self._tool_defs(),
            placement=self._placement(),
        )
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == "internal_search"
        assert tool_calls[0].tool_args == {
            "queries": ["Onyx documentation", "Onyx docs", "Onyx platform"]
        }

    def test_ignores_unknown_tool_in_xml_style_invoke(self) -> None:
        response_text = """
<function_calls>
<invoke name="unknown_tool">
<parameter name="queries" string="false">["Onyx docs"]</parameter>
</invoke>
</function_calls>
"""
        tool_calls = extract_tool_calls_from_response_text(
            response_text=response_text,
            tool_definitions=self._tool_defs(),
            placement=self._placement(),
        )
        assert len(tool_calls) == 0


class TestXmlToolCallContentFilter:
    def test_strips_function_calls_block_single_chunk(self) -> None:
        f = _XmlToolCallContentFilter()
        output = f.process(
            "prefix "
            '<function_calls><invoke name="internal_search">'
            '<parameter name="queries" string="false">["Onyx docs"]</parameter>'
            "</invoke></function_calls> suffix"
        )
        output += f.flush()
        assert output == "prefix  suffix"

    def test_strips_function_calls_block_split_across_chunks(self) -> None:
        f = _XmlToolCallContentFilter()
        chunks = [
            "Start ",
            "<function_",
            'calls><invoke name="internal_search">',
            '<parameter name="queries" string="false">["Onyx docs"]',
            "</parameter></invoke></function_calls>",
            " End",
        ]
        output = "".join(f.process(chunk) for chunk in chunks) + f.flush()
        assert output == "Start  End"

    def test_preserves_non_tool_call_xml(self) -> None:
        f = _XmlToolCallContentFilter()
        output = f.process("A <tag>value</tag> B")
        output += f.flush()
        assert output == "A <tag>value</tag> B"

    def test_does_not_strip_similar_tag_names(self) -> None:
        f = _XmlToolCallContentFilter()
        output = f.process(
            "A <function_calls_v2><invoke>noop</invoke></function_calls_v2> B"
        )
        output += f.flush()
        assert (
            output == "A <function_calls_v2><invoke>noop</invoke></function_calls_v2> B"
        )
