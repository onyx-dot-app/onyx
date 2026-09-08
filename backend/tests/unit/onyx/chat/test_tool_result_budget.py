"""Regression tests for tool results that exceed the model input budget."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

import litellm
import pytest
from litellm.types.utils import ChatCompletionDeltaToolCall, Delta
from litellm.types.utils import Function as LiteLLMFunction

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import NullEmitter
from onyx.chat.llm_loop import run_llm_loop
from onyx.chat.llm_step import translate_history_to_llm_format
from onyx.chat.models import ChatMessageSimple, ExtractedContextFiles, ToolCallSimple
from onyx.chat.tool_result_budget import (
    TOOL_RESULT_TRUNCATION_NOTICE,
    shorten_tool_result,
)
from onyx.configs.constants import MessageType
from onyx.llm.constants import LlmProviderNames
from onyx.llm.exceptions import InputBudgetExceededError
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.input_budget import estimate_request_tokens
from onyx.llm.models import (
    AssistantMessage,
    FunctionCall,
    LanguageModelInput,
    LLMInputBudget,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.interface import Tool
from onyx.tools.models import ToolResponse


class _ScriptedResultTool(Tool[None]):
    def __init__(self, results: dict[str, str]) -> None:
        super().__init__(NullEmitter())
        self._results = results

    @property
    def id(self) -> int:
        return 1

    @property
    def name(self) -> str:
        return "scripted_result"

    @property
    def description(self) -> str:
        return "Return deterministic text for a test case."

    @property
    def display_name(self) -> str:
        return "Scripted result"

    def tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}},
                    "required": ["label"],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        pass

    def run(
        self,
        placement: Placement,
        override_kwargs: None,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        del placement, override_kwargs
        result = self._results[llm_kwargs["label"]]
        return ToolResponse(rich_response=result, llm_facing_response=result)


def _make_llm(max_input_tokens: int) -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider=LlmProviderNames.OPENAI,
        model_name="gpt-3.5-turbo",
        max_input_tokens=max_input_tokens,
        timeout=30,
    )


def _make_provider_llm(provider: str, model: str) -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider=provider,
        model_name=model,
        max_input_tokens=32_000,
        timeout=30,
    )


def _make_context_files() -> ExtractedContextFiles:
    return ExtractedContextFiles(
        file_texts=[],
        image_files=[],
        use_as_search_filter=False,
        total_token_count=0,
        file_metadata=[],
        uncapped_token_count=0,
    )


def _tool_call_chunk(labels: list[str]) -> litellm.ModelResponse:
    delta = Delta(role="assistant", content=None)
    delta.tool_calls = [
        ChatCompletionDeltaToolCall(
            id=f"call-{label}",
            function=LiteLLMFunction(
                name="scripted_result",
                arguments=json.dumps({"label": label}),
            ),
            type="function",
            index=index,
        )
        for index, label in enumerate(labels)
    ]
    return litellm.ModelResponse(
        id="tool-call-response",
        choices=[
            litellm.Choices(
                delta=delta,
                finish_reason="tool_calls",
                index=0,
            )
        ],
        model="gpt-3.5-turbo",
    )


def _answer_chunk() -> litellm.ModelResponse:
    return litellm.ModelResponse(
        id="answer-response",
        choices=[
            litellm.Choices(
                delta=Delta(role="assistant", content="done"),
                finish_reason="stop",
                index=0,
            )
        ],
        model="gpt-3.5-turbo",
    )


def _run_scripted_loop(
    *,
    results: dict[str, str],
    max_input_tokens: int,
    tool_batches: list[list[str]] | None = None,
    completion_requests: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], ChatStateContainer]:
    llm = _make_llm(max_input_tokens)
    token_counter = get_llm_token_counter(llm)
    recorded_requests = completion_requests if completion_requests is not None else []
    batches = tool_batches or [list(results)]

    def fake_completion(**kwargs: Any) -> list[litellm.ModelResponse]:
        recorded_requests.append(kwargs)
        request_index = len(recorded_requests) - 1
        if request_index < len(batches):
            return [_tool_call_chunk(batches[request_index])]
        return [_answer_chunk()]

    user_text = "Use each scripted result, then answer."
    history = [
        ChatMessageSimple(
            message=user_text,
            token_count=token_counter(user_text),
            message_type=MessageType.USER,
        )
    ]
    state_container = ChatStateContainer()

    with (
        patch("litellm.completion", side_effect=fake_completion),
        patch(
            "onyx.chat.llm_loop.get_session_with_current_tenant",
            return_value=nullcontext(MagicMock()),
        ),
        patch("onyx.chat.llm_loop.get_default_base_system_prompt", return_value=""),
        patch("onyx.llm.litellm_singleton.config.initialize_litellm"),
    ):
        run_llm_loop(
            emitter=NullEmitter(),
            state_container=state_container,
            simple_chat_history=history,
            tools=[_ScriptedResultTool(results)],
            custom_agent_prompt=None,
            context_files=_make_context_files(),
            persona=None,
            user_memory_context=None,
            llm=llm,
            token_counter=token_counter,
        )

    return recorded_requests, state_container


def _request_text_tokens(
    request: dict[str, Any], token_counter: Callable[[str], int]
) -> int:
    request_text = json.dumps(
        {
            "messages": request["messages"],
            "tools": request.get("tools"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return token_counter(request_text)


def _assert_tool_call_associations(messages: list[dict[str, Any]]) -> None:
    assistant_tool_messages = [
        message
        for message in messages
        if message["role"] == "assistant" and message.get("tool_calls")
    ]
    call_ids = [
        call["id"]
        for message in assistant_tool_messages
        for call in message["tool_calls"]
    ]
    response_ids = [
        message["tool_call_id"] for message in messages if message["role"] == "tool"
    ]
    assert response_ids == call_ids


def test_one_excessive_tool_result_allows_bounded_followup_request() -> None:
    max_input_tokens = 32_000
    llm = _make_llm(max_input_tokens)
    token_counter = get_llm_token_counter(llm)
    result = "result " * 40_000

    requests, state_container = _run_scripted_loop(
        results={"large": result},
        max_input_tokens=max_input_tokens,
    )

    assert len(requests) == 2
    followup = requests[1]
    tool_messages = [
        message for message in followup["messages"] if message["role"] == "tool"
    ]
    assert len(tool_messages) == 1
    _assert_tool_call_associations(followup["messages"])
    assert token_counter(tool_messages[0]["content"]) <= 20_000
    assert tool_messages[0]["content"] != result
    assert "truncat" in tool_messages[0]["content"].lower()
    assert _request_text_tokens(followup, token_counter) <= int(max_input_tokens * 0.95)
    assert state_container.get_tool_calls()[0].tool_call_response == result


def test_batch_of_individually_acceptable_results_shares_request_budget() -> None:
    max_input_tokens = 24_000
    llm = _make_llm(max_input_tokens)
    token_counter = get_llm_token_counter(llm)
    results: dict[str, str] = {
        f"result-{index}": "result " * 8_000 for index in range(3)
    }

    assert all(token_counter(result) < 20_000 for result in results.values())
    assert sum(token_counter(result) for result in results.values()) > int(
        max_input_tokens * 0.95
    )

    requests, state_container = _run_scripted_loop(
        results=results,
        max_input_tokens=max_input_tokens,
    )

    assert len(requests) == 2
    followup = requests[1]
    tool_messages = [
        message for message in followup["messages"] if message["role"] == "tool"
    ]
    assert len(tool_messages) == 3
    _assert_tool_call_associations(followup["messages"])
    assert _request_text_tokens(followup, token_counter) <= int(max_input_tokens * 0.95)
    assert [call.tool_call_id for call in state_container.get_tool_calls()] == [
        "call-result-0",
        "call-result-1",
        "call-result-2",
    ]
    assert [call.tool_call_response for call in state_container.get_tool_calls()] == [
        results[label] for label in results
    ]


def test_small_tool_result_stays_unchanged() -> None:
    result = "A short complete result."

    requests, state_container = _run_scripted_loop(
        results={"small": result},
        max_input_tokens=1_000,
    )

    tool_message = next(
        message for message in requests[1]["messages"] if message["role"] == "tool"
    )
    assert tool_message["content"] == result
    assert state_container.get_tool_calls()[0].tool_call_response == result


def test_unicode_json_result_retains_original_prefix_and_saved_value() -> None:
    result = '{"title":"雪だるま ☃️","payload":"' + "漢字🙂" * 30_000 + '"}'

    requests, state_container = _run_scripted_loop(
        results={"unicode": result},
        max_input_tokens=32_000,
    )

    tool_message = next(
        message for message in requests[1]["messages"] if message["role"] == "tool"
    )
    shortened = tool_message["content"]
    prefix, separator, notice = shortened.rpartition("\n\n")
    assert separator
    assert result.startswith(prefix)
    assert "incomplete text excerpt" in notice
    assert not prefix.endswith("}")
    shortened.encode("utf-8")
    assert state_container.get_tool_calls()[0].tool_call_response == result


def test_json_escape_expansion_keeps_a_feasible_followup_request() -> None:
    max_input_tokens = 8_000
    result = "\\" * 100_000
    llm = _make_llm(max_input_tokens)
    token_counter = get_llm_token_counter(llm)

    requests, state_container = _run_scripted_loop(
        results={"escapes": result},
        max_input_tokens=max_input_tokens,
    )

    assert len(requests) == 2
    assert _request_text_tokens(requests[1], token_counter) <= int(
        max_input_tokens * 0.95
    )
    assert state_container.get_tool_calls()[0].tool_call_response == result


def test_repeated_tool_cycles_recompute_the_shared_budget() -> None:
    max_input_tokens = 32_000
    results: dict[str, str] = {
        "first": "first-result " * 9_000,
        "second": "second-result " * 9_000,
    }
    llm = _make_llm(max_input_tokens)
    token_counter = get_llm_token_counter(llm)

    requests, state_container = _run_scripted_loop(
        results=results,
        max_input_tokens=max_input_tokens,
        tool_batches=[["first"], ["second"]],
    )

    assert len(requests) == 3
    assert all(
        _request_text_tokens(request, token_counter) <= int(max_input_tokens * 0.95)
        for request in requests
    )
    final_tool_messages = [
        message for message in requests[-1]["messages"] if message["role"] == "tool"
    ]
    assert len(final_tool_messages) == 2
    _assert_tool_call_associations(requests[-1]["messages"])
    assert (
        sum(
            "incomplete text excerpt" in message["content"]
            for message in final_tool_messages
        )
        == 1
    )
    assert [call.tool_call_response for call in state_container.get_tool_calls()] == [
        results["first"],
        results["second"],
    ]


def test_ollama_conversion_charges_tool_labels_and_reminder() -> None:
    llm = _make_provider_llm(LlmProviderNames.OLLAMA_CHAT, "llama3")
    history = [
        ChatMessageSimple(
            message="",
            token_count=1,
            message_type=MessageType.ASSISTANT,
            tool_calls=[
                ToolCallSimple(
                    tool_call_id="call-1",
                    tool_name="scripted_result",
                    tool_arguments={"label": "x"},
                    token_count=1,
                )
            ],
        ),
        ChatMessageSimple(
            message="result",
            token_count=1,
            message_type=MessageType.TOOL_CALL_RESPONSE,
            tool_call_id="call-1",
        ),
        ChatMessageSimple(
            message="Current reminder",
            token_count=2,
            message_type=MessageType.USER_REMINDER,
        ),
    ]

    prepared = llm.prepare_messages(
        translate_history_to_llm_format(history, llm.config),
        True,
    )

    assert "[Tool Call] name=scripted_result id=call-1" in prepared[0]["content"]
    assert prepared[1]["content"] == "[Tool Result] id=call-1\nresult"
    assert prepared[2]["content"] == (
        "<system-reminder>\nCurrent reminder\n</system-reminder>"
    )


def test_mistral_conversion_includes_tool_to_user_bridge() -> None:
    llm = _make_provider_llm(LlmProviderNames.MISTRAL, "mistral-small")
    prompt: LanguageModelInput = [
        AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-1",
                    function=FunctionCall(
                        name="scripted_result", arguments='{"label":"x"}'
                    ),
                )
            ],
        ),
        ToolMessage(content="result", tool_call_id="call-1"),
        UserMessage(content="Current reminder"),
    ]

    prepared = llm.prepare_messages(prompt, True)

    assert [message["role"] for message in prepared] == [
        "assistant",
        "tool",
        "assistant",
        "user",
    ]
    assert prepared[2]["content"] == "Noted. Continuing."


def test_bedrock_final_cycle_converts_tool_history_without_definitions() -> None:
    llm = _make_provider_llm(LlmProviderNames.BEDROCK, "anthropic.claude-3-haiku")
    prompt: LanguageModelInput = [
        AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-1",
                    function=FunctionCall(
                        name="scripted_result", arguments='{"label":"x"}'
                    ),
                )
            ],
        ),
        ToolMessage(content="result", tool_call_id="call-1"),
    ]

    prepared = llm.prepare_messages(prompt, False)

    assert all(message["role"] != "tool" for message in prepared)
    assert all("tool_calls" not in message for message in prepared)
    assert "[Tool Call]" in prepared[0]["content"]
    assert "[Tool Result] id=call-1" in prepared[1]["content"]


def test_final_request_guard_stops_before_litellm_completion() -> None:
    llm = _make_llm(32_000)
    token_counter = get_llm_token_counter(llm)

    with (
        patch("litellm.completion") as completion,
        pytest.raises(InputBudgetExceededError) as exc_info,
    ):
        list(
            llm.stream(
                UserMessage(content="This request does not fit."),
                input_budget=LLMInputBudget(
                    max_tokens=0,
                    token_counter=token_counter,
                ),
            )
        )

    completion.assert_not_called()
    assert exc_info.value.error_code == "CONTEXT_TOO_LONG"
    assert exc_info.value.is_retryable is False


def test_final_request_guard_accepts_exact_estimated_budget() -> None:
    llm = _make_llm(32_000)
    token_counter = get_llm_token_counter(llm)
    prompt = UserMessage(content="This request exactly fits its estimate.")
    prepared = llm.prepare_messages(prompt, False)
    estimated_tokens = estimate_request_tokens(prepared, None, token_counter)

    with patch("litellm.completion", return_value=[_answer_chunk()]) as completion:
        responses = list(
            llm.stream(
                prompt,
                input_budget=LLMInputBudget(
                    max_tokens=estimated_tokens,
                    token_counter=token_counter,
                ),
            )
        )

    assert responses
    completion.assert_called_once()


def test_notice_is_included_in_each_shortening_limit() -> None:
    token_counter = get_llm_token_counter(_make_llm(32_000))
    notice_tokens = token_counter(TOOL_RESULT_TRUNCATION_NOTICE)
    result = "result " * 100

    with pytest.raises(InputBudgetExceededError) as exc_info:
        shorten_tool_result(result, notice_tokens - 1, token_counter)
    assert exc_info.value.error_code == "CONTEXT_TOO_LONG"
    assert exc_info.value.is_retryable is False

    at_notice, at_notice_tokens = shorten_tool_result(
        result, notice_tokens, token_counter
    )
    assert at_notice == TOOL_RESULT_TRUNCATION_NOTICE
    assert at_notice_tokens == notice_tokens

    above_notice, above_notice_tokens = shorten_tool_result(
        result, notice_tokens + 1, token_counter
    )
    assert result.startswith(above_notice.removesuffix(TOOL_RESULT_TRUNCATION_NOTICE))
    assert above_notice.endswith(TOOL_RESULT_TRUNCATION_NOTICE)
    assert above_notice_tokens <= notice_tokens + 1

    shortened_again, shortened_again_tokens = shorten_tool_result(
        above_notice, notice_tokens, token_counter, above_notice_tokens
    )
    assert shortened_again.count(TOOL_RESULT_TRUNCATION_NOTICE) == 1
    assert shortened_again_tokens == notice_tokens


def test_tiny_budget_stops_before_a_second_provider_request() -> None:
    completion_requests: list[dict[str, Any]] = []

    with pytest.raises(InputBudgetExceededError) as exc_info:
        _run_scripted_loop(
            results={"tiny": "result " * 1_000},
            max_input_tokens=100,
            completion_requests=completion_requests,
        )

    assert len(completion_requests) == 1
    assert exc_info.value.error_code == "CONTEXT_TOO_LONG"
    assert exc_info.value.is_retryable is False


@pytest.mark.parametrize(
    ("configured_value", "expected_value"),
    [(None, "20000"), ("7", "7")],
)
def test_configured_tool_result_ceiling_accepts_default_and_positive_values(
    configured_value: str | None, expected_value: str
) -> None:
    env = os.environ.copy()
    if configured_value is None:
        env.pop("MAX_TOOL_RESULT_TOKENS", None)
    else:
        env["MAX_TOOL_RESULT_TOKENS"] = configured_value

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from onyx.configs.chat_configs import MAX_TOOL_RESULT_TOKENS; "
            "print(MAX_TOOL_RESULT_TOKENS)",
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == expected_value


@pytest.mark.parametrize(
    ("configured_value", "error_fragment"),
    [
        ("0", "MAX_TOOL_RESULT_TOKENS must be a positive integer"),
        ("-1", "MAX_TOOL_RESULT_TOKENS must be a positive integer"),
        ("not-an-integer", "invalid literal for int()"),
    ],
)
def test_configured_tool_result_ceiling_rejects_invalid_values(
    configured_value: str, error_fragment: str
) -> None:
    env = os.environ.copy()
    env["MAX_TOOL_RESULT_TOKENS"] = configured_value

    result = subprocess.run(
        [sys.executable, "-c", "import onyx.configs.chat_configs"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode != 0
    assert error_fragment in result.stderr
