"""Tests for the Inworld Router model fetcher.

Inworld lists models at `/llm/v1alpha/models` (camelCase protobuf JSON under
`models`), not at the OpenAI `/v1/models` path. These tests pin the mapping
from that catalog to Onyx model configs.
"""

from typing import Any, cast
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm.api import (
    _get_inworld_models_response,
    _inworld_models_url,
    get_inworld_available_models,
)
from onyx.server.manage.llm.models import InworldModelsRequest

_SAMPLE: dict[str, Any] = {
    "models": [
        {
            "model": "gpt-5.4",
            "provider": "openai",
            "modelCreator": "openai",
            "spec": {
                "inputModalities": ["text", "image"],
                "outputModalities": ["text"],
                "contextLength": 400000,
                "capabilities": {
                    "functionCalling": True,
                    "vision": True,
                    "reasoningCapability": {
                        "supported": True,
                        "supportedLevels": ["low", "medium", "high"],
                    },
                },
            },
            "isSupported": True,
        },
        {
            "model": "models/inworld-llm-small",
            "provider": "inworld",
            "spec": {
                "inputModalities": ["text"],
                "outputModalities": ["text"],
                "contextLength": 32768,
                "capabilities": {"functionCalling": True},
            },
            "isSupported": True,
        },
        {
            # No spec: metadata falls back to defaults.
            "model": "deepseek-v4-flash",
            "provider": "deepseek",
            "isSupported": True,
        },
        {
            # Image generation -> not a chat model.
            "model": "gpt-image-2",
            "provider": "openai",
            "spec": {
                "inputModalities": ["text"],
                "outputModalities": ["image"],
            },
            "isSupported": True,
        },
        {
            # Embedding model -> dropped by name.
            "model": "text-embedding-3-large",
            "provider": "openai",
            "spec": {"outputModalities": ["text"]},
            "isSupported": True,
        },
        {
            # Malformed entry without a provider.
            "model": "orphan",
        },
    ]
}


def _fetch(sample: dict[str, Any] | None = None) -> dict:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value="k"),
        patch(
            "onyx.server.manage.llm.api._get_inworld_models_response",
            return_value=_SAMPLE if sample is None else sample,
        ),
    ):
        results = get_inworld_available_models(
            request=InworldModelsRequest(
                api_base="https://api.inworld.ai/v1",
                api_key="k",
                provider_id=None,  # skip DB sync
            ),
            _=cast(User, None),
            db_session=cast(Session, None),
        )
    return {r.name: r for r in results}


def test_model_id_is_provider_slash_model() -> None:
    by_name = _fetch()
    assert "openai/gpt-5.4" in by_name
    assert "inworld/models/inworld-llm-small" in by_name
    assert "deepseek/deepseek-v4-flash" in by_name


def test_non_chat_and_malformed_models_are_dropped() -> None:
    by_name = _fetch()
    assert "openai/gpt-image-2" not in by_name
    assert "openai/text-embedding-3-large" not in by_name
    assert not any(name.endswith("orphan") for name in by_name)


def test_auto_router_is_listed_as_router() -> None:
    by_name = _fetch()
    auto = by_name["auto"]
    assert auto.is_router is True
    assert auto.max_input_tokens is None
    assert all(not r.is_router for name, r in by_name.items() if name != "auto")


def test_context_length_mapped() -> None:
    by_name = _fetch()
    assert by_name["openai/gpt-5.4"].max_input_tokens == 400000
    assert by_name["inworld/models/inworld-llm-small"].max_input_tokens == 32768
    assert by_name["deepseek/deepseek-v4-flash"].max_input_tokens is None


def test_vision_from_capabilities_and_modalities() -> None:
    by_name = _fetch()
    assert by_name["openai/gpt-5.4"].supports_image_input is True
    assert by_name["inworld/models/inworld-llm-small"].supports_image_input is False


def test_vision_from_input_modalities_alone() -> None:
    by_name = _fetch(
        {
            "models": [
                {
                    "model": "gemini-3-flash",
                    "provider": "google",
                    "spec": {
                        "inputModalities": ["text", "image"],
                        "outputModalities": ["text"],
                    },
                }
            ]
        }
    )
    assert by_name["google/gemini-3-flash"].supports_image_input is True


def test_reasoning_from_reasoning_capability() -> None:
    by_name = _fetch()
    assert by_name["openai/gpt-5.4"].supports_reasoning is True
    assert by_name["inworld/models/inworld-llm-small"].supports_reasoning is False


def test_display_name_drops_inworld_models_prefix() -> None:
    by_name = _fetch()
    assert by_name["openai/gpt-5.4"].display_name == "gpt-5.4"
    assert by_name["inworld/models/inworld-llm-small"].display_name == (
        "inworld-llm-small"
    )


def test_results_sorted_with_auto_first() -> None:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value="k"),
        patch(
            "onyx.server.manage.llm.api._get_inworld_models_response",
            return_value=_SAMPLE,
        ),
    ):
        results = get_inworld_available_models(
            request=InworldModelsRequest(
                api_base="https://api.inworld.ai/v1", api_key="k"
            ),
            _=cast(User, None),
            db_session=cast(Session, None),
        )
    names = [r.name for r in results]
    assert names[0] == "auto"
    assert names[1:] == sorted(names[1:], key=str.lower)


def test_empty_catalog_raises() -> None:
    with pytest.raises(OnyxError):
        _fetch({"models": []})


def test_catalog_with_only_non_chat_models_raises() -> None:
    with pytest.raises(OnyxError):
        _fetch(
            {
                "models": [
                    {
                        "model": "gpt-image-2",
                        "provider": "openai",
                        "spec": {"outputModalities": ["image"]},
                    }
                ]
            }
        )


@pytest.mark.parametrize(
    "api_base",
    [
        "https://api.inworld.ai/v1",
        "https://api.inworld.ai/v1/",
        "https://api.inworld.ai",
        " https://api.inworld.ai/ ",
    ],
)
def test_models_url_is_derived_from_the_api_host(api_base: str) -> None:
    assert _inworld_models_url(api_base) == "https://api.inworld.ai/llm/v1alpha/models"


def test_models_url_keeps_custom_host() -> None:
    assert (
        _inworld_models_url("https://api.example.test:8443/v1")
        == "https://api.example.test:8443/llm/v1alpha/models"
    )


def test_models_request_uses_basic_auth() -> None:
    with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
        mock_get.return_value.json.return_value = {"models": []}
        _get_inworld_models_response("https://api.inworld.ai/v1", "aW53b3JsZA==")

    assert mock_get.call_args.args[0] == "https://api.inworld.ai/llm/v1alpha/models"
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Basic aW53b3JsZA=="


def test_models_request_without_key_sends_no_authorization() -> None:
    with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
        mock_get.return_value.json.return_value = {"models": []}
        _get_inworld_models_response("https://api.inworld.ai/v1", None)

    assert "Authorization" not in mock_get.call_args.kwargs["headers"]
