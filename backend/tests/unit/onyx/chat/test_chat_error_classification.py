"""Classify empty and refused assistant responses."""

from unittest.mock import Mock

import pytest

from onyx.agents.models import RunState, StepResult
from onyx.agents.runtime import Agent, RunFailed
from onyx.chat.errors import (
    _REFUSAL_FINISH_REASONS,
    EmptyLLMResponseError,
    build_empty_llm_response_error,
    chat_error,
)
from onyx.llm.interfaces import GenerationContext, LLMConfig
from onyx.llm.models import (
    AssistantMessage,
    ThinkingContent,
    ToolChoiceOptions,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient


class TestEmptyLlmResponseClassification:
    def _make_llm(self, provider: str = "openai", model: str = "gpt-5.2") -> Mock:
        llm = Mock()
        llm.config = LLMConfig(
            model_provider=provider,
            model_name=model,
            temperature=0.0,
            max_input_tokens=4096,
        )
        return llm

    def test_openai_empty_stream_is_classified_as_budget_exceeded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("onyx.chat.errors.is_true_openai_model", lambda *_: True)

        err = build_empty_llm_response_error(
            llm=self._make_llm(),
            message=AssistantMessage(),
            tool_choice=ToolChoiceOptions.AUTO,
        )

        assert isinstance(err, EmptyLLMResponseError)
        assert err.error_code == "BUDGET_EXCEEDED"
        assert err.is_retryable is False
        assert "quota" in err.client_error_msg.lower()

    def test_reasoning_only_response_uses_generic_empty_response_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("onyx.chat.errors.is_true_openai_model", lambda *_: True)

        err = build_empty_llm_response_error(
            llm=self._make_llm(),
            message=AssistantMessage(
                content=[ThinkingContent(text="scratchpad only")],
            ),
            tool_choice=ToolChoiceOptions.AUTO,
        )

        assert isinstance(err, EmptyLLMResponseError)
        assert err.error_code == "EMPTY_LLM_RESPONSE"
        assert err.is_retryable is True
        assert "quota" not in err.client_error_msg.lower()

    def test_refusal_finish_reason_is_classified_as_model_refusal(self) -> None:
        """Anthropic refusal: HTTP 200, stop_reason="refusal" (normalized by
        LiteLLM to "content_filter"), no text or tool calls. Must surface as a
        refusal, not a generic empty-stream error."""
        err = build_empty_llm_response_error(
            llm=self._make_llm(provider="anthropic", model="claude-fable-5"),
            message=AssistantMessage(
                stop_reason="content_filter",
            ),
            tool_choice=ToolChoiceOptions.AUTO,
        )

        assert isinstance(err, EmptyLLMResponseError)
        assert err.error_code == "MODEL_REFUSAL"
        assert err.is_retryable is False
        assert err.finish_reason == "content_filter"
        assert "declined" in err.client_error_msg.lower()
        # Anthropic-specific fallback suggestion from the issue.
        assert "Claude Opus 4.8" in err.client_error_msg

    @pytest.mark.parametrize("finish_reason", sorted(_REFUSAL_FINISH_REASONS))
    def test_refusal_finish_reasons_take_precedence_over_budget_heuristic(
        self, monkeypatch: pytest.MonkeyPatch, finish_reason: str
    ) -> None:
        """Native provider refusal reasons may pass through gateways unchanged."""
        monkeypatch.setattr("onyx.chat.errors.is_true_openai_model", lambda *_: True)

        err = build_empty_llm_response_error(
            llm=self._make_llm(),
            message=AssistantMessage(
                stop_reason=finish_reason,
            ),
            tool_choice=ToolChoiceOptions.AUTO,
        )

        assert err.error_code == "MODEL_REFUSAL"
        assert err.is_retryable is False
        assert err.finish_reason == finish_reason
        assert "Claude Opus 4.8" not in err.client_error_msg


def test_empty_response_diagnostics_survive_saved_run_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.chat.errors.DEV_MODE", False)
    monkeypatch.setattr("onyx.agents.runtime.logger.exception", lambda *_: None)
    llm = FakeModelClient(lambda *_: AssistantMessage(stop_reason="length"))
    monkeypatch.setattr(
        llm,
        "redact_error",
        lambda text: text.replace("test-private-value", "[REDACTED]"),
    )
    error = EmptyLLMResponseError(
        provider=llm.config.model_provider,
        model=llm.config.model_name,
        tool_choice=ToolChoiceOptions.REQUIRED,
        client_error_msg="Empty response test-private-value",
        finish_reason="length",
    )

    def reject_empty_response(_result: StepResult) -> bool:
        raise error from RuntimeError("raw-provider-detail")

    run = Agent(
        llm,
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        after_step=reject_empty_response,
    ).start(max_steps=1)
    with pytest.raises(RunFailed):
        run.result(timeout=2)
    assert run.wait_for_idle(2)
    serialized = run.snapshot().model_dump_json()
    assert "test-private-value" not in serialized
    assert "raw-provider-detail" not in serialized
    restored = RunState.model_validate_json(serialized)
    assert restored.failure is not None
    packet = chat_error(RunFailed(restored.failure), llm, model_index=1)
    assert packet == chat_error(error, llm, model_index=1)
    assert packet.error_code == "EMPTY_LLM_RESPONSE"
    assert packet.error == "Empty response [REDACTED]"
    assert packet.details == {
        "model": "test-model",
        "provider": "openai",
        "model_index": 1,
        "tool_choice": "required",
        "finish_reason": "length",
    }
    assert packet.stack_trace is None
