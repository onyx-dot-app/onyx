"""Tests for llm_step.py, specifically sanitization and argument parsing."""

from typing import Any

import pytest

from onyx.chat.llm_step import _extract_tool_call_kickoffs
from onyx.chat.llm_step import _increment_turns
from onyx.chat.llm_step import _parse_tool_args_to_dict
from onyx.chat.llm_step import _resolve_tool_arguments
from onyx.chat.llm_step import _sanitize_llm_output
from onyx.chat.llm_step import _XmlToolCallContentFilter
from onyx.chat.llm_step import extract_tool_calls_from_response_text
from onyx.chat.llm_step import translate_history_to_llm_format
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ToolCallSimple
from onyx.configs.constants import MessageType
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import AssistantMessage
from onyx.llm.models import ToolMessage
from onyx.llm.models import UserMessage
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


class TestExtractToolCallKickoffs:
    """Tests for the _extract_tool_call_kickoffs function."""

    def test_valid_tool_call(self) -> None:
        tool_call_map = {
            0: {
                "id": "call_123",
                "name": "internal_search",
                "arguments": '{"queries": ["test"]}',
            }
        }
        result = _extract_tool_call_kickoffs(tool_call_map, turn_index=0)
        assert len(result) == 1
        assert result[0].tool_name == "internal_search"
        assert result[0].tool_args == {"queries": ["test"]}

    def test_invalid_json_arguments_returns_empty_dict(self) -> None:
        """Verify that malformed JSON arguments produce an empty dict
        rather than raising an exception. This confirms the dead try/except
        around _parse_tool_args_to_dict was safe to remove."""
        tool_call_map = {
            0: {
                "id": "call_bad",
                "name": "internal_search",
                "arguments": "not valid json {{{",
            }
        }
        result = _extract_tool_call_kickoffs(tool_call_map, turn_index=0)
        assert len(result) == 1
        assert result[0].tool_args == {}

    def test_none_arguments_returns_empty_dict(self) -> None:
        tool_call_map = {
            0: {
                "id": "call_none",
                "name": "internal_search",
                "arguments": None,
            }
        }
        result = _extract_tool_call_kickoffs(tool_call_map, turn_index=0)
        assert len(result) == 1
        assert result[0].tool_args == {}

    def test_skips_entries_missing_id_or_name(self) -> None:
        tool_call_map: dict[int, dict[str, Any]] = {
            0: {"id": None, "name": "internal_search", "arguments": "{}"},
            1: {"id": "call_1", "name": None, "arguments": "{}"},
            2: {"id": "call_2", "name": "internal_search", "arguments": "{}"},
        }
        result = _extract_tool_call_kickoffs(tool_call_map, turn_index=0)
        assert len(result) == 1
        assert result[0].tool_call_id == "call_2"

    def test_tab_index_auto_increments(self) -> None:
        tool_call_map = {
            0: {"id": "c1", "name": "tool_a", "arguments": "{}"},
            1: {"id": "c2", "name": "tool_b", "arguments": "{}"},
        }
        result = _extract_tool_call_kickoffs(tool_call_map, turn_index=0)
        assert result[0].placement.tab_index == 0
        assert result[1].placement.tab_index == 1

    def test_tab_index_override(self) -> None:
        tool_call_map = {
            0: {"id": "c1", "name": "tool_a", "arguments": "{}"},
            1: {"id": "c2", "name": "tool_b", "arguments": "{}"},
        }
        result = _extract_tool_call_kickoffs(tool_call_map, turn_index=0, tab_index=5)
        assert result[0].placement.tab_index == 5
        assert result[1].placement.tab_index == 5


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


class TestIncrementTurns:
    """Tests for the _increment_turns helper used by _close_reasoning_if_active."""

    def test_increments_turn_index_when_no_sub_turn(self) -> None:
        turn, sub = _increment_turns(0, None)
        assert turn == 1
        assert sub is None

    def test_increments_sub_turn_when_present(self) -> None:
        turn, sub = _increment_turns(3, 0)
        assert turn == 3
        assert sub == 1

    def test_increments_sub_turn_from_nonzero(self) -> None:
        turn, sub = _increment_turns(5, 2)
        assert turn == 5
        assert sub == 3


class TestResolveToolArguments:
    """Tests for the _resolve_tool_arguments helper."""

    def test_dict_arguments(self) -> None:
        obj = {"arguments": {"queries": ["test"]}}
        assert _resolve_tool_arguments(obj) == {"queries": ["test"]}

    def test_dict_parameters(self) -> None:
        """Falls back to 'parameters' key when 'arguments' is missing."""
        obj = {"parameters": {"queries": ["test"]}}
        assert _resolve_tool_arguments(obj) == {"queries": ["test"]}

    def test_arguments_takes_precedence_over_parameters(self) -> None:
        obj = {"arguments": {"a": 1}, "parameters": {"b": 2}}
        assert _resolve_tool_arguments(obj) == {"a": 1}

    def test_json_string_arguments(self) -> None:
        obj = {"arguments": '{"queries": ["test"]}'}
        assert _resolve_tool_arguments(obj) == {"queries": ["test"]}

    def test_invalid_json_string_returns_empty_dict(self) -> None:
        obj = {"arguments": "not valid json"}
        assert _resolve_tool_arguments(obj) == {}

    def test_no_arguments_or_parameters_returns_empty_dict(self) -> None:
        obj = {"name": "some_tool"}
        assert _resolve_tool_arguments(obj) == {}

    def test_non_dict_non_string_arguments_returns_none(self) -> None:
        """When arguments resolves to a list or int, returns None."""
        assert _resolve_tool_arguments({"arguments": [1, 2, 3]}) is None
        assert _resolve_tool_arguments({"arguments": 42}) is None


class TestTranslateHistoryToLlmFormat:
    @staticmethod
    def _llm_config(provider: str) -> LLMConfig:
        return LLMConfig(
            model_provider=provider,
            model_name="test-model",
            temperature=0,
            max_input_tokens=8192,
        )

    @staticmethod
    def _tool_history() -> list[ChatMessageSimple]:
        return [
            ChatMessageSimple(
                message="",
                token_count=5,
                message_type=MessageType.ASSISTANT,
                tool_calls=[
                    ToolCallSimple(
                        tool_call_id="51381e0b0",
                        tool_name="internal_search",
                        tool_arguments={"queries": ["alpha"]},
                    )
                ],
            ),
            ChatMessageSimple(
                message="tool result body",
                token_count=5,
                message_type=MessageType.TOOL_CALL_RESPONSE,
                tool_call_id="51381e0b0",
            ),
        ]

    def test_preserves_structured_tool_history_for_non_ollama(self) -> None:
        translated = translate_history_to_llm_format(
            history=self._tool_history(),
            llm_config=self._llm_config(LlmProviderNames.OPENAI),
        )
        assert isinstance(translated, list)

        assert isinstance(translated[0], AssistantMessage)
        assert translated[0].tool_calls is not None
        assert translated[0].tool_calls[0].id == "51381e0b0"
        assert isinstance(translated[1], ToolMessage)
        assert translated[1].tool_call_id == "51381e0b0"

    def test_flattens_tool_history_for_ollama(self) -> None:
        translated = translate_history_to_llm_format(
            history=self._tool_history(),
            llm_config=self._llm_config(LlmProviderNames.OLLAMA_CHAT),
        )
        assert isinstance(translated, list)

        assert isinstance(translated[0], AssistantMessage)
        assert translated[0].tool_calls is None
        assert translated[0].content is not None
        assert "51381e0b0" in translated[0].content

        assert isinstance(translated[1], UserMessage)
        assert "51381e0b0" in translated[1].content
        assert "tool result body" in translated[1].content

    def test_flattens_multiple_assistant_tool_calls_for_ollama(self) -> None:
        history = [
            ChatMessageSimple(
                message="I will use tools now.",
                token_count=5,
                message_type=MessageType.ASSISTANT,
                tool_calls=[
                    ToolCallSimple(
                        tool_call_id="call-a",
                        tool_name="internal_search",
                        tool_arguments={"queries": ["alpha"]},
                    ),
                    ToolCallSimple(
                        tool_call_id="call-b",
                        tool_name="internal_search",
                        tool_arguments={"queries": ["beta"]},
                    ),
                ],
            )
        ]
        translated = translate_history_to_llm_format(
            history=history,
            llm_config=self._llm_config(LlmProviderNames.OLLAMA_CHAT),
        )

        assert isinstance(translated, list)
        assert isinstance(translated[0], AssistantMessage)
        assert translated[0].tool_calls is None
        assert translated[0].content == (
            "I will use tools now.\n"
            '[Tool Call] name=internal_search id=call-a args={"queries": ["alpha"]}\n'
            '[Tool Call] name=internal_search id=call-b args={"queries": ["beta"]}'
        )

    @pytest.mark.parametrize(
        "provider",
        [
            LlmProviderNames.OPENAI,
            LlmProviderNames.OLLAMA_CHAT,
        ],
    )
    def test_tool_call_response_requires_tool_call_id(self, provider: str) -> None:
        with pytest.raises(ValueError, match="tool_call_id is not available"):
            translate_history_to_llm_format(
                history=[
                    ChatMessageSimple(
                        message="tool result body",
                        token_count=5,
                        message_type=MessageType.TOOL_CALL_RESPONSE,
                        tool_call_id=None,
                    )
                ],
                llm_config=self._llm_config(provider),
            )
