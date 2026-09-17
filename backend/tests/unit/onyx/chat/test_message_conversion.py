"""Tests for message conversion and shared compatibility parsing."""

import pytest

import onyx.context.messages as conversion_module
from onyx.context.messages import PromptMetadata, prepare_model_messages
from onyx.file_store.models import ChatFileType, ChatLoadedFile
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LLMConfig
from onyx.llm.litellm_conversion import serialize_request
from onyx.llm.litellm_models import AssistantMessage, ToolMessage
from onyx.llm.litellm_models import UserMessage as WireUserMessage
from onyx.llm.models import AssistantMessage as CanonicalAssistantMessage
from onyx.llm.models import (
    GenerationRequest,
    ImageContentPart,
    ImageUrlDetail,
    Message,
    TextContent,
    TextContentPart,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.models import ToolCall as AgentToolCall
from onyx.llm.models import UserMessage as CanonicalUserMessage
from onyx.llm.tool_parsing import (
    _resolve_tool_arguments,
    extract_tool_calls_from_response_text,
)
from onyx.llm.well_known_providers.constants import (
    AZURE_PROVIDER_NAME,
    OPENAI_PROVIDER_NAME,
)
from onyx.prompts.chat_prompts import IMAGE_DROP_REMINDER
from onyx.prompts.constants import SYSTEM_REMINDER_TAG_CLOSE, SYSTEM_REMINDER_TAG_OPEN
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

    def test_collapses_nested_arguments_duplicate(self) -> None:
        response_text = '{"name":"internal_search","arguments":{"queries":["alpha"]}}'
        tool_calls = extract_tool_calls_from_response_text(
            response_text=response_text,
            tool_definitions=self._tool_defs(),
        )
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "internal_search"
        assert tool_calls[0].arguments == {"queries": ["alpha"]}

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
        )
        assert len(tool_calls) == 2
        assert [call.arguments for call in tool_calls] == [
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
        )
        assert len(tool_calls) == 2
        assert [call.arguments for call in tool_calls] == [
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
        )
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "internal_search"
        assert tool_calls[0].arguments == {
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
        )
        assert len(tool_calls) == 0


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
    def _tool_history() -> list[Message]:
        return [
            CanonicalAssistantMessage(
                content=[
                    TextContent(text=""),
                    *(
                        [
                            AgentToolCall(
                                id="51381e0b0",
                                name="internal_search",
                                arguments={"queries": ["alpha"]},
                            )
                        ]
                        or []
                    ),
                ],
                metadata=PromptMetadata(token_count=5),
            ),
            ToolResultMessage(
                content="tool result body",
                tool_call_id="51381e0b0",
                tool_name="",
                metadata=PromptMetadata(token_count=5),
            ),
        ]

    def test_preserves_structured_tool_history_for_non_ollama(self) -> None:
        translated = serialize_request(
            GenerationRequest(messages=self._tool_history()),
            self._llm_config(LlmProviderNames.OPENAI),
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
            CanonicalAssistantMessage(
                content=[
                    TextContent(text=""),
                    *(
                        [
                            AgentToolCall(
                                id="call-1",
                                name="ServiceNow API",
                                arguments={"q": "incident"},
                            )
                        ]
                        or []
                    ),
                ],
                metadata=PromptMetadata(token_count=5),
            ),
            ToolResultMessage(
                content="tool result body",
                tool_call_id="call-1",
                tool_name="",
                metadata=PromptMetadata(token_count=5),
            ),
        ]
        translated = serialize_request(
            GenerationRequest(messages=history),
            self._llm_config(LlmProviderNames.BEDROCK),
        )
        assert isinstance(translated, list)
        assert isinstance(translated[0], AssistantMessage)
        assert translated[0].tool_calls is not None
        assert translated[0].tool_calls[0].function.name == "ServiceNow_API"

    def test_flattens_tool_history_for_ollama(self) -> None:
        translated = serialize_request(
            GenerationRequest(messages=self._tool_history()),
            self._llm_config(LlmProviderNames.OLLAMA_CHAT),
        )
        assert isinstance(translated, list)

        assert isinstance(translated[0], AssistantMessage)
        assert translated[0].tool_calls is None
        assert translated[0].content is not None
        assert "51381e0b0" in translated[0].content

        assert isinstance(translated[1], WireUserMessage)
        assert "51381e0b0" in translated[1].content
        assert "tool result body" in translated[1].content

    def test_flattens_multiple_assistant_tool_calls_for_ollama(self) -> None:
        history = [
            CanonicalAssistantMessage(
                content=[
                    TextContent(text="I will use tools now."),
                    *(
                        [
                            AgentToolCall(
                                id="call-a",
                                name="internal_search",
                                arguments={"queries": ["alpha"]},
                            ),
                            AgentToolCall(
                                id="call-b",
                                name="internal_search",
                                arguments={"queries": ["beta"]},
                            ),
                        ]
                        or []
                    ),
                ],
                metadata=PromptMetadata(token_count=5),
            )
        ]
        translated = serialize_request(
            GenerationRequest(messages=history),
            self._llm_config(LlmProviderNames.OLLAMA_CHAT),
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
        with pytest.raises(ValueError, match="tool_call_id"):
            serialize_request(
                GenerationRequest(
                    messages=[
                        ToolResultMessage(
                            content="tool result body",
                            tool_call_id="",
                            tool_name="",
                            metadata=PromptMetadata(token_count=5),
                        )
                    ]
                ),
                self._llm_config(provider),
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


@pytest.mark.parametrize("cap", [1, 2])
def test_native_and_attached_images_share_limit_without_loading_dropped_files(
    cap: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        conversion_module, "model_supports_image_input", lambda *_: True
    )
    monkeypatch.setattr(conversion_module, "resolve_image_cap", lambda _: cap)
    loaded: list[str] = []

    def image(file_id: str) -> ChatLoadedFile:
        def load() -> bytes:
            loaded.append(file_id)
            return _PNG_BYTES

        return ChatLoadedFile.lazy_loaded(
            file_id=file_id,
            file_type=ChatFileType.IMAGE,
            filename=f"{file_id}.png",
            content_text=None,
            token_count=50,
            loader=load,
        )

    native = ImageContentPart(
        image_url=ImageUrlDetail(url="https://example.com/new.png")
    )
    message = CanonicalUserMessage(
        content=[TextContentPart(text="before"), native, TextContentPart(text="after")],
        metadata=PromptMetadata(image_files=[image("new")]),
    )
    translated = prepare_model_messages(
        [_make_user_msg("older", images=[image("old")]), message],
        _make_llm_config(AZURE_PROVIDER_NAME),
    )
    recent = translated[1]
    assert isinstance(recent, UserMessage)
    assert isinstance(recent.content, list)
    assert recent.content[:3] == message.content
    assert sum(isinstance(part, ImageContentPart) for part in recent.content) == cap
    assert loaded == (["new"] if cap == 2 else [])
    assert translated[-1].content == _expected_image_drop_reminder(3 - cap)


@pytest.mark.parametrize("include_attachment", [False, True])
def test_native_images_use_nonvision_markers_without_loading_attachments(
    include_attachment: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        conversion_module, "model_supports_image_input", lambda *_: False
    )

    def load() -> bytes:
        raise AssertionError("nonvision formatting must not load image bytes")

    attached = ChatLoadedFile.lazy_loaded(
        file_id="attached",
        file_type=ChatFileType.IMAGE,
        filename="attached.png",
        content_text=None,
        token_count=50,
        loader=load,
    )
    message = CanonicalUserMessage(
        content=[
            TextContentPart(text="before"),
            ImageContentPart(
                image_url=ImageUrlDetail(url="https://example.com/image.png")
            ),
            TextContentPart(text="after"),
        ],
        metadata=PromptMetadata(image_files=[attached] if include_attachment else []),
    )
    (translated,) = prepare_model_messages(
        [message], _make_llm_config(OPENAI_PROVIDER_NAME)
    )
    assert isinstance(translated, UserMessage)
    assert isinstance(translated.content, list)
    assert all(isinstance(part, TextContentPart) for part in translated.content)
    text = [
        part.text for part in translated.content if isinstance(part, TextContentPart)
    ]
    assert text[0] == "before"
    assert "does not support image input" in text[1]
    assert text[2] == "after"
    if include_attachment:
        assert "attached" in text[3]
    else:
        assert len(text) == 3


def _make_user_msg(text: str, images: list[ChatLoadedFile] | None = None) -> Message:
    return CanonicalUserMessage(
        content=text, metadata=PromptMetadata(token_count=5, image_files=images)
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
    emitted by prepare_model_messages. Lets tests assert
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
    """End-to-end tests for the Azure-family image cap (prepare_model_messages).

    Three invariants worth pinning down — anything more is double coverage of
    the same 30-line feature.
    """

    @pytest.fixture(autouse=True)
    def _vision_capable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # These tests exercise the cap, not the vision gate — pin it open.
        monkeypatch.setattr(
            conversion_module, "model_supports_image_input", lambda *_: True
        )

    def test_disabled_by_default_passes_everything_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without ENABLE_AZURE_IMAGE_CAP, even an Azure request with many
        images flows untouched (no drops, no trailing reminder)."""
        monkeypatch.setattr(conversion_module, "ENABLE_AZURE_IMAGE_CAP", False)
        history = [
            _make_user_msg("hi", images=[_make_image(f"img{i}") for i in range(100)])
        ]
        translated = prepare_model_messages(
            history=history, llm_info=_make_llm_config(AZURE_PROVIDER_NAME)
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
        monkeypatch.setattr(conversion_module, "ENABLE_AZURE_IMAGE_CAP", True)
        monkeypatch.setattr(conversion_module, "_AZURE_DEFAULT_IMAGE_CAP", 3)
        history = [
            _make_user_msg(
                "describe", images=[_make_image(f"img{i}") for i in range(5)]
            )
        ]
        translated = prepare_model_messages(
            history=history, llm_info=_make_llm_config(AZURE_PROVIDER_NAME)
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
        monkeypatch.setattr(conversion_module, "ENABLE_AZURE_IMAGE_CAP", True)
        monkeypatch.setattr(conversion_module, "_AZURE_DEFAULT_IMAGE_CAP", 3)
        history = [
            _make_user_msg("hi", images=[_make_image(f"img{i}") for i in range(5)])
        ]
        translated = prepare_model_messages(
            history=history, llm_info=_make_llm_config(OPENAI_PROVIDER_NAME)
        )
        assert isinstance(translated, list)
        assert len(translated) == 1
        assert isinstance(translated[0], UserMessage)
        assert len(_attached_image_file_ids(translated[0])) == 5


class TestNonVisionImageStripping:
    """History can contain images the currently selected model cannot accept
    (e.g. after a mid-session model switch). prepare_model_messages
    must replace them with text markers instead of causing a provider 400."""

    def test_strips_image_parts_for_non_vision_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            conversion_module, "model_supports_image_input", lambda *_: False
        )
        history = [_make_user_msg("look at this", images=[_make_image("img0")])]
        translated = prepare_model_messages(
            history=history, llm_info=_make_llm_config(OPENAI_PROVIDER_NAME)
        )
        assert isinstance(translated, list)
        (user_msg,) = translated
        assert isinstance(user_msg, UserMessage)
        assert isinstance(user_msg.content, list)
        assert not any(isinstance(p, ImageContentPart) for p in user_msg.content)
        markers = [
            p.text
            for p in user_msg.content
            if isinstance(p, TextContentPart) and "img0" in p.text
        ]
        assert markers
        assert "does not support image input" in markers[0]

    def test_keeps_image_parts_for_vision_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            conversion_module, "model_supports_image_input", lambda *_: True
        )
        history = [_make_user_msg("look at this", images=[_make_image("img0")])]
        translated = prepare_model_messages(
            history=history, llm_info=_make_llm_config(OPENAI_PROVIDER_NAME)
        )
        (user_msg,) = translated
        assert isinstance(user_msg, UserMessage)
        assert isinstance(user_msg.content, list)
        assert _attached_image_file_ids(user_msg) == ["img0"]
        assert any(isinstance(p, ImageContentPart) for p in user_msg.content)

    def test_capability_not_checked_without_images(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_: object) -> bool:
            raise AssertionError("capability check should not run for text-only")

        monkeypatch.setattr(conversion_module, "model_supports_image_input", _boom)
        history = [_make_user_msg("just text")]
        translated = prepare_model_messages(
            history=history, llm_info=_make_llm_config(OPENAI_PROVIDER_NAME)
        )
        assert isinstance(translated, list)
        assert len(translated) == 1


@pytest.mark.parametrize("supports_images", [False, True])
def test_resolved_image_capability_avoids_lookup(
    supports_images: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    def lookup(*_: object) -> bool:
        raise AssertionError("resolved model metadata must not query capabilities")

    monkeypatch.setattr(conversion_module, "model_supports_image_input", lookup)
    model = _make_llm_config(OPENAI_PROVIDER_NAME).model_copy(
        update={"supports_images": supports_images}
    )
    message = CanonicalUserMessage(
        content=[
            ImageContentPart(
                image_url=ImageUrlDetail(url="https://example.com/image.png")
            )
        ]
    )
    (prepared,) = prepare_model_messages([message], model)
    assert isinstance(prepared, UserMessage) and isinstance(prepared.content, list)
    assert (
        any(isinstance(part, ImageContentPart) for part in prepared.content)
        is supports_images
    )


def test_unknown_image_capability_uses_existing_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked_up: list[tuple[str, str, str | None]] = []

    def lookup(name: str, provider: str, deployment: str | None) -> bool:
        looked_up.append((name, provider, deployment))
        return True

    monkeypatch.setattr(conversion_module, "model_supports_image_input", lookup)
    model = _make_llm_config(OPENAI_PROVIDER_NAME)
    assert model.supports_images is None
    message = CanonicalUserMessage(
        content=[
            ImageContentPart(
                image_url=ImageUrlDetail(url="https://example.com/image.png")
            )
        ]
    )
    (prepared,) = prepare_model_messages([message], model)
    assert isinstance(prepared, UserMessage) and isinstance(prepared.content, list)
    assert any(isinstance(part, ImageContentPart) for part in prepared.content)
    assert looked_up == [
        (model.model_name, model.model_provider, model.deployment_name)
    ]
