"""Native history retains tool identities, image limits, and text fallbacks."""

import pytest
from pydantic_ai import messages as pm

from onyx.chat import history_translation as llm_step_module
from onyx.chat.history_translation import (
    translate_history_to_native_messages,
)
from onyx.chat.models import ChatLoadedFile, ChatMessageSimple, ToolCallSimple
from onyx.configs.constants import MessageType
from onyx.file_store.models import ChatFileType
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LLMConfig
from onyx.llm.well_known_providers.constants import (
    AZURE_PROVIDER_NAME,
    OPENAI_PROVIDER_NAME,
)
from onyx.prompts.chat_prompts import IMAGE_DROP_REMINDER
from onyx.prompts.constants import SYSTEM_REMINDER_TAG_CLOSE, SYSTEM_REMINDER_TAG_OPEN


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
        translated = translate_history_to_native_messages(
            history=self._tool_history(),
            llm_config=self._llm_config(LlmProviderNames.OPENAI),
        )
        assert isinstance(translated, list)

        assert isinstance(translated[0], pm.ModelResponse)
        call = translated[0].parts[0]
        assert isinstance(call, pm.ToolCallPart)
        assert call.tool_call_id == "51381e0b0"
        assert call.args_as_dict() == {"queries": ["alpha"]}
        assert isinstance(translated[1], pm.ModelRequest)
        result = translated[1].parts[0]
        assert isinstance(result, pm.ToolReturnPart)
        assert result.tool_call_id == call.tool_call_id
        assert result.tool_name == call.tool_name
        assert result.content == "tool result body"

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
        translated = translate_history_to_native_messages(
            history=history,
            llm_config=self._llm_config(LlmProviderNames.BEDROCK),
        )
        assert isinstance(translated, list)
        assert isinstance(translated[0], pm.ModelResponse)
        call = translated[0].parts[0]
        assert isinstance(call, pm.ToolCallPart)
        assert call.tool_name == "ServiceNow_API"

    @pytest.mark.parametrize(
        "provider",
        [
            LlmProviderNames.OPENAI,
            LlmProviderNames.OLLAMA_CHAT,
        ],
    )
    def test_tool_call_response_requires_tool_call_id(self, provider: str) -> None:
        with pytest.raises(ValueError, match="tool_call_id is not available"):
            translate_history_to_native_messages(
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


def _user_content(message: pm.ModelMessage) -> str | list[pm.UserContent]:
    assert isinstance(message, pm.ModelRequest)
    part = message.parts[0]
    assert isinstance(part, pm.UserPromptPart)
    return part.content if isinstance(part.content, str) else list(part.content)


def _attached_image_file_ids(message: pm.ModelMessage) -> list[str]:
    content = _user_content(message)
    if isinstance(content, str):
        return []
    return [
        part[len(_ATTACHED_IMAGE_PREFIX) : -len(_ATTACHED_IMAGE_SUFFIX)]
        for part in content
        if isinstance(part, str) and part.startswith(_ATTACHED_IMAGE_PREFIX)
    ]


def _expected_image_drop_reminder(dropped_count: int) -> str:
    """Build the exact wrapped reminder string a test should compare against."""
    return (
        f"{SYSTEM_REMINDER_TAG_OPEN}\n"
        f"{IMAGE_DROP_REMINDER.format(dropped_count=dropped_count)}\n"
        f"{SYSTEM_REMINDER_TAG_CLOSE}"
    )


class TestImageCap:
    """End-to-end tests for the Azure-family image cap (translate_history_to_native_messages).

    Three invariants worth pinning down — anything more is double coverage of
    the same 30-line feature.
    """

    @pytest.fixture(autouse=True)
    def _vision_capable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # These tests exercise the cap, not the vision gate — pin it open.
        monkeypatch.setattr(
            llm_step_module, "model_supports_image_input", lambda *_: True
        )

    def test_disabled_by_default_passes_everything_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without ENABLE_AZURE_IMAGE_CAP, even an Azure request with many
        images flows untouched (no drops, no trailing reminder)."""
        monkeypatch.setattr(llm_step_module, "ENABLE_AZURE_IMAGE_CAP", False)
        history = [
            _make_user_msg("hi", images=[_make_image(f"img{i}") for i in range(100)])
        ]
        translated = translate_history_to_native_messages(
            history=history, llm_config=_make_llm_config(AZURE_PROVIDER_NAME)
        )
        assert isinstance(translated, list)
        assert len(translated) == 1
        assert isinstance(translated[0], pm.ModelRequest)
        assert len(_attached_image_file_ids(translated[0])) == 100

    def test_enabled_caps_azure_keeps_first_attachments_and_emits_reminder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Azure + cap enabled + over-limit → first-N attachments survive
        (user-attached preferred over later project-context fill), and a
        trailing system-reminder pm.ModelRequest is emitted with the centralized
        IMAGE_DROP_REMINDER prompt."""
        monkeypatch.setattr(llm_step_module, "ENABLE_AZURE_IMAGE_CAP", True)
        monkeypatch.setattr(llm_step_module, "_AZURE_DEFAULT_IMAGE_CAP", 3)
        history = [
            _make_user_msg(
                "describe", images=[_make_image(f"img{i}") for i in range(5)]
            )
        ]
        translated = translate_history_to_native_messages(
            history=history, llm_config=_make_llm_config(AZURE_PROVIDER_NAME)
        )
        assert isinstance(translated, list)
        assert len(translated) == 2
        user_msg, reminder = translated
        assert isinstance(user_msg, pm.ModelRequest)
        assert _attached_image_file_ids(user_msg) == ["img0", "img1", "img2"]
        assert isinstance(reminder, pm.ModelRequest)
        assert _user_content(reminder) == _expected_image_drop_reminder(dropped_count=2)

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
        translated = translate_history_to_native_messages(
            history=history, llm_config=_make_llm_config(OPENAI_PROVIDER_NAME)
        )
        assert isinstance(translated, list)
        assert len(translated) == 1
        assert isinstance(translated[0], pm.ModelRequest)
        assert len(_attached_image_file_ids(translated[0])) == 5


class TestNonVisionImageStripping:
    """History can contain images the currently selected model cannot accept
    (e.g. after a mid-session model switch). translate_history_to_native_messages
    must replace them with text markers instead of causing a provider 400."""

    def test_strips_image_parts_for_non_vision_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            llm_step_module, "model_supports_image_input", lambda *_: False
        )
        history = [_make_user_msg("look at this", images=[_make_image("img0")])]
        translated = translate_history_to_native_messages(
            history=history, llm_config=_make_llm_config(OPENAI_PROVIDER_NAME)
        )
        assert isinstance(translated, list)
        (user_msg,) = translated
        assert isinstance(user_msg, pm.ModelRequest)
        content = _user_content(user_msg)
        assert isinstance(content, list)
        assert not any(isinstance(p, pm.BinaryContent) for p in content)
        markers = [p for p in content if isinstance(p, str) and "img0" in p]
        assert markers
        assert "does not support image input" in markers[0]

    def test_keeps_image_parts_for_vision_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            llm_step_module, "model_supports_image_input", lambda *_: True
        )
        history = [_make_user_msg("look at this", images=[_make_image("img0")])]
        translated = translate_history_to_native_messages(
            history=history, llm_config=_make_llm_config(OPENAI_PROVIDER_NAME)
        )
        (user_msg,) = translated
        assert isinstance(user_msg, pm.ModelRequest)
        content = _user_content(user_msg)
        assert isinstance(content, list)
        assert _attached_image_file_ids(user_msg) == ["img0"]
        assert any(isinstance(p, pm.BinaryContent) for p in content)

    def test_capability_not_checked_without_images(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_: object) -> bool:
            raise AssertionError("capability check should not run for text-only")

        monkeypatch.setattr(llm_step_module, "model_supports_image_input", _boom)
        history = [_make_user_msg("just text")]
        translated = translate_history_to_native_messages(
            history=history, llm_config=_make_llm_config(OPENAI_PROVIDER_NAME)
        )
        assert isinstance(translated, list)
        assert len(translated) == 1


def test_native_tool_return_retains_sanitized_call_name() -> None:
    history = TestTranslateHistoryToLlmFormat._tool_history()
    assert history[0].tool_calls
    history[0].tool_calls[0].tool_name = "ServiceNow API"
    translated = translate_history_to_native_messages(
        history, _make_llm_config(LlmProviderNames.BEDROCK)
    )
    response = translated[1]
    assert isinstance(response, pm.ModelRequest)
    returned = response.parts[0]
    assert isinstance(returned, pm.ToolReturnPart)
    assert returned.tool_name == "ServiceNow_API"


def test_native_file_metadata_survives_empty_assistant() -> None:
    translated = translate_history_to_native_messages(
        [
            ChatMessageSimple(
                message="", token_count=0, message_type=MessageType.ASSISTANT
            ),
            ChatMessageSimple(
                message="file contents",
                token_count=3,
                message_type=MessageType.USER,
                file_id="file-123",
            ),
        ],
        _make_llm_config(LlmProviderNames.OPENAI),
    )
    assert len(translated) == 1
    assert translated[0].metadata == {"onyx_file_id": "file-123"}


def test_native_cache_point_stops_at_user_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_step_module, "PROMPT_CACHE_CHAT_HISTORY", True)
    translated = translate_history_to_native_messages(
        [
            ChatMessageSimple(
                message="cached",
                token_count=2,
                message_type=MessageType.USER,
                should_cache=True,
            ),
            ChatMessageSimple(
                message="uncached",
                token_count=2,
                message_type=MessageType.USER,
                should_cache=False,
            ),
        ],
        _make_llm_config(LlmProviderNames.ANTHROPIC),
    )
    cached = _user_content(translated[0])
    assert isinstance(cached, list)
    assert cached[0] == "cached"
    assert isinstance(cached[-1], pm.CachePoint)
    assert _user_content(translated[1]) == "uncached"
