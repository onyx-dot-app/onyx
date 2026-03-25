"""Unit tests for multi-model answer generation types.

Tests cover:
- Placement.model_index serialization
- MultiModelMessageResponseIDInfo round-trip
- SendMessageRequest.llm_overrides backward compatibility
- ChatMessageDetail new fields
"""

from uuid import uuid4

from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.server.query_and_chat.models import MultiModelMessageResponseIDInfo
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.placement import Placement


class TestPlacementModelIndex:
    def test_default_none(self) -> None:
        p = Placement(turn_index=0)
        assert p.model_index is None

    def test_set_value(self) -> None:
        p = Placement(turn_index=0, model_index=2)
        assert p.model_index == 2

    def test_serializes(self) -> None:
        p = Placement(turn_index=0, tab_index=1, model_index=1)
        d = p.model_dump()
        assert d["model_index"] == 1

    def test_none_excluded_when_default(self) -> None:
        p = Placement(turn_index=0)
        d = p.model_dump()
        assert d["model_index"] is None


class TestMultiModelMessageResponseIDInfo:
    def test_round_trip(self) -> None:
        info = MultiModelMessageResponseIDInfo(
            user_message_id=42,
            reserved_assistant_message_ids=[43, 44, 45],
            model_names=["gpt-4", "claude-opus", "gemini-pro"],
        )
        d = info.model_dump()
        restored = MultiModelMessageResponseIDInfo(**d)
        assert restored.user_message_id == 42
        assert restored.reserved_assistant_message_ids == [43, 44, 45]
        assert restored.model_names == ["gpt-4", "claude-opus", "gemini-pro"]

    def test_null_user_message_id(self) -> None:
        info = MultiModelMessageResponseIDInfo(
            user_message_id=None,
            reserved_assistant_message_ids=[1, 2],
            model_names=["a", "b"],
        )
        assert info.user_message_id is None


class TestSendMessageRequestOverrides:
    def test_llm_overrides_default_none(self) -> None:
        req = SendMessageRequest(
            message="hello",
            chat_session_id=uuid4(),
        )
        assert req.llm_overrides is None

    def test_llm_overrides_accepts_list(self) -> None:
        overrides = [
            LLMOverride(model_provider="openai", model_version="gpt-4"),
            LLMOverride(model_provider="anthropic", model_version="claude-opus"),
        ]
        req = SendMessageRequest(
            message="hello",
            chat_session_id=uuid4(),
            llm_overrides=overrides,
        )
        assert req.llm_overrides is not None
        assert len(req.llm_overrides) == 2

    def test_backward_compat_single_override(self) -> None:
        req = SendMessageRequest(
            message="hello",
            chat_session_id=uuid4(),
            llm_override=LLMOverride(model_provider="openai", model_version="gpt-4"),
        )
        assert req.llm_override is not None
        assert req.llm_overrides is None


class TestChatMessageDetailMultiModel:
    def test_defaults_none(self) -> None:
        from onyx.configs.constants import MessageType

        detail = ChatMessageDetail(
            message_id=1,
            message="hello",
            message_type=MessageType.ASSISTANT,
            time_sent="2026-03-22T00:00:00Z",
            files=[],
        )
        assert detail.preferred_response_id is None
        assert detail.model_display_name is None

    def test_set_values(self) -> None:
        from onyx.configs.constants import MessageType

        detail = ChatMessageDetail(
            message_id=1,
            message="hello",
            message_type=MessageType.USER,
            time_sent="2026-03-22T00:00:00Z",
            files=[],
            preferred_response_id=42,
            model_display_name="GPT-4",
        )
        assert detail.preferred_response_id == 42
        assert detail.model_display_name == "GPT-4"

    def test_serializes(self) -> None:
        from onyx.configs.constants import MessageType

        detail = ChatMessageDetail(
            message_id=1,
            message="hello",
            message_type=MessageType.ASSISTANT,
            time_sent="2026-03-22T00:00:00Z",
            files=[],
            model_display_name="Claude Opus",
        )
        d = detail.model_dump()
        assert d["model_display_name"] == "Claude Opus"
        assert d["preferred_response_id"] is None
