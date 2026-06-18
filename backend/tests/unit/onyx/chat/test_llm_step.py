"""Tests for llm_step.py, specifically sanitization and argument parsing."""

from typing import Any

import pytest

from onyx.chat import llm_step as llm_step_module
from onyx.chat.llm_step import _extract_tool_call_kickoffs
from onyx.chat.llm_step import _increment_turns
from onyx.chat.llm_step import _parse_tool_args_to_dict
from onyx.chat.llm_step import _resolve_tool_arguments
from onyx.chat.llm_step import _XmlToolCallContentFilter
from onyx.chat.llm_step import extract_tool_calls_from_response_text
from onyx.chat.llm_step import translate_history_to_llm_format
from onyx.chat.models import ChatLoadedFile
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ToolCallSimple
from onyx.configs.constants import MessageType
from onyx.file_store.models import ChatFileType
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.models import AssistantMessage
from onyx.llm.models import TextContentPart
from onyx.llm.models import ToolMessage
from onyx.llm.models import UserMessage
from onyx.llm.well_known_providers.constants import AZURE_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import OPENAI_PROVIDER_NAME
from onyx.prompts.chat_prompts import IMAGE_DROP_REMINDER
from onyx.prompts.constants import SYSTEM_REMINDER_TAG_CLOSE
from onyx.prompts.constants import SYSTEM_REMINDER_TAG_OPEN
from onyx.server.query_and_chat.placement import Placement
from onyx.utils.postgres_sanitization import sanitize_string


class TestSanitizeLlmOutput:
    """Tests for the sanitize_string function."""

    def test_removes_null_bytes(self) -> None:
        """Test that NULL bytes are removed from strings."""
        assert sanitize_string("hello\x00world") == "helloworld"
        assert sanitize_string("\x00start") == "start"
        assert sanitize_string("end\x00") == "end"
        assert sanitize_string("\x00\x00\x00") == ""

    def test_removes_surrogates(self) -> None:
        """Test that UTF-16 surrogates are removed from strings."""
        # Low surrogate
        assert sanitize_string("hello\ud800world") == "helloworld"
        # High surrogate
        assert sanitize_string("hello\udfffworld") == "helloworld"
        # Middle of surrogate range
        assert sanitize_string("test\uda00value") == "testvalue"

    def test_removes_mixed_bad_characters(self) -> None:
        """Test removal of both NULL bytes and surrogates together."""
        assert sanitize_string("a\x00b\ud800c\udfffd") == "abcd"

    def test_preserves_valid_unicode(self) -> None:
        """Test that valid Unicode characters are preserved."""
        # Emojis
        assert sanitize_string("hello 👋 world") == "hello 👋 world"
        # Chinese characters
        assert sanitize_string("你好世界") == "你好世界"
        # Mixed scripts
        assert sanitize_string("Hello мир 世界") == "Hello мир 世界"

    def test_empty_string(self) -> None:
        """Test that empty strings are handled correctly."""
        assert sanitize_string("") == ""

    def test_normal_ascii(self) -> None:
        """Test that normal ASCII strings pass through unchanged."""
        assert sanitize_string("hello world") == "hello world"
        assert sanitize_string('{"key": "value"}') == '{"key": "value"}'


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

    def test_sanitizes_tool_call_name_for_bedrock(self) -> None:
        # Custom OpenAPI Action tools are stored with the user-supplied
        # Tool.name (e.g. "ServiceNow API"), which gets injected into the
        # assistant message's toolUse.name on follow-up turns. Bedrock rejects
        # names that don't match [a-zA-Z0-9_-]+, so we must sanitize.
        history = [
            ChatMessageSimple(
                message="",
                token_count=5,
                message_type=MessageType.ASSISTANT,
                tool_calls=[
                    ToolCallSimple(
                        tool_call_id="call-1",
                        tool_name="ServiceNow API",
                        tool_arguments={"q": "incident"},
                    ),
                ],
            ),
            ChatMessageSimple(
                message="tool result body",
                token_count=5,
                message_type=MessageType.TOOL_CALL_RESPONSE,
                tool_call_id="call-1",
            ),
        ]
        translated = translate_history_to_llm_format(
            history=history,
            llm_config=self._llm_config(LlmProviderNames.BEDROCK),
        )
        assert isinstance(translated, list)
        assert isinstance(translated[0], AssistantMessage)
        assert translated[0].tool_calls is not None
        assert translated[0].tool_calls[0].function.name == "ServiceNow_API"

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


# Minimal valid PNG header bytes so get_image_type_from_bytes returns image/png
# instead of raising — keeps the image-emission path running in tests.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _make_image(file_id: str) -> ChatLoadedFile:
    return ChatLoadedFile(
        file_id=file_id,
        content=_PNG_BYTES,
        file_type=ChatFileType.IMAGE,
        filename=f"{file_id}.png",
        content_text=None,
        token_count=50,
    )


def _make_user_msg(
    text: str, images: list[ChatLoadedFile] | None = None
) -> ChatMessageSimple:
    return ChatMessageSimple(
        message=text,
        token_count=5,
        message_type=MessageType.USER,
        image_files=images,
    )


def _make_llm_config(provider: str) -> LLMConfig:
    return LLMConfig(
        model_provider=provider,
        model_name="test-model",
        temperature=0,
        max_input_tokens=8192,
    )


_ATTACHED_IMAGE_PREFIX = "[attached image — file_id: "
_ATTACHED_IMAGE_SUFFIX = "]"


def _attached_image_file_ids(user_msg: UserMessage) -> list[str]:
    """Return file_ids in order, parsed from the per-image label text parts
    emitted by translate_history_to_llm_format. Lets tests assert
    `... == ["img0", "img1", ...]` instead of poking at substrings."""
    if not isinstance(user_msg.content, list):
        return []
    return [
        p.text[len(_ATTACHED_IMAGE_PREFIX) : -len(_ATTACHED_IMAGE_SUFFIX)]
        for p in user_msg.content
        if isinstance(p, TextContentPart) and p.text.startswith(_ATTACHED_IMAGE_PREFIX)
    ]


def _expected_image_drop_reminder(dropped_count: int) -> str:
    """Build the exact wrapped reminder string a test should compare against."""
    return (
        f"{SYSTEM_REMINDER_TAG_OPEN}\n"
        f"{IMAGE_DROP_REMINDER.format(dropped_count=dropped_count)}\n"
        f"{SYSTEM_REMINDER_TAG_CLOSE}"
    )


class TestImageCap:
    """End-to-end tests for the Azure-family image cap (translate_history_to_llm_format).

    Three invariants worth pinning down — anything more is double coverage of
    the same 30-line feature.
    """

    def test_disabled_by_default_passes_everything_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without ENABLE_AZURE_IMAGE_CAP, even an Azure request with many
        images flows untouched (no drops, no trailing reminder)."""
        monkeypatch.setattr(llm_step_module, "ENABLE_AZURE_IMAGE_CAP", False)
        history = [
            _make_user_msg("hi", images=[_make_image(f"img{i}") for i in range(100)])
        ]
        translated = translate_history_to_llm_format(
            history=history, llm_config=_make_llm_config(AZURE_PROVIDER_NAME)
        )
        assert isinstance(translated, list)
        assert len(translated) == 1
        assert isinstance(translated[0], UserMessage)
        assert len(_attached_image_file_ids(translated[0])) == 100

    def test_enabled_caps_azure_keeps_first_attachments_and_emits_reminder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Azure + cap enabled + over-limit → first-N attachments survive
        (user-attached preferred over later project-context fill), and a
        trailing system-reminder UserMessage is emitted with the centralized
        IMAGE_DROP_REMINDER prompt."""
        monkeypatch.setattr(llm_step_module, "ENABLE_AZURE_IMAGE_CAP", True)
        monkeypatch.setattr(llm_step_module, "_AZURE_DEFAULT_IMAGE_CAP", 3)
        history = [
            _make_user_msg(
                "describe", images=[_make_image(f"img{i}") for i in range(5)]
            )
        ]
        translated = translate_history_to_llm_format(
            history=history, llm_config=_make_llm_config(AZURE_PROVIDER_NAME)
        )
        assert isinstance(translated, list)
        assert len(translated) == 2
        user_msg, reminder = translated
        assert isinstance(user_msg, UserMessage)
        assert _attached_image_file_ids(user_msg) == ["img0", "img1", "img2"]
        assert isinstance(reminder, UserMessage)
        assert reminder.content == _expected_image_drop_reminder(dropped_count=2)

    def test_enabled_does_not_cap_non_azure_providers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The only way the Azure-prefix check could regress: a non-Azure
        provider getting capped. Pin this down."""
        monkeypatch.setattr(llm_step_module, "ENABLE_AZURE_IMAGE_CAP", True)
        monkeypatch.setattr(llm_step_module, "_AZURE_DEFAULT_IMAGE_CAP", 3)
        history = [
            _make_user_msg("hi", images=[_make_image(f"img{i}") for i in range(5)])
        ]
        translated = translate_history_to_llm_format(
            history=history, llm_config=_make_llm_config(OPENAI_PROVIDER_NAME)
        )
        assert isinstance(translated, list)
        assert len(translated) == 1
        assert isinstance(translated[0], UserMessage)
        assert len(_attached_image_file_ids(translated[0])) == 5


class TestEmptyAnswerRecovery:
    """Tests for the empty-answer recovery in run_llm_step_pkt_generator.

    When the model emits real text that is entirely consumed by content/citation
    processing (e.g. an answer dominated by bracketed-numeric text that matches
    the citation pattern but has no mapping), the raw model output is surfaced
    instead of returning an empty answer (which would otherwise raise
    EmptyLLMResponseError downstream).
    """

    @staticmethod
    def _make_llm() -> Any:
        from unittest.mock import MagicMock

        from onyx.llm.interfaces import LLMConfig

        llm = MagicMock()
        llm.config = LLMConfig(
            model_provider="litellm_proxy",
            model_name="claude-4.6-opus",
            temperature=0.0,
            max_input_tokens=100_000,
        )
        return llm

    @staticmethod
    def _content_stream(chunks: list[str]) -> Any:
        from onyx.llm.model_response import Delta
        from onyx.llm.model_response import ModelResponseStream
        from onyx.llm.model_response import StreamingChoice

        def _gen(*_args: Any, **_kwargs: Any) -> Any:
            for i, chunk in enumerate(chunks):
                yield ModelResponseStream(
                    id="chunk",
                    created="0",
                    choice=StreamingChoice(
                        finish_reason="stop" if i == len(chunks) - 1 else None,
                        delta=Delta(content=chunk),
                    ),
                )

        return _gen

    def _run(
        self,
        chunks: list[str],
        *,
        with_citation_processor: bool,
        tool_choice: ToolChoiceOptions = ToolChoiceOptions.AUTO,
        state_container: Any = None,
        pre_answer_processing_time: float | None = None,
        span_sink: list[Any] | None = None,
    ) -> tuple[Any, list[Any]]:
        from contextlib import nullcontext
        from unittest.mock import patch

        from onyx.chat import llm_step as _llm_step_module
        from onyx.chat.citation_processor import CitationMode
        from onyx.chat.citation_processor import DynamicCitationProcessor
        from onyx.chat.llm_step import run_llm_step_pkt_generator

        llm = self._make_llm()
        llm.stream = self._content_stream(chunks)

        citation_processor = (
            DynamicCitationProcessor(citation_mode=CitationMode.HYPERLINK)
            if with_citation_processor
            else None
        )

        # Capture the generation span so tests can assert what the trace recorded.
        real_generation_span = _llm_step_module.generation_span

        def _capturing_span(*args: Any, **kwargs: Any) -> Any:
            span = real_generation_span(*args, **kwargs)
            if span_sink is not None:
                span_sink.append(span)
            return span

        span_patch = (
            patch.object(_llm_step_module, "generation_span", _capturing_span)
            if span_sink is not None
            else nullcontext()
        )

        with span_patch:
            gen = run_llm_step_pkt_generator(
                history=[],
                tool_definitions=[],
                tool_choice=tool_choice,
                llm=llm,
                placement=Placement(turn_index=0),
                state_container=state_container,
                citation_processor=citation_processor,
                pre_answer_processing_time=pre_answer_processing_time,
            )

            packets: list[Any] = []
            result: Any = None
            while True:
                try:
                    packets.append(next(gen))
                except StopIteration as stop:
                    result = stop.value
                    break

        llm_step_result, _ = result
        return llm_step_result, packets

    def test_recovers_raw_when_citations_strip_entire_answer(self) -> None:
        """An answer that is entirely an unmapped bracketed number is stripped to
        empty by the citation processor; recovery surfaces the raw text."""
        from onyx.server.query_and_chat.streaming_models import AgentResponseDelta

        raw = "[1234567890123456789]"
        llm_step_result, packets = self._run([raw], with_citation_processor=True)

        # Without recovery this would be None -> EmptyLLMResponseError downstream.
        assert llm_step_result.answer == raw
        assert llm_step_result.raw_answer == raw
        assert llm_step_result.tool_calls is None

        # The recovered text is actually streamed to the client.
        emitted = "".join(
            p.obj.content for p in packets if isinstance(p.obj, AgentResponseDelta)
        )
        assert emitted == raw

    def test_recovers_raw_for_numeric_list_answer(self) -> None:
        raw = "[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]"
        llm_step_result, _ = self._run([raw], with_citation_processor=True)
        assert llm_step_result.answer == raw

    def test_no_recovery_for_normal_answer(self) -> None:
        """Normal prose is unaffected — answer is the processed text, not a
        duplicated raw fallback."""
        from onyx.server.query_and_chat.streaming_models import AgentResponseDelta

        chunks = ["The answer ", "is 42."]
        llm_step_result, packets = self._run(chunks, with_citation_processor=True)
        assert llm_step_result.answer == "The answer is 42."
        emitted = "".join(
            p.obj.content for p in packets if isinstance(p.obj, AgentResponseDelta)
        )
        # Streamed exactly once (no duplicate recovery emission).
        assert emitted == "The answer is 42."

    def test_no_recovery_when_no_content_emitted(self) -> None:
        """A genuinely empty stream stays empty (so EmptyLLMResponseError can
        still fire for real provider failures)."""
        llm_step_result, _ = self._run([""], with_citation_processor=True)
        assert llm_step_result.answer is None
        assert llm_step_result.raw_answer is None

    def test_no_recovery_in_required_tool_choice(self) -> None:
        """In REQUIRED mode pre-tool content is reasoning and an empty answer is
        expected; recovery must not fire (fallback tool extraction owns it)."""
        raw = "[1234567890123456789]"
        llm_step_result, _ = self._run(
            [raw],
            with_citation_processor=True,
            tool_choice=ToolChoiceOptions.REQUIRED,
        )
        assert llm_step_result.answer is None
        assert llm_step_result.raw_answer == raw

    def test_recovered_answer_is_recorded_in_tracing_span(self) -> None:
        """The generation span output must reflect the recovered answer, not the
        empty intermediate state (otherwise the recovered turn is invisible in
        traces)."""
        raw = "[1234567890123456789]"
        span_sink: list[Any] = []
        llm_step_result, _ = self._run(
            [raw], with_citation_processor=True, span_sink=span_sink
        )
        assert llm_step_result.answer == raw

        assert len(span_sink) == 1
        output = span_sink[0].span_data.output
        assert output is not None
        # output is [AssistantMessage.model_dump()]; the recovered text is recorded.
        assert any(raw in str(entry.get("content")) for entry in output)

    def test_normal_answer_recorded_in_tracing_span(self) -> None:
        """Sanity check that the moved span-output assignment still records normal
        answers."""
        span_sink: list[Any] = []
        llm_step_result, _ = self._run(
            ["Hello ", "world."], with_citation_processor=True, span_sink=span_sink
        )
        assert llm_step_result.answer == "Hello world."
        output = span_sink[0].span_data.output
        assert output is not None
        assert any("Hello world." in str(entry.get("content")) for entry in output)

    def test_recovery_sets_pre_answer_time_when_no_prior_answer_start(self) -> None:
        """When all content is swallowed before reaching _emit_content_chunk (e.g.
        an XML tool-call block the filter strips), recovery fires the
        AgentResponseStart branch and must persist pre-answer timing — mirroring
        the normal path — so the metric is not lost."""
        from unittest.mock import MagicMock

        # A complete <function_calls> block is stripped by the XML content filter,
        # so _emit_content_chunk never runs and answer_start stays False, while the
        # raw answer retains the text. No <invoke>, so it is NOT classified as a
        # tool-call payload (see tests below) and recovery still fires.
        raw = "<function_calls>noop</function_calls>"
        state_container = MagicMock()
        llm_step_result, _ = self._run(
            [raw],
            with_citation_processor=True,
            state_container=state_container,
            pre_answer_processing_time=1.5,
        )

        assert llm_step_result.answer == raw
        state_container.set_pre_answer_processing_time.assert_called_once_with(1.5)
        state_container.set_answer_tokens.assert_called_with(raw)

    def test_no_recovery_for_xml_tool_call_payload(self) -> None:
        """When the raw output is XML tool-call markup (emitted as plain text),
        recovery must NOT fire — run_llm_loop's fallback extraction parses it into
        a real tool call, and surfacing the raw markup would leak it to the client
        and pollute context."""
        from onyx.server.query_and_chat.streaming_models import AgentResponseDelta

        raw = (
            '<function_calls><invoke name="search">'
            '<parameter name="query">hi</parameter></invoke></function_calls>'
        )
        llm_step_result, packets = self._run([raw], with_citation_processor=True)

        # answer stays None so the loop's fallback tool extraction can handle it.
        assert llm_step_result.answer is None
        assert llm_step_result.raw_answer == raw
        # Nothing leaked to the client.
        emitted = "".join(
            p.obj.content for p in packets if isinstance(p.obj, AgentResponseDelta)
        )
        assert emitted == ""

    def test_no_recovery_for_zero_arg_xml_tool_call(self) -> None:
        """A zero-argument <invoke> (no <parameter>) is still valid tool-call
        markup. Recovery must NOT fire — otherwise the raw markup leaks and the
        fallback extractor can't parse the call."""
        from onyx.server.query_and_chat.streaming_models import AgentResponseDelta

        raw = '<function_calls><invoke name="get_time"></invoke></function_calls>'
        llm_step_result, packets = self._run([raw], with_citation_processor=True)

        assert llm_step_result.answer is None
        assert llm_step_result.raw_answer == raw
        emitted = "".join(
            p.obj.content for p in packets if isinstance(p.obj, AgentResponseDelta)
        )
        assert emitted == ""
