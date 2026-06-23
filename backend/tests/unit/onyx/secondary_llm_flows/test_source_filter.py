from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.llm.models import UserMessage
from onyx.secondary_llm_flows.source_filter import decide_search_scope
from onyx.secondary_llm_flows.source_filter import SearchCycle
from onyx.tools.models import ChatMinimalTextMessage

A = DocumentSource.ZENDESK
B = DocumentSource.CONFLUENCE


def _run_decision(
    history: list[ChatMinimalTextMessage],
    connected: list[DocumentSource],
    previous_cycles: list[SearchCycle],
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
        scope = decide_search_scope(history, llm, connected, previous_cycles, ["q"])
    return scope, captured["prompt"]


def test_prompt_excludes_assistant_turns_and_ends_with_user() -> None:
    """Assistant/tool turns must not leak into the decision prompt, and the
    prompt must be a single user message (providers reject assistant prefills)."""
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
    scope, prompt = _run_decision(history, [A, B], [], "[confluence]")

    assert all(isinstance(m, UserMessage) for m in prompt)
    assert isinstance(prompt[-1], UserMessage)
    text = prompt[-1].content
    assert "Let me search Zendesk first." not in text
    assert "<huge zendesk result dump>" not in text
    assert scope == [B]


def test_first_search_renders_na_for_previous_cycles() -> None:
    history = [
        ChatMinimalTextMessage(
            message="Search Confluence.", message_type=MessageType.USER
        )
    ]
    _scope, prompt = _run_decision(history, [A, B], [], "[]")
    assert "N/A This is the first search" in prompt[-1].content


def test_previous_cycles_are_rendered_in_the_prompt() -> None:
    """Prior cycles (queries + applied filters) reach the prompt so a backoff
    sequence can advance."""
    history = [
        ChatMinimalTextMessage(
            message="Check Zendesk first, then Confluence.",
            message_type=MessageType.USER,
        )
    ]
    cycles: list[SearchCycle] = [
        SearchCycle(
            cycle_number=1,
            queries=["login bug"],
            searched_sources=["zendesk"],
        )
    ]
    scope, prompt = _run_decision(history, [A, B], cycles, "[confluence]")
    text = prompt[-1].content
    assert "zendesk" in text and "login bug" in text
    assert scope == [B]


def test_fewer_than_two_sources_skips_the_llm() -> None:
    """With nothing to scope between, the decision returns None without an LLM call."""
    history = [
        ChatMinimalTextMessage(message="Check Zendesk.", message_type=MessageType.USER)
    ]
    llm = MagicMock()
    for connected in ([], [A]):
        assert decide_search_scope(history, llm, connected, [], ["q"]) is None
    llm.invoke.assert_not_called()


def test_empty_bracket_is_unscoped() -> None:
    history = [
        ChatMinimalTextMessage(
            message="What's our PTO policy?", message_type=MessageType.USER
        )
    ]
    scope, _prompt = _run_decision(history, [A, B], [], "[]")
    assert scope is None


def test_stray_text_around_list_still_parses() -> None:
    history = [
        ChatMinimalTextMessage(message="Check Zendesk.", message_type=MessageType.USER)
    ]
    scope, _prompt = _run_decision(history, [A, B], [], "Sure: [zendesk]")
    assert scope == [A]


def test_only_the_last_five_user_turns_reach_the_prompt() -> None:
    """Older user turns are dropped so the decision sees only recent context."""
    history = [
        ChatMinimalTextMessage(message=f"msg {i}", message_type=MessageType.USER)
        for i in range(8)
    ]
    _scope, prompt = _run_decision(history, [A, B], [], "[]")

    text = prompt[-1].content
    # msg 7 is the current query (query reminder); msgs 3-6 are recent history;
    # msgs 0-2 are dropped.
    assert "msg 7" in text and "msg 3" in text
    assert "msg 2" not in text
    assert "msg 0" not in text
