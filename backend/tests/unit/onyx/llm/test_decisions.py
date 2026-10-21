import json
from contextlib import closing
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from onyx.llm.decisions.client import DecisionClient
from onyx.llm.decisions.models import (
    ChoiceQuestion,
    DecisionChoice,
    DecisionProvider,
    DecisionRequest,
    PredicateQuestion,
    ScoreLevel,
    ScoreQuestion,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.spans import NoOpSpan
from onyx.tracing.framework.traces import TraceContentMode


@pytest.fixture
def decision_request() -> DecisionRequest:
    return DecisionRequest(
        input="The export failed.",
        questions=[
            PredicateQuestion(name="urgent", instructions="Is this urgent?"),
            ChoiceQuestion(
                name="team",
                instructions="Which team?",
                choices=[
                    DecisionChoice(value="support", description="Product problems"),
                    DecisionChoice(value="billing"),
                ],
            ),
            ScoreQuestion(
                name="severity",
                instructions="How severe?",
                levels=[ScoreLevel(label="Low"), ScoreLevel(label="High")],
            ),
        ],
    )


@pytest.mark.parametrize(
    "provider,url",
    [
        (DecisionProvider.TYPESAFE, "https://api.typesafe.ai/v1/systemone"),
        (DecisionProvider.OPENROUTER, "https://openrouter.ai/api/alpha/decisions"),
    ],
)
def test_system_one_protocol(
    provider: DecisionProvider, url: str, decision_request: DecisionRequest
) -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        assert str(http_request.url) == url
        assert http_request.headers["Authorization"] == "Bearer test-key"
        assert http_request.headers["X-Onyx"] == "test"
        assert json.loads(http_request.content) == {
            "model": "test-model",
            "state": "The export failed.",
            "questions": {
                "urgent": {"type": "noul", "instructions": "Is this urgent?"},
                "team": {
                    "type": "choice",
                    "instructions": "Which team?",
                    "criteria": {"support": "Product problems", "billing": None},
                },
                "severity": {
                    "type": "score",
                    "instructions": "How severe?",
                    "criteria": ["Low", "High"],
                },
            },
        }
        return httpx.Response(
            200,
            json={
                "model": "served-model",
                "answers": {
                    "severity": {
                        "type": "score",
                        "score": 0.7,
                        "confidence": 0.6,
                        "probabilities": {"0": 0.3, "1": 0.7},
                        "legend": {"0": "Low", "1": "High"},
                    },
                    "team": {
                        "type": "choice",
                        "choice": "support",
                        "confidence": 0.8,
                        "probabilities": {"support": 0.9, "billing": 0.1},
                    },
                    "urgent": {"type": "noul", "noul": 0.95},
                },
                "usage": {"input_tokens": 42, "output_tokens": 5},
            },
        )

    with closing(httpx.Client(transport=httpx.MockTransport(handler))) as transport:
        with patch("onyx.llm.decisions.client.httpx.Client", return_value=transport):
            result = DecisionClient(
                provider, "test-model", "test-key", extra_headers={"X-Onyx": "test"}
            ).decide(decision_request, flow=LLMFlow.MODEL_VALIDATION)
    assert result.model_dump() == {
        "model": "served-model",
        "answers": [
            {"type": "predicate", "name": "urgent", "probability": 0.95},
            {
                "type": "choice",
                "name": "team",
                "choice": "support",
                "confidence": 0.8,
                "probabilities": [
                    {"value": "support", "probability": 0.9},
                    {"value": "billing", "probability": 0.1},
                ],
            },
            {
                "type": "score",
                "name": "severity",
                "score": 0.7,
                "confidence": 0.6,
                "probabilities": [
                    {"value": 0, "label": "Low", "probability": 0.3},
                    {"value": 1, "label": "High", "probability": 0.7},
                ],
            },
        ],
        "usage": {"input_tokens": 42, "output_tokens": 5},
    }


@pytest.mark.parametrize(
    "provider,url",
    [
        (DecisionProvider.OPENAI, "https://api.openai.com/v1/decisions"),
    ],
)
def test_array_protocol_preserves_refusals(
    provider: DecisionProvider, url: str, decision_request: DecisionRequest
) -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        assert str(http_request.url) == url
        assert json.loads(http_request.content) == {
            "model": "test-model",
            "input": "The export failed.",
            "questions": [
                {
                    "type": "predicate",
                    "name": "urgent",
                    "instructions": "Is this urgent?",
                },
                {
                    "type": "choice",
                    "name": "team",
                    "instructions": "Which team?",
                    "choices": [
                        {"value": "support", "description": "Product problems"},
                        {"value": "billing"},
                    ],
                },
                {
                    "type": "score",
                    "name": "severity",
                    "instructions": "How severe?",
                    "levels": [{"label": "Low"}, {"label": "High"}],
                },
            ],
        }
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "answers": [
                    {"type": "refusal", "name": "urgent"},
                    {"type": "refusal", "name": "team"},
                    {"type": "refusal", "name": "severity"},
                ],
                "usage": {"input_tokens": 42, "output_tokens": 0},
            },
        )

    with closing(httpx.Client(transport=httpx.MockTransport(handler))) as transport:
        with patch("onyx.llm.decisions.client.httpx.Client", return_value=transport):
            result = DecisionClient(provider, "test-model", "test-key").decide(
                decision_request, flow=LLMFlow.MODEL_VALIDATION
            )
    assert [answer.type for answer in result.answers] == [
        "refusal",
        "refusal",
        "refusal",
    ]
    assert result.usage is not None
    assert result.usage.input_tokens == 42
    assert result.usage.output_tokens == 0


@pytest.mark.parametrize(
    "answers",
    [
        [],
        [{"name": "other", "type": "predicate", "probability": 0.2}],
        [{"name": "urgent", "type": "predicate", "probability": 1.1}],
        [{"name": "urgent", "type": "predicate", "probability": "0.5"}],
        [{"name": "urgent", "type": "predicate", "probability": float("nan")}],
        [
            {"name": "urgent", "type": "predicate", "probability": 0.5},
            {"name": "urgent", "type": "predicate", "probability": 0.5},
        ],
    ],
)
def test_rejects_malformed_results(answers: list[dict[str, object]]) -> None:
    response = httpx.Response(
        200,
        content=json.dumps({"model": "test", "answers": answers}),
        headers={"Content-Type": "application/json"},
    )
    with closing(
        httpx.Client(transport=httpx.MockTransport(lambda _: response))
    ) as transport:
        with patch("onyx.llm.decisions.client.httpx.Client", return_value=transport):
            with pytest.raises(ValueError):
                DecisionClient(DecisionProvider.OPENAI, "test", "test-key").decide(
                    DecisionRequest(
                        input="text",
                        questions=[
                            PredicateQuestion(name="urgent", instructions="Urgent?")
                        ],
                    ),
                    flow=LLMFlow.MODEL_VALIDATION,
                )


def test_rejects_duplicate_question_names() -> None:
    with pytest.raises(ValidationError, match="names must be unique"):
        DecisionRequest(
            input="text",
            questions=[PredicateQuestion(name="same", instructions="Question?")] * 2,
        )


@pytest.mark.parametrize("status", [401, 429, 500])
def test_propagates_http_failure(
    status: int, decision_request: DecisionRequest
) -> None:
    with closing(
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status)))
    ) as transport:
        with patch("onyx.llm.decisions.client.httpx.Client", return_value=transport):
            with pytest.raises(httpx.HTTPStatusError):
                DecisionClient(DecisionProvider.OPENAI, "test", "test-key").decide(
                    decision_request, flow=LLMFlow.MODEL_VALIDATION
                )


def test_propagates_timeout(decision_request: DecisionRequest) -> None:
    with patch("onyx.llm.decisions.client.httpx.Client") as client:
        client.return_value.__enter__.return_value.post.side_effect = httpx.ReadTimeout(
            "timed out"
        )
        with pytest.raises(httpx.ReadTimeout):
            DecisionClient(
                DecisionProvider.OPENAI, "test", "test-key", timeout=7
            ).decide(decision_request, flow=LLMFlow.MODEL_VALIDATION)
        client.assert_called_once_with(timeout=7)


def test_openrouter_custom_base_uses_alpha() -> None:
    client = DecisionClient(
        DecisionProvider.OPENROUTER,
        "test",
        "test-key",
        api_base="https://proxy.example/api/v1/",
    )
    assert client.url == "https://proxy.example/api/alpha/decisions"


@pytest.mark.parametrize(
    "mode", [TraceContentMode.FULL, TraceContentMode.METADATA_ONLY]
)
def test_traces_respect_content_mode(mode: TraceContentMode) -> None:
    span = NoOpSpan(GenerationSpanData(), content_mode=mode)
    response = {
        "model": "served-model",
        "answers": [{"name": "urgent", "type": "predicate", "probability": 0.9}],
        "usage": {"input_tokens": 5, "output_tokens": 0},
    }
    with closing(
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
        )
    ) as transport:
        with (
            patch("onyx.llm.decisions.client.httpx.Client", return_value=transport),
            patch(
                "onyx.tracing.llm_utils.generation_span", return_value=span
            ) as create_span,
        ):
            DecisionClient(DecisionProvider.OPENAI, "test", "test-key").decide(
                DecisionRequest(
                    input="Private text",
                    questions=[
                        PredicateQuestion(name="urgent", instructions="Urgent?")
                    ],
                ),
                flow=LLMFlow.MODEL_VALIDATION,
            )
    assert create_span.call_args.kwargs["model_config"] == {
        "flow": "model_validation",
        "model_provider": "openai",
    }
    assert span.span_data.usage == {"input_tokens": 5, "output_tokens": 0}
    assert span.span_data.routed_model == "served-model"
    if mode == TraceContentMode.METADATA_ONLY:
        assert span.span_data.input is None
        assert span.span_data.output is None
    else:
        assert span.span_data.input is not None
        assert span.span_data.input[0]["input"] == "Private text"
        assert span.span_data.output == [response]


@pytest.mark.parametrize("provider", [DecisionProvider.OPENAI])
def test_array_protocol_returns_distributions(
    provider: DecisionProvider, decision_request: DecisionRequest
) -> None:
    answers = [
        {"name": "urgent", "type": "predicate", "probability": 0.9},
        {
            "name": "team",
            "type": "choice",
            "choice": "support",
            "confidence": 0.8,
            "probabilities": [
                {"value": "support", "probability": 0.9},
                {"value": "billing", "probability": 0.1},
            ],
        },
        {
            "name": "severity",
            "type": "score",
            "score": 0.7,
            "confidence": 0.6,
            "probabilities": [
                {"value": 0, "label": "Low", "probability": 0.3},
                {"value": 1, "label": "High", "probability": 0.7},
            ],
        },
    ]
    with closing(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"model": "test", "answers": answers}
                )
            )
        )
    ) as transport:
        with patch("onyx.llm.decisions.client.httpx.Client", return_value=transport):
            response = DecisionClient(provider, "test", "test-key").decide(
                decision_request, flow=LLMFlow.MODEL_VALIDATION
            )
    assert [answer.model_dump() for answer in response.answers] == answers


@pytest.mark.parametrize(
    "probabilities",
    [
        [
            {"value": "support", "probability": 0.7},
            {"value": "billing", "probability": 0.5},
        ],
        [{"value": "support", "probability": 1.0}],
        [
            {"value": "support", "probability": 0.5},
            {"value": "unknown", "probability": 0.5},
        ],
    ],
)
def test_rejects_invalid_distributions(probabilities: list[dict[str, object]]) -> None:
    with closing(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "model": "test",
                        "answers": [
                            {
                                "name": "team",
                                "type": "choice",
                                "choice": "support",
                                "confidence": 0.8,
                                "probabilities": probabilities,
                            }
                        ],
                    },
                )
            )
        )
    ) as transport:
        with patch("onyx.llm.decisions.client.httpx.Client", return_value=transport):
            with pytest.raises(ValueError):
                DecisionClient(DecisionProvider.OPENAI, "test", "test-key").decide(
                    DecisionRequest(
                        input="text",
                        questions=[
                            ChoiceQuestion(
                                name="team",
                                instructions="Which team?",
                                choices=[
                                    DecisionChoice(value="support"),
                                    DecisionChoice(value="billing"),
                                ],
                            )
                        ],
                    ),
                    flow=LLMFlow.MODEL_VALIDATION,
                )


@pytest.mark.parametrize("legend", [{"0": "Low"}, {"bad": "Low", "1": "High"}])
def test_rejects_malformed_score_legend(legend: dict[str, str]) -> None:
    with closing(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "model": "test",
                        "answers": {
                            "severity": {
                                "type": "score",
                                "score": 0.5,
                                "confidence": 0.5,
                                "probabilities": {"0": 0.5, "1": 0.5},
                                "legend": legend,
                            }
                        },
                    },
                )
            )
        )
    ) as transport:
        with patch("onyx.llm.decisions.client.httpx.Client", return_value=transport):
            with pytest.raises(ValueError, match="legend must match"):
                DecisionClient(DecisionProvider.TYPESAFE, "test", "test-key").decide(
                    DecisionRequest(
                        input="text",
                        questions=[
                            ScoreQuestion(
                                name="severity",
                                instructions="How severe?",
                                levels=[
                                    ScoreLevel(label="Low"),
                                    ScoreLevel(label="High"),
                                ],
                            )
                        ],
                    ),
                    flow=LLMFlow.MODEL_VALIDATION,
                )
