"""Native request retries preserve required fields and tracing."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings

from onyx.llm.exceptions import LLMRateLimitError
from onyx.llm.interfaces import LLMConfig
from onyx.llm.provider_model import ProviderModel, settings_after_rejection
from onyx.tracing.framework.create import generation_span, trace


def make_model() -> ProviderModel:
    return ProviderModel(
        TestModel(),
        LLMConfig(
            model_provider="openai",
            model_name="gpt-5-mini",
            temperature=0.3,
            max_input_tokens=10000,
        ),
    )


@pytest.mark.parametrize(
    "body",
    [
        "invalid schema",
        "invalid tool arguments",
        "context length exceeded",
        "authentication failed",
    ],
)
def test_non_tuning_errors_are_not_retried(body: str) -> None:
    assert (
        settings_after_rejection(
            ModelSettings(thinking="high", temperature=0.2),
            ModelHTTPError(400, "model", body),
        )
        is None
    )


def test_rejected_reasoning_keeps_policy_and_tools() -> None:
    settings: Any = {
        "thinking": "high",
        "temperature": 0.2,
        "openai_store": False,
        "tool_choice": ["search"],
        "extra_headers": {"retention": "none"},
    }
    result = settings_after_rejection(
        settings, ModelHTTPError(400, "model", "thinking not supported")
    )
    assert result == {
        key: value for key, value in settings.items() if key != "thinking"
    }


def test_required_reasoning_none_is_retained() -> None:
    settings = settings_after_rejection(
        ModelSettings(thinking="high"),
        ModelHTTPError(400, "model", "set reasoning_effort to 'none'"),
    )
    assert settings == {"openai_reasoning_effort": "none"}


@pytest.mark.asyncio
async def test_retry_records_successful_attempt_and_keeps_tool_schema() -> None:
    model = make_model()
    params = ModelRequestParameters()
    expected = ModelResponse(parts=[TextPart("answer")])
    mock = AsyncMock(
        side_effect=[ModelHTTPError(400, "model", "thinking unsupported"), expected]
    )
    with (
        patch.object(model.wrapped, "request", mock),
        trace("test"),
        generation_span(model="model") as span,
    ):
        result = await model.request(
            [], ModelSettings(thinking="high", temperature=0.3), params
        )
    assert result is expected
    assert mock.await_count == 2
    assert mock.await_args is not None
    assert mock.await_args.args[2] is params
    assert span.span_data.request_params
    assert "thinking" not in span.span_data.request_params["sent_kwargs"]


@pytest.mark.asyncio
async def test_rate_limit_keeps_public_exception_contract() -> None:
    model = make_model()
    with patch.object(
        model.wrapped,
        "request",
        AsyncMock(side_effect=ModelHTTPError(429, "model", "limit")),
    ):
        with pytest.raises(LLMRateLimitError):
            await model.request([], ModelSettings(), ModelRequestParameters())


def test_rejected_thinking_removes_provider_extensions_only() -> None:
    settings: Any = {
        "thinking": "high",
        "openai_reasoning_summary": "auto",
        "bedrock_additional_model_requests_fields": {
            "thinking": {"type": "enabled", "budget_tokens": 1024},
            "top_k": 10,
        },
        "extra_headers": {"retention": "none"},
    }
    updated = settings_after_rejection(
        settings, ModelHTTPError(400, "model", "thinking is unsupported")
    )
    assert updated == {
        "bedrock_additional_model_requests_fields": {"top_k": 10},
        "extra_headers": {"retention": "none"},
    }
    assert settings["bedrock_additional_model_requests_fields"]["thinking"]


def test_rejected_temperature_keeps_enabled_thinking() -> None:
    settings: Any = {
        "temperature": 0.2,
        "thinking": "low",
        "anthropic_thinking": {"type": "enabled", "budget_tokens": 1024},
    }
    updated = settings_after_rejection(
        settings,
        ModelHTTPError(
            400,
            "claude-haiku-4-5",
            "temperature may only be set to 1 when thinking is enabled",
        ),
    )
    assert updated == {
        key: value for key, value in settings.items() if key != "temperature"
    }
