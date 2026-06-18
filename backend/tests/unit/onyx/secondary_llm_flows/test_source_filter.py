from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.llm.models import AssistantMessage
from onyx.llm.models import UserMessage
from onyx.secondary_llm_flows.source_filter import decide_search_scope
from onyx.tools.models import ChatMinimalTextMessage

A = DocumentSource.ZENDESK
B = DocumentSource.CONFLUENCE


def test_decide_search_scope_excludes_assistant_turns_and_ends_with_user() -> None:
    """Regression: even when the history ends with assistant/tool content (which
    Anthropic rejects as a prefill), the decision prompt must contain only the
    user-side turns and end with a user message."""
    history = [
        ChatMinimalTextMessage(
            message="Check Zendesk first, then Confluence.",
            message_type=MessageType.USER,
        ),
        ChatMinimalTextMessage(
            message="Help resolve this ticket.", message_type=MessageType.USER
        ),
        ChatMinimalTextMessage(
            message="Let me search Zendesk first.", message_type=MessageType.ASSISTANT
        ),
        ChatMinimalTextMessage(
            message="<huge zendesk result dump>",
            message_type=MessageType.TOOL_CALL_RESPONSE,
        ),
    ]

    captured: dict = {}

    def fake_invoke(prompt: list, **_kwargs: object) -> MagicMock:
        captured["prompt"] = prompt
        resp = MagicMock()
        resp.choice.message.content = '{"sources": ["confluence"], "next": null}'
        return resp

    llm = MagicMock()
    llm.invoke.side_effect = fake_invoke

    with (
        patch(
            "onyx.secondary_llm_flows.source_filter.llm_generation_span",
            return_value=nullcontext(MagicMock()),
        ),
        patch("onyx.secondary_llm_flows.source_filter.record_llm_response"),
    ):
        scope, next_source = decide_search_scope(history, {A}, llm, [A, B])

    prompt = captured["prompt"]
    assert not any(isinstance(m, AssistantMessage) for m in prompt), (
        "assistant/tool turns must be excluded from the decision prompt"
    )
    assert isinstance(prompt[-1], UserMessage), (
        "the decision prompt must end with a user message"
    )
    assert scope == [B]
