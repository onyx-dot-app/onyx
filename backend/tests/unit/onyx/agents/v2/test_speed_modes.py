from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import nullcontext
from typing import Any

import pytest

from onyx.agents.v2 import llm as llm_module
from onyx.agents.v2.llm import (
    OnyxDecisionModel,
    compact_completion_context,
    create_minimal_completion_llm,
)
from onyx.agents.v2.models import (
    ExecutionContext,
    HarnessPolicy,
    RegisteredTool,
    ToolOutput,
    UsageSnapshot,
)
from onyx.agents.v2.runner import AgentHarness
from onyx.llm.interfaces import (
    LLM,
    LanguageModelInput,
    LLMConfig,
    LLMUserIdentity,
    ToolChoice,
)
from onyx.llm.model_response import (
    ChatCompletionMessageToolCall,
    Choice,
    FunctionCall,
    Message,
    ModelResponse,
    ModelResponseStream,
)
from onyx.llm.models import ReasoningEffort
from onyx.prompts.harness_v2 import CONCISE_SEARCH_ANSWER_PROMPT, SEARCH_ANSWER_PROMPT
from onyx.server.features.harness_v2.models import AgentRequest


def test_compact_completion_context_preserves_answer_receipts_and_nonsearch_content() -> (
    None
):
    context = _context_with_results(
        [
            {
                "tool_name": "internal_search",
                "status": "success",
                "answer": "SLO was 99.9% [1]",
                "answer_ref": "result_0001",
                "content": '{"answer":"SLO was 99.9% [1]","evidence":"chunk"}',
                "content_preview": "large redundant preview",
                "receipt": {
                    "executed_queries": ["slo"],
                    "answer_finish_reason": "stop",
                },
                "document_ids": ["doc-1"],
                "citation_mapping": {"1": "doc-1"},
                "read_more": {"result_ref": "result_0001", "offset": 800},
            },
            {
                "tool_name": "external__ticket",
                "status": "success",
                "content": "keep full non-search content",
                "content_preview": "keep preview too",
                "receipt": {"external_tool": "ticket"},
            },
            {
                "tool_name": "internal_search",
                "status": "success",
                "answer": "Error budget is exhausted [2]",
                "content": '{"answer":"Error budget is exhausted [2]"}',
                "content_preview": "second large redundant preview",
                "receipt": {"executed_queries": ["error budget"]},
                "read_more": {"result_ref": "result_0002", "offset": 1200},
            },
        ]
    )

    compact = compact_completion_context(context)

    assert compact is not None
    assert (
        json.loads(context)["current_turn_state"]["results"][0]["content_preview"]
        == "large redundant preview"
    )
    payload = json.loads(compact)
    search_result = payload["current_turn_state"]["results"][0]
    external_result = payload["current_turn_state"]["results"][1]
    second_search = payload["current_turn_state"]["results"][2]
    assert "content_preview" not in search_result
    assert "content_preview" not in second_search
    assert search_result["answer"] == "SLO was 99.9% [1]"
    assert search_result["receipt"]["executed_queries"] == ["slo"]
    assert search_result["read_more"]["offset"] == 0
    assert search_result["document_ids"] == ["doc-1"]
    assert search_result["citation_mapping"] == {"1": "doc-1"}
    assert external_result["content"] == "keep full non-search content"
    assert external_result["content_preview"] == "keep preview too"
    assert second_search["answer"] == "Error budget is exhausted [2]"
    assert second_search["read_more"]["offset"] == 0


@pytest.mark.parametrize(
    "result",
    [
        {"tool_name": "internal_search", "status": "error", "answer": "nope"},
        {"tool_name": "internal_search", "status": "partial", "answer": "maybe"},
        {
            "tool_name": "internal_search",
            "status": "success",
            "content": "missing answer",
        },
        {"tool_name": "external__ticket", "status": "success", "answer": "done"},
    ],
)
def test_compact_completion_context_falls_back_without_successful_search_answer(
    result: dict[str, Any],
) -> None:
    assert compact_completion_context(_context_with_results([result])) is None


def test_decision_model_uses_standard_first_then_minimal_with_tools_available() -> None:
    standard_llm = SequencedFakeLLM(
        [_tool_response("internal_search", {"objective": "find SLO"})]
    )
    completion_llm = SequencedFakeLLM(
        [_tool_response("internal_search", {"objective": "find remaining risk"})]
    )
    model = OnyxDecisionModel(standard_llm, completion_llm=completion_llm)
    tools = [_tool_definition("internal_search")]

    first = model.decide(
        task="answer",
        context=_context_with_results([]),
        tools=tools,
        remaining_seconds=10,
        remaining_tokens=1000,
        max_output_tokens=80,
    )
    second = model.decide(
        task="answer",
        context=_context_with_results(
            [
                {
                    "tool_name": "internal_search",
                    "status": "success",
                    "answer": "SLO was 99.9% [1]",
                    "content_preview": "redundant",
                }
            ]
        ),
        tools=tools,
        remaining_seconds=9,
        remaining_tokens=900,
        max_output_tokens=80,
    )

    assert first.decision_mode == "standard"
    assert first.calls[0].name == "internal_search"
    assert second.decision_mode == "minimal_compact"
    assert second.calls[0].name == "internal_search"
    assert standard_llm.calls[0]["reasoning_effort"] == ReasoningEffort.LOW
    assert completion_llm.calls[0]["reasoning_effort"] == ReasoningEffort.OFF
    assert standard_llm.calls[0]["tools"] == tools
    assert completion_llm.calls[0]["tools"] == tools


@pytest.mark.parametrize("status", ["success", "partial", "error"])
def test_minimal_decisions_keep_context_and_allow_followup(status: str) -> None:
    standard = SequencedFakeLLM([])
    minimal = SequencedFakeLLM(
        [_tool_response("internal_search", {"objective": "find missing facts"})] * 2
    )
    model = OnyxDecisionModel(standard, minimal_decision_llm=minimal)
    tools = [_tool_definition("internal_search")]
    contexts = [
        _context_with_results([]),
        _context_with_results(
            [
                {
                    "tool_name": "internal_search",
                    "status": status,
                    "answer": "Known fact [1]",
                    "content_preview": "Original evidence",
                }
            ]
        ),
    ]
    for context in contexts:
        decision = model.decide(
            task="answer",
            context=context,
            tools=tools,
            remaining_seconds=10,
            remaining_tokens=1000,
            max_output_tokens=None,
        )
        assert decision.decision_mode == "minimal"
        assert decision.calls[0].name == "internal_search"
        call = minimal.calls[-1]
        assert call["reasoning_effort"] == ReasoningEffort.OFF
        assert call["tools"] == tools
        assert call["max_tokens"] is None
        assert json.loads(call["prompt"][1].content)["context"] == context
    assert not standard.calls


def test_minimal_decisions_are_opt_in_and_search_only() -> None:
    assert AgentRequest(question="hello").decision_mode == "standard"
    with pytest.raises(ValueError, match="search-only"):
        AgentRequest(
            question="hello",
            persona_id=1,
            include_persona_tools=True,
            decision_mode="minimal",
        )


def test_agent_harness_records_standard_and_minimal_decision_modes() -> None:
    standard_llm = SequencedFakeLLM(
        [_tool_response("internal_search", {"objective": "find SLO"})]
    )
    completion_llm = SequencedFakeLLM(
        [
            _tool_response("internal_search", {"objective": "find remaining risk"}),
            _tool_response(
                "finish_task",
                {
                    "outcome": "completed",
                    "answer_ref": "result_0001",
                    "reason": "search answer is complete",
                },
            ),
        ]
    )
    policy = HarnessPolicy(max_model_calls=4, max_context_tokens=4000)

    result = AgentHarness(
        model=OnyxDecisionModel(standard_llm, completion_llm=completion_llm),
        tools=[
            RegisteredTool(
                name="internal_search",
                description="search",
                parameters={"type": "object", "properties": {}},
                execute=_search_answer,
                pinned=True,
                requires_approval=False,
            )
        ],
        policy=policy,
        usage=UsageSnapshot,
        token_counter=lambda _: 10,
    ).run("answer")

    decision_events = [
        event.data["decision_mode"]
        for event in result.events
        if event.kind == "model_decision"
    ]
    assert result.outcome == "completed"
    assert decision_events == ["standard", "minimal_compact", "minimal_compact"]
    assert len(standard_llm.calls) == 1
    assert len(completion_llm.calls) == 2
    assert completion_llm.calls[0]["tools"] == standard_llm.calls[0]["tools"]


def test_create_minimal_completion_llm_sends_minimal_reasoning_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class TransportSentinel(RuntimeError):
        pass

    def fake_completion(**kwargs: Any) -> None:
        captured.update(kwargs)
        raise TransportSentinel("stop before network")

    monkeypatch.setattr(
        llm_module, "llm_generation_span", lambda *_a, **_kw: nullcontext(None)
    )
    monkeypatch.setattr(
        "onyx.llm.litellm_singleton.litellm.completion",
        fake_completion,
    )

    llm = ConfigOnlyLLM(
        LLMConfig(
            model_provider="openai",
            model_name="gpt-5-mini",
            temperature=0,
            api_key="test-key",
            api_base="https://api.example.com",
            api_version="2026-01-01",
            custom_config={"custom": "value"},
            deployment_name="gpt-5-mini-deployment",
            max_input_tokens=12345,
            reasoning_effort_default=ReasoningEffort.LOW,
            reasoning_effort_user_default=ReasoningEffort.HIGH,
        )
    )
    minimal_llm = create_minimal_completion_llm(llm)

    with pytest.raises(TransportSentinel):
        minimal_llm.invoke(
            prompt=[],
            reasoning_effort=ReasoningEffort.OFF,
            max_tokens=20,
            total_timeout_override=5,
        )

    assert captured["model"] == "openai/responses/gpt-5-mini-deployment"
    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == "https://api.example.com"
    assert captured["api_version"] == "2026-01-01"
    assert captured["max_tokens"] == 20
    assert captured["reasoning"] == {"effort": "minimal"}


@pytest.mark.parametrize(
    "config",
    [
        LLMConfig(
            model_provider="anthropic",
            model_name="gpt-5-mini",
            temperature=0,
            max_input_tokens=1000,
        ),
        LLMConfig(
            model_provider="openai",
            model_name="gpt-4o-mini",
            temperature=0,
            max_input_tokens=1000,
        ),
        LLMConfig(
            model_provider="openai",
            model_name="gpt-5-mini",
            temperature=0,
            max_input_tokens=1000,
            reasoning_effort_max=ReasoningEffort.OFF,
        ),
    ],
)
def test_create_minimal_completion_llm_rejects_unsupported_config(
    config: LLMConfig,
) -> None:
    assert_minimal_rejected(config)


def test_speed_mode_defaults_and_concise_prompt_keep_baseline_contract() -> None:
    request = AgentRequest(question="What changed?")

    assert request.concise_answers is False
    assert request.completion_mode == "standard"
    assert CONCISE_SEARCH_ANSWER_PROMPT.startswith(SEARCH_ANSWER_PROMPT)
    assert "Keep every" in CONCISE_SEARCH_ANSWER_PROMPT
    assert "citation" in CONCISE_SEARCH_ANSWER_PROMPT
    assert "Brevity must not reduce coverage" in CONCISE_SEARCH_ANSWER_PROMPT
    assert "max" not in CONCISE_SEARCH_ANSWER_PROMPT.lower()


def test_minimal_mode_rejects_external_workflows() -> None:
    with pytest.raises(ValueError, match="search-only"):
        AgentRequest(
            question="Search and send an email",
            persona_id=1,
            include_persona_tools=True,
            completion_mode="minimal",
        )


def assert_minimal_rejected(config: LLMConfig) -> None:
    with pytest.raises(ValueError):
        create_minimal_completion_llm(ConfigOnlyLLM(config))


class ConfigOnlyLLM(LLM):
    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    @property
    def config(self) -> LLMConfig:
        return self._config

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
        total_timeout_override: float | None = None,
    ) -> ModelResponse:
        raise NotImplementedError

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        raise NotImplementedError


class SequencedFakeLLM(ConfigOnlyLLM):
    def __init__(self, responses: list[ModelResponse]) -> None:
        super().__init__(
            LLMConfig(
                model_provider="openai",
                model_name="gpt-5-mini",
                temperature=0,
                max_input_tokens=1000,
            )
        )
        self.calls: list[dict[str, Any]] = []
        self._responses = responses

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
        total_timeout_override: float | None = None,
    ) -> ModelResponse:
        self.calls.append(
            {
                "prompt": prompt,
                "tools": tools,
                "tool_choice": tool_choice,
                "structured_response_format": structured_response_format,
                "timeout_override": timeout_override,
                "max_tokens": max_tokens,
                "reasoning_effort": reasoning_effort,
                "user_identity": user_identity,
                "total_timeout_override": total_timeout_override,
            }
        )
        return self._responses.pop(0)


def _tool_definition(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "test tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _tool_response(name: str, arguments: dict[str, Any]) -> ModelResponse:
    return ModelResponse(
        id="response-id",
        created="now",
        choice=Choice(
            finish_reason="tool_calls",
            message=Message(
                tool_calls=[
                    ChatCompletionMessageToolCall(
                        id="call-1",
                        function=FunctionCall(
                            name=name,
                            arguments=json.dumps(arguments),
                        ),
                    )
                ]
            ),
        ),
    )


def _search_answer(
    _arguments: dict[str, Any],
    _context: ExecutionContext,
) -> ToolOutput:
    return ToolOutput(
        status="success",
        answer="SLO was 99.9% [1]",
        content='{"answer":"SLO was 99.9% [1]","evidence":"source [1]"}',
        receipt={"executed_queries": ["slo"]},
        document_ids=["doc-1"],
        citation_mapping={1: "doc-1"},
    )


def _context_with_results(results: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "current_turn_state": {
                "results": results,
                "input": {"task": "answer"},
            }
        }
    )


@pytest.mark.parametrize("model_name", ["gpt-5.6-luna", "gpt-5.6-sol"])
def test_search_model_sends_explicit_none_without_network(monkeypatch, model_name):
    from onyx.agents.v2.llm import create_search_llm

    captured = {}

    class TransportSentinel(RuntimeError):
        pass

    def fake_completion(**kwargs):
        captured.update(kwargs)
        raise TransportSentinel("stop before network")

    monkeypatch.setattr(
        "onyx.llm.litellm_singleton.litellm.completion", fake_completion
    )
    original = ConfigOnlyLLM(
        LLMConfig(
            model_provider="openai",
            model_name="gpt-5-mini",
            api_key="test-key",
            temperature=0,
            max_input_tokens=32000,
            reasoning_effort_default=ReasoningEffort.HIGH,
        )
    )
    search = create_search_llm(original, model_name)
    with pytest.raises(TransportSentinel):
        search.invoke(
            prompt=[],
            reasoning_effort=ReasoningEffort.OFF,
            max_tokens=16384,
            total_timeout_override=5,
        )
    assert captured["model"] == f"openai/responses/{model_name}"
    assert captured["reasoning"]["effort"] == "none"
    assert search.config.max_input_tokens == 32000
    assert original.config.model_name == "gpt-5-mini"
    assert create_search_llm(original, None) is original
