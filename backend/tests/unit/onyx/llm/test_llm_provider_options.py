from datetime import datetime
from datetime import timezone

import pytest

from onyx.llm.well_known_providers.auto_update_models import (
    LLMProviderRecommendation,
)
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.llm.well_known_providers.constants import OPENAI_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import VERTEXAI_PROVIDER_NAME
from onyx.llm.well_known_providers.llm_provider_options import (
    model_configurations_for_provider,
)
from onyx.llm.well_known_providers.models import SimpleKnownModel


def _build_recommendations(
    provider_name: str, visible_model_names: list[str]
) -> LLMRecommendations:
    return LLMRecommendations(
        version="test",
        updated_at=datetime.now(timezone.utc),
        providers={
            provider_name: LLMProviderRecommendation(
                default_model=SimpleKnownModel(name=visible_model_names[0]),
                additional_visible_models=[
                    SimpleKnownModel(name=model_name)
                    for model_name in visible_model_names[1:]
                ],
            )
        },
    )


def test_model_configurations_vertex_are_sorted_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.llm.well_known_providers.llm_provider_options.fetch_models_for_provider",
        lambda _provider_name: ["zeta-model", "alpha-model", "Beta-model"],
    )
    monkeypatch.setattr(
        "onyx.llm.well_known_providers.llm_provider_options.get_max_input_tokens",
        lambda _model_name, _provider_name: None,
    )
    monkeypatch.setattr(
        "onyx.llm.well_known_providers.llm_provider_options.model_supports_image_input",
        lambda _model_name, _provider_name: False,
    )

    recommendations = _build_recommendations(
        VERTEXAI_PROVIDER_NAME, ["gamma-model", "alpha-model"]
    )

    model_configurations = model_configurations_for_provider(
        VERTEXAI_PROVIDER_NAME, recommendations
    )

    assert [model.name for model in model_configurations] == [
        "alpha-model",
        "Beta-model",
        "gamma-model",
        "zeta-model",
    ]
    assert [model.is_visible for model in model_configurations] == [
        True,
        False,
        True,
        False,
    ]


def test_model_configurations_non_vertex_preserve_provider_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.llm.well_known_providers.llm_provider_options.fetch_models_for_provider",
        lambda _provider_name: ["model-b", "model-a"],
    )
    monkeypatch.setattr(
        "onyx.llm.well_known_providers.llm_provider_options.get_max_input_tokens",
        lambda _model_name, _provider_name: None,
    )
    monkeypatch.setattr(
        "onyx.llm.well_known_providers.llm_provider_options.model_supports_image_input",
        lambda _model_name, _provider_name: False,
    )

    recommendations = _build_recommendations(
        OPENAI_PROVIDER_NAME, ["model-c", "model-a"]
    )

    model_configurations = model_configurations_for_provider(
        OPENAI_PROVIDER_NAME, recommendations
    )

    assert [model.name for model in model_configurations] == [
        "model-b",
        "model-a",
        "model-c",
    ]
