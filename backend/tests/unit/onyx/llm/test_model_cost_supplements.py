"""
Tests for the model-cost supplements bridge
(onyx/llm/litellm_singleton/model_cost_supplements.json).

Supplements carry registry entries that are merged upstream in LiteLLM but
not shipped in the version Onyx pins — currently the Azure GPT-5.6 models
from https://github.com/BerriAI/litellm/pull/32678. They guarantee that
Azure GPT-5.6 deployments get capability metadata (reasoning/vision) and
Azure pricing (https://github.com/onyx-dot-app/onyx/issues/12847).

Once a LiteLLM upgrade ships these entries, the supplement entries can be
deleted; these tests must keep passing off the bundled registry alone.
"""

import litellm
import pytest

from onyx.llm.constants import LlmProviderNames
from onyx.llm.utils import find_model_obj
from onyx.llm.utils import get_model_map
from onyx.llm.utils import litellm_thinks_model_supports_image_input
from onyx.llm.utils import model_is_reasoning_model

GPT_5_6_MODEL_NAMES = ["gpt-5.6", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]


@pytest.fixture(autouse=True)
def clear_model_map_cache() -> None:
    get_model_map.cache_clear()


@pytest.mark.parametrize("model_name", GPT_5_6_MODEL_NAMES)
def test_azure_gpt_5_6_entry_has_capabilities(model_name: str) -> None:
    model_map = get_model_map()
    entry = model_map[f"azure/{model_name}"]
    assert entry["litellm_provider"] == LlmProviderNames.AZURE
    assert entry["supports_reasoning"] is True
    assert entry["supports_vision"] is True
    assert entry["max_input_tokens"] == 1050000
    assert "/v1/responses" in entry["supported_endpoints"]


@pytest.mark.parametrize("model_name", GPT_5_6_MODEL_NAMES)
def test_azure_gpt_5_6_capability_detection(model_name: str) -> None:
    assert model_is_reasoning_model(model_name, LlmProviderNames.AZURE) is True
    assert (
        litellm_thinks_model_supports_image_input(model_name, LlmProviderNames.AZURE)
        is True
    )


@pytest.mark.parametrize("model_name", GPT_5_6_MODEL_NAMES)
def test_azure_gpt_5_6_resolves_to_azure_entry(model_name: str) -> None:
    """Azure lookups must hit the azure/ entry (Azure pricing), not fall back
    to the bare OpenAI entry."""
    model_obj = find_model_obj(get_model_map(), LlmProviderNames.AZURE, model_name)
    assert model_obj is not None
    assert model_obj["litellm_provider"] == LlmProviderNames.AZURE


def test_supplements_do_not_override_bundled_entries() -> None:
    """The bare gpt-5.6* entries ship with the pinned LiteLLM as OpenAI-provider
    entries; supplements must never clobber existing registry entries."""
    for model_name in GPT_5_6_MODEL_NAMES:
        assert (
            litellm.model_cost[model_name]["litellm_provider"]
            == LlmProviderNames.OPENAI
        )
