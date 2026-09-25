"""Classify empty and refused assistant responses."""

from unittest.mock import Mock

import pytest

from onyx.chat.errors import (
    _REFUSAL_FINISH_REASONS,
    EmptyLLMResponseError,
    _build_empty_llm_response_error,
)
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import (
    AssistantMessage,
    ThinkingContent,
    ToolChoiceOptions,
)


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

        err = _build_empty_llm_response_error(
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

        err = _build_empty_llm_response_error(
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
        err = _build_empty_llm_response_error(
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

        err = _build_empty_llm_response_error(
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
