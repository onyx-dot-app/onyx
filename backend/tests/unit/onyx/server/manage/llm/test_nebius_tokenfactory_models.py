"""Tests for the Nebius Token Factory model fetcher.

Verifies the mapping from the provider's /v1/models?verbose response to
Onyx model configs: context length and vision (from architecture.modality).
"""

from typing import cast
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.manage.llm.api import get_nebius_tokenfactory_available_models
from onyx.server.manage.llm.models import NebiusTokenfactoryModelsRequest

# Trimmed real /v1/models?verbose=true payload plus a vision and an embedding
# entry to exercise modality handling and filtering.
_SAMPLE = {
    "object": "list",
    "data": [
        {
            # features present but NO "tools" -> explicitly does not support tools
            "id": "nvidia/Llama-3_1-Nemotron-Ultra-253B-v1",
            "name": "llama-3-1-nemotron-ultra-253b-v1-m",
            "context_length": 8000,
            "architecture": {"modality": "text->text"},
            "supported_features": ["json_mode", "structured_outputs", "reasoning"],
        },
        {
            "id": "meta-llama/Llama-3.3-70B-Instruct",
            "name": "Llama-3.3-70B-Instruct",
            "created": 1781351620,
            "context_length": 131072,
            "architecture": {"modality": "text->text"},
            "quantization": "fp8",
            "regions": [{"country_code": "FI", "name": "eu-north1"}],
            "per_request_limits": {"requests_per_minute": 1200.0},
            "supported_features": ["tools"],
        },
        {
            "id": "Qwen/Qwen3-32B",
            "name": "Qwen3-32B",
            "context_length": 40960,
            "architecture": {"modality": "text->text"},
            "supported_features": ["tools", "json_mode", "reasoning"],
        },
        {
            # vision model (image on the input side)
            "id": "some-vendor/VisionChat",
            "name": "VisionChat",
            "context_length": 32000,
            "architecture": {"modality": "text+image->text"},
            "supported_features": ["tools"],
        },
        {
            # embedding model -> must be dropped
            "id": "BAAI/bge-en-icl",
            "name": "bge-en-icl",
            "context_length": 4096,
            "architecture": {"modality": "text->embedding"},
            "supported_features": [],
        },
    ],
}


def _fetch() -> dict:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value="k"),
        patch(
            "onyx.server.manage.llm.api._get_nebius_tokenfactory_models_response",
            return_value=_SAMPLE,
        ),
    ):
        results = get_nebius_tokenfactory_available_models(
            request=NebiusTokenfactoryModelsRequest(
                api_base="https://api.tokenfactory.nebius.com/v1",
                api_key="k",
                provider_id=None,  # skip DB sync
            ),
            _=cast(User, None),
            db_session=cast(Session, None),
        )
    return {r.name: r for r in results}


def test_embedding_model_is_dropped() -> None:
    by_name = _fetch()
    assert "BAAI/bge-en-icl" not in by_name
    # the four chat/vision models remain
    assert len(by_name) == 4


def test_context_length_mapped() -> None:
    by_name = _fetch()
    assert by_name["meta-llama/Llama-3.3-70B-Instruct"].max_input_tokens == 131072
    assert by_name["nvidia/Llama-3_1-Nemotron-Ultra-253B-v1"].max_input_tokens == 8000


def test_vision_from_modality() -> None:
    by_name = _fetch()
    assert by_name["some-vendor/VisionChat"].supports_image_input is True
    assert by_name["meta-llama/Llama-3.3-70B-Instruct"].supports_image_input is False


def test_reasoning_from_features() -> None:
    by_name = _fetch()
    assert by_name["Qwen/Qwen3-32B"].supports_reasoning is True
    assert by_name["meta-llama/Llama-3.3-70B-Instruct"].supports_reasoning is False


def test_display_metadata_mapped() -> None:
    m = _fetch()["meta-llama/Llama-3.3-70B-Instruct"]
    assert m.quantization == "fp8"
    assert m.country_code == "FI"
    assert m.requests_per_minute == 1200.0
    assert m.supported_features == ["tools"]
