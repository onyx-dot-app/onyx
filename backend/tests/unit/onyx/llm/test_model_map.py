from unittest.mock import patch

from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.llm import model_catalog
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_capabilities import (
    find_model_obj,
    get_model_map,
    model_is_reasoning_model,
)


def _fresh_model_map() -> dict:
    model_catalog.build_model_map.cache_clear()
    get_model_map.cache_clear()
    return get_model_map()


def _reset_caches() -> None:
    model_catalog.build_model_map.cache_clear()
    get_model_map.cache_clear()


def test_partial_match_in_model_map() -> None:
    """
    We should handle adding/not adding the provider prefix to the model name.
    """
    model_map = _fresh_model_map()
    try:
        _EXPECTED_FIELDS = {
            "max_input_tokens": 128000,
            "max_output_tokens": 16384,
            "max_tokens": 128000,
            "supports_function_calling": True,
            "supports_reasoning": False,
            "supports_response_schema": True,
            "supports_vision": True,
            "litellm_provider": "openai",
        }

        # ollama_chat carries no gpt-4o, so both names resolve through the
        # bare-key pass: "openai/gpt-4o" as a provider-scoped key, then
        # "gpt-4o" as a bare key owned by openai.
        result1 = find_model_obj(
            model_map, LlmProviderNames.OLLAMA_CHAT, "openai/gpt-4o"
        )
        assert result1 is not None
        for key, value in _EXPECTED_FIELDS.items():
            assert key in result1
            assert result1[key] == value, "Unexpected value for key: {}".format(key)

        result2 = find_model_obj(model_map, LlmProviderNames.OLLAMA_CHAT, "gpt-4o")
        assert result2 is not None
        for key, value in _EXPECTED_FIELDS.items():
            assert key in result2
            assert result2[key] == value, "Unexpected value for key: {}".format(key)
    finally:
        _reset_caches()


def test_bare_key_prefers_canonical_owner() -> None:
    """A bare model id shared by several provider sections resolves to the
    canonical owner's entry, while provider-scoped keys stay separate."""
    mock_catalog = {
        "openai": {
            "models": {
                "gpt-4o": {
                    "name": "GPT-4o",
                    "reasoning": False,
                    "limit": {"context": 128000},
                }
            },
            "aliases": {},
        },
        "azure": {
            "models": {
                "gpt-4o": {
                    "name": "GPT-4o",
                    "reasoning": True,
                    "limit": {"context": 999},
                }
            },
            "aliases": {},
        },
    }

    with patch.object(model_catalog, "_catalog", return_value=mock_catalog):
        model_map = _fresh_model_map()
        try:
            bare = find_model_obj(model_map, "custom_provider", "gpt-4o")
            assert bare is not None
            assert bare["litellm_provider"] == "openai"
            assert bare["max_tokens"] == 128000

            scoped = find_model_obj(model_map, LlmProviderNames.AZURE, "gpt-4o")
            assert scoped is not None
            assert scoped["litellm_provider"] == "azure"
            assert scoped["max_tokens"] == 999
        finally:
            _reset_caches()


def test_model_is_reasoning_model_handles_none_in_model_map() -> None:
    """Regression: a catalog entry may carry supports_reasoning=None.
    model_is_reasoning_model must always return a bool, never None."""
    mock_catalog = {
        "openai": {
            "models": {
                "gpt-4o": {"reasoning": None},
                "o3": {"reasoning": True},
                "gpt-4o-mini": {},
            },
            "aliases": {},
        },
    }

    with (
        patch.object(model_catalog, "_catalog", return_value=mock_catalog),
        patch(
            "onyx.llm.model_capabilities._probe_supports_reasoning",
            return_value=False,
        ),
    ):
        _fresh_model_map()
        try:
            # None in map — should fall through to the probe
            assert model_is_reasoning_model("gpt-4o", "openai") is False

            # True in map — should return True without probing
            assert model_is_reasoning_model("o3", "openai") is True

            # Missing key — should fall through to the probe
            assert model_is_reasoning_model("gpt-4o-mini", "openai") is False
        finally:
            _reset_caches()


def test_twelvelabs_pegasus_override_present() -> None:
    model_map = _fresh_model_map()
    try:
        model_obj = find_model_obj(
            model_map,
            "twelvelabs",
            "us.twelvelabs.pegasus-1-2-v1:0",
        )
        assert model_obj is not None
        assert model_obj["max_input_tokens"] == GEN_AI_MODEL_FALLBACK_MAX_TOKENS
        assert model_obj["max_tokens"] == GEN_AI_MODEL_FALLBACK_MAX_TOKENS
        assert model_obj["supports_reasoning"] is False
    finally:
        _reset_caches()
