"""Unit tests for multi-model schema and Pydantic model additions."""

from datetime import datetime

from onyx.configs.constants import MessageType
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.server.query_and_chat.models import MultiModelMessageResponseIDInfo
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.placement import Placement


def test_placement_model_index_default_none() -> None:
    p = Placement(turn_index=0)
    assert p.model_index is None


def test_placement_model_index_set() -> None:
    p = Placement(turn_index=0, model_index=2)
    assert p.model_index == 2


def test_placement_serialization_with_model_index() -> None:
    p = Placement(turn_index=1, tab_index=0, model_index=1)
    data = p.model_dump()
    assert data["model_index"] == 1
    restored = Placement(**data)
    assert restored.model_index == 1


def test_multi_model_message_response_id_info() -> None:
    info = MultiModelMessageResponseIDInfo(
        user_message_id=42,
        reserved_assistant_message_ids=[100, 101, 102],
        model_names=["gpt-4", "claude-3-opus", "gemini-pro"],
    )
    data = info.model_dump()
    assert data["user_message_id"] == 42
    assert len(data["reserved_assistant_message_ids"]) == 3
    assert len(data["model_names"]) == 3


def test_multi_model_message_response_id_info_null_user() -> None:
    info = MultiModelMessageResponseIDInfo(
        user_message_id=None,
        reserved_assistant_message_ids=[10],
        model_names=["gpt-4"],
    )
    assert info.user_message_id is None


def test_send_message_request_llm_overrides_none_by_default() -> None:
    req = SendMessageRequest(
        message="hello",
        chat_session_id="00000000-0000-0000-0000-000000000001",
    )
    assert req.llm_overrides is None
    assert req.llm_override is None


def test_send_message_request_with_llm_overrides() -> None:
    overrides = [
        LLMOverride(model_provider="openai", model_version="gpt-4"),
        LLMOverride(model_provider="anthropic", model_version="claude-3-opus"),
    ]
    req = SendMessageRequest(
        message="compare these",
        chat_session_id="00000000-0000-0000-0000-000000000001",
        llm_overrides=overrides,
    )
    assert req.llm_overrides is not None
    assert len(req.llm_overrides) == 2


def test_send_message_request_backward_compat_single_override() -> None:
    """Existing single llm_override still works alongside new llm_overrides field."""
    req = SendMessageRequest(
        message="single model",
        chat_session_id="00000000-0000-0000-0000-000000000001",
        llm_override=LLMOverride(model_provider="openai", model_version="gpt-4"),
    )
    assert req.llm_override is not None
    assert req.llm_overrides is None


def test_chat_message_detail_multi_model_fields_default_none() -> None:
    detail = ChatMessageDetail(
        message_id=1,
        message="hello",
        message_type=MessageType.USER,
        time_sent=datetime.now(),
        files=[],
    )
    assert detail.preferred_response_id is None
    assert detail.model_display_name is None


def test_chat_message_detail_multi_model_fields_set() -> None:
    detail = ChatMessageDetail(
        message_id=1,
        message="response from gpt-4",
        message_type=MessageType.ASSISTANT,
        time_sent=datetime.now(),
        files=[],
        preferred_response_id=42,
        model_display_name="GPT-4",
    )
    assert detail.preferred_response_id == 42
    assert detail.model_display_name == "GPT-4"
    data = detail.model_dump()
    assert data["preferred_response_id"] == 42
    assert data["model_display_name"] == "GPT-4"
