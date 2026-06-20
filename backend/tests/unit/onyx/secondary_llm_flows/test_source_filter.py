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
        scope = decide_search_scope(history, llm, [A, B], [])

    prompt = captured["prompt"]
    assert not any(isinstance(m, AssistantMessage) for m in prompt), (
        "assistant/tool turns must be excluded from the decision prompt"
    )
    assert isinstance(prompt[-1], UserMessage), (
        "the decision prompt must end with a user message"
    )
    assert scope == [B]


def _run_decision(
    history: list[ChatMinimalTextMessage],
    connected: list[DocumentSource],
    already_searched: list[DocumentSource],
    llm_returns: str,
) -> tuple[list[DocumentSource] | None, list]:
    """Run decide_search_scope with the LLM stubbed to return `llm_returns`.
    Returns (scope, prompt_messages)."""
    captured: dict = {}

    def fake_invoke(prompt: list, **_kwargs: object) -> MagicMock:
        captured["prompt"] = prompt
        resp = MagicMock()
        resp.choice.message.content = llm_returns
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
        scope = decide_search_scope(history, llm, connected, already_searched)
    return scope, captured["prompt"]


def test_already_searched_is_rendered_into_the_prompt() -> None:
    """The sources already searched this turn must reach the decision prompt so a
    sequential directive can advance past them."""
    history = [
        ChatMinimalTextMessage(
            message="Check Zendesk first, then Confluence.",
            message_type=MessageType.USER,
        )
    ]
    # already searched A (zendesk); the flow should advance to B (confluence).
    scope, prompt = _run_decision(history, [A, B], [A], '{"sources": ["confluence"]}')

    system_text = prompt[0].content
    assert A.value in system_text, (
        "already-searched source must appear in the decision prompt"
    )
    assert scope == [B]


def test_no_already_searched_renders_none_yet() -> None:
    """With nothing searched yet, the prompt states so explicitly (not a blank)."""
    history = [
        ChatMinimalTextMessage(
            message="Search Confluence.", message_type=MessageType.USER
        )
    ]
    _scope, prompt = _run_decision(history, [A, B], [], '{"sources": ["confluence"]}')
    assert "(none yet)" in prompt[0].content


def test_duplicated_json_output_still_scopes() -> None:
    """Regression: a model occasionally emits the JSON object twice
    (`{...}{...}`). The flow must still resolve the scope, not fall open to an
    unscoped search."""
    history = [
        ChatMinimalTextMessage(message="Check Zendesk.", message_type=MessageType.USER)
    ]
    scope, _prompt = _run_decision(
        history, [A, B], [], '{"sources":["zendesk"]}{"sources":["zendesk"]}'
    )
    assert scope == [A]
