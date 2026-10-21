"""Tests for the Atlas Cloud model fetcher.

The gateway's catalog is public and carries richer metadata than LiteLLM's
static map, so every field comes from the catalog. These tests verify the
mapping: non-text-output entries dropped, context length and modalities
mapped, id-less entries skipped, and results sorted by name.
"""

from typing import cast
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm.api import get_atlascloud_available_models
from onyx.server.manage.llm.models import (
    AtlasCloudFinalModelResponse,
    AtlasCloudModelsRequest,
)

# Trimmed catalog payload shaped like the live one. The live OpenAI-compatible
# catalog lists language models only, so the image-generation entry here guards
# the output-modality filter rather than mirroring something it returns today.
_SAMPLE = {
    "object": "list",
    "data": [
        {
            "id": "deepseek-ai/DeepSeek-V3.1-Terminus",
            "name": "DeepSeek V3.1 Terminus",
            "context_length": 131072,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "supported_features": ["json_mode", "tools", "reasoning"],
        },
        {
            "id": "Qwen/Qwen3-235B-A22B-Instruct-2507",
            "name": "Qwen3-235B-A22B-Instruct-2507",
            "context_length": 131072,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "supported_features": ["json_mode", "tools"],
        },
        {
            "id": "black-forest-labs/FLUX.1-dev",
            "name": "FLUX.1 dev",
            "input_modalities": ["text"],
            "output_modalities": ["image"],
        },
        {"id": "", "name": "no id"},
    ],
}


def _fetch(payload: dict = _SAMPLE) -> list[AtlasCloudFinalModelResponse]:
    with patch(
        "onyx.server.manage.llm.api._get_openai_compatible_models_response",
        return_value=payload,
    ):
        return get_atlascloud_available_models(
            request=AtlasCloudModelsRequest(provider_id=None),
            _=cast(User, None),
            db_session=cast(Session, None),
        )


def test_only_text_output_models_are_returned() -> None:
    names = [m.name for m in _fetch()]
    assert names == [
        "deepseek-ai/DeepSeek-V3.1-Terminus",
        "Qwen/Qwen3-235B-A22B-Instruct-2507",
    ]


def test_catalog_metadata_maps_onto_the_model_config() -> None:
    deepseek = next(
        m for m in _fetch() if m.name == "deepseek-ai/DeepSeek-V3.1-Terminus"
    )
    assert deepseek.display_name == "DeepSeek V3.1 Terminus"
    assert deepseek.max_input_tokens == 131072
    assert deepseek.supports_reasoning is True
    assert deepseek.supports_image_input is False


def test_model_without_reasoning_feature_reports_no_reasoning_support() -> None:
    qwen = next(
        m for m in _fetch() if m.name == "Qwen/Qwen3-235B-A22B-Instruct-2507"
    )
    assert qwen.supports_reasoning is False
    assert qwen.supports_image_input is False


def test_image_input_modality_is_mapped() -> None:
    vision = {
        "data": [
            {
                "id": "vendor/vision-model",
                "name": "Vision Model",
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
                "supported_features": [],
            }
        ]
    }
    assert _fetch(vision)[0].supports_image_input is True


def test_missing_modality_and_feature_fields_default_to_false() -> None:
    sparse = {"data": [{"id": "vendor/model", "name": "Model"}]}
    model = _fetch(sparse)[0]
    assert model.supports_image_input is False
    assert model.supports_reasoning is False
    assert model.max_input_tokens is None


def test_display_name_falls_back_to_the_model_id() -> None:
    unnamed = {"data": [{"id": "vendor/model", "output_modalities": ["text"]}]}
    assert _fetch(unnamed)[0].display_name == "vendor/model"


def test_empty_catalog_raises() -> None:
    with pytest.raises(OnyxError):
        _fetch({"object": "list", "data": []})


def test_catalog_without_text_models_raises() -> None:
    with pytest.raises(OnyxError):
        _fetch(
            {
                "data": [
                    {"id": "vendor/img", "output_modalities": ["image"]},
                ]
            }
        )
