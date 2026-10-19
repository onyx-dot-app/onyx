"""Tests for the Vercel AI Gateway model fetcher.

The gateway's catalog is public and carries richer metadata than LiteLLM's
static map, so every field comes from the catalog. These tests verify the
mapping: non-language entries dropped, context window and modalities mapped,
id-less entries skipped, and results sorted by name.
"""

from typing import cast
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm.api import (
    _get_vercel_ai_gateway_decision_models,
    get_vercel_ai_gateway_available_models,
)
from onyx.server.manage.llm.models import (
    VercelAIGatewayFinalModelResponse,
    VercelAIGatewayModelsRequest,
)

# Trimmed catalog payload: chat models, a decision-only model, and entries
# outside the model surfaces Onyx supports.
_SAMPLE = {
    "object": "list",
    "data": [
        {
            "id": "anthropic/claude-sonnet-4.5",
            "name": "Claude Sonnet 4.5",
            "type": "language",
            "context_window": 1000000,
            "modalities": {"input": ["text", "image"], "output": ["text"]},
            "supported_parameters": ["tools", "reasoning"],
        },
        {
            "id": "alibaba/qwen-3-14b",
            "name": "Qwen3-14B",
            "type": "language",
            "context_window": 40960,
            "modalities": {"input": ["text"], "output": ["text"]},
            "supported_parameters": ["tools"],
        },
        {
            "id": "openai/gpt-6-luna-decisions",
            "name": "GPT-6 Luna Decisions",
            "type": "evaluation",
            "context_window": 1050000,
            "modalities": {"input": ["text", "image"], "output": ["text"]},
        },
        {
            "id": "openai/text-embedding-3-large",
            "name": "Embedding",
            "type": "embedding",
            "context_window": 8191,
        },
        {"id": "openai/sora", "name": "Sora", "type": "video_generation"},
        {"id": "", "name": "no id", "type": "language"},
    ],
}


def _fetch(payload: dict = _SAMPLE) -> list[VercelAIGatewayFinalModelResponse]:
    with patch(
        "onyx.server.manage.llm.api._get_openai_compatible_models_response",
        return_value=payload,
    ):
        return get_vercel_ai_gateway_available_models(
            request=VercelAIGatewayModelsRequest(provider_id=None),
            _=cast(User, None),
            db_session=cast(Session, None),
        )


def test_language_and_decision_models_are_returned() -> None:
    names = [m.name for m in _fetch()]
    assert names == [
        "alibaba/qwen-3-14b",
        "anthropic/claude-sonnet-4.5",
        "openai/gpt-6-luna-decisions",
    ]


def test_evaluation_models_are_decision_only() -> None:
    model = next(m for m in _fetch() if m.name == "openai/gpt-6-luna-decisions")
    assert model.supports_chat is False
    assert model.supports_decisions is True
    assert model.supports_image_input is True


def test_catalog_metadata_maps_onto_the_model_config() -> None:
    claude = next(m for m in _fetch() if m.name == "anthropic/claude-sonnet-4.5")
    assert claude.display_name == "Claude Sonnet 4.5"
    assert claude.max_input_tokens == 1000000
    assert claude.supports_image_input is True
    assert claude.supports_reasoning is True


def test_text_only_model_reports_no_image_or_reasoning_support() -> None:
    qwen = next(m for m in _fetch() if m.name == "alibaba/qwen-3-14b")
    assert qwen.supports_image_input is False
    assert qwen.supports_reasoning is False


def test_missing_modality_and_parameter_fields_default_to_false() -> None:
    sparse = {"data": [{"id": "vendor/model", "name": "Model", "type": "language"}]}
    model = _fetch(sparse)[0]
    assert model.supports_image_input is False
    assert model.supports_reasoning is False
    assert model.max_input_tokens is None


def test_empty_catalog_raises() -> None:
    with pytest.raises(OnyxError):
        _fetch({"object": "list", "data": []})


def test_catalog_without_language_models_raises() -> None:
    with pytest.raises(OnyxError):
        _fetch({"data": [{"id": "openai/sora", "type": "video_generation"}]})


def test_catalog_with_only_decision_models_is_valid() -> None:
    models = _fetch({"data": [{"id": "typesafe-ai/jev", "type": "evaluation"}]})
    assert [(model.name, model.supports_decisions) for model in models] == [
        ("typesafe-ai/jev", True)
    ]


def test_gateway_evaluation_models_are_verified_before_provider_save() -> None:
    payload = {
        "data": [
            {"id": "openai/gpt-6-luna-decisions", "type": "evaluation"},
            {"id": "openai/gpt-6-luna", "type": "language"},
        ]
    }
    with (
        patch(
            "onyx.server.manage.llm.api._get_openai_compatible_models_response",
            return_value=payload,
        ) as get_models,
        patch(
            "onyx.server.manage.llm.api._resolve_api_key", return_value="gateway-key"
        ),
    ):
        models = _get_vercel_ai_gateway_decision_models(
            api_base="https://gateway.example/v1",
            api_key=None,
            provider_id=4,
            db_session=cast(Session, None),
        )

    assert models == {"openai/gpt-6-luna-decisions": False}
    assert get_models.call_args.kwargs == {
        "url": "https://gateway.example/v1/models",
        "source_name": "Vercel AI Gateway",
        "api_key": "gateway-key",
    }
