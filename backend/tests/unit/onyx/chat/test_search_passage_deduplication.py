"""Prompt preparation retains unique evidence and shortens exact repeats per step."""

import json

import pytest

from onyx.chat.models import SearchPassages
from onyx.chat.prompt_utils import SearchPassageCache, prepare_prompt
from onyx.context.search.models import SearchDocsResponse
from onyx.llm.models import (
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)


def test_search_passages_are_deduplicated_only_within_the_same_step() -> None:
    passage = "Exact shared evidence. " * 100
    different_passage = "Additional evidence from the same document. " * 100

    def result(call_id: str, citation: int, content: str) -> ToolResultMessage:
        return ToolResultMessage(
            tool_call_id=call_id,
            tool_name="internal_search",
            content=json.dumps(
                {
                    "results": [
                        {"document": citation, "title": "Source", "content": content}
                    ],
                    "note": "Keep this scope restriction.",
                }
            ),
            details=SearchDocsResponse(
                search_docs=[], citation_mapping={citation: "same-document"}
            ),
        )

    messages: list[Message] = [
        UserMessage(content="Compare these subjects"),
        AssistantMessage(content=[]),
        result("first", 1, passage),
        result("repeat", 101, passage),
        result("different", 201, different_passage),
        AssistantMessage(content=[]),
        result("next-step", 301, passage),
    ]
    originals = [message.model_copy(deep=True) for message in messages]

    def prepare() -> list[Message]:
        return prepare_prompt(
            messages,
            system_prompt=None,
            custom_agent_prompt=None,
            reminder_message=None,
            context_files=None,
            token_counter=len,
            search_passage_cache={},
        )

    prepared = prepare()
    results = [
        message for message in prepared if isinstance(message, ToolResultMessage)
    ]
    first, repeated, different, next_step = results
    assert passage in first.text
    repeated_payload = json.loads(repeated.text)
    assert repeated_payload["results"][0]["content"] == (
        "Same passage as document 1 in tool result first; use that result's content."
    )
    assert repeated_payload["results"][0]["document"] == 101
    assert repeated_payload["results"][0]["title"] == "Source"
    assert repeated_payload["note"] == "Keep this scope restriction."
    assert different_passage in different.text
    assert passage in next_step.text
    original_repeat = originals[3]
    assert isinstance(original_repeat, ToolResultMessage)
    assert repeated.details == original_repeat.details
    assert [message.tool_call_id for message in results] == [
        "first",
        "repeat",
        "different",
        "next-step",
    ]
    assert messages == originals
    assert prepare() == prepared


def test_each_step_of_search_results_is_parsed_once_per_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passage = "Exact shared evidence. " * 100

    def result(call_id: str, citation: int) -> ToolResultMessage:
        return ToolResultMessage(
            tool_call_id=call_id,
            tool_name="internal_search",
            content=json.dumps(
                {"results": [{"document": citation, "title": "S", "content": passage}]}
            ),
            details=SearchDocsResponse(
                search_docs=[], citation_mapping={citation: "same-document"}
            ),
        )

    parsed: list[str] = []
    parse = SearchPassages.model_validate_json

    def counting_parse(data: str | bytes) -> SearchPassages:
        parsed.append(str(data))
        return parse(data)

    monkeypatch.setattr(SearchPassages, "model_validate_json", counting_parse)
    history: list[Message] = [
        UserMessage(content="Question"),
        AssistantMessage(content=[]),
        result("first", 1),
        result("repeat", 2),
    ]
    cache: SearchPassageCache = {}

    def prepare(messages: list[Message]) -> list[Message]:
        return prepare_prompt(
            messages,
            system_prompt=None,
            custom_agent_prompt=None,
            reminder_message=None,
            context_files=None,
            token_counter=len,
            search_passage_cache=cache,
        )

    first = prepare(history)
    assert len(parsed) == 2
    # A later request with the same step parses nothing and gives the same
    # deduplicated contents.
    history += [AssistantMessage(content=[]), result("later", 3)]
    second = prepare(history)
    assert len(parsed) == 3
    assert second[: len(first)] == first
    assert "Same passage as document 1" in second[3].text
