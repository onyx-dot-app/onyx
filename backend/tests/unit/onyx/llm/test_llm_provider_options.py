from datetime import datetime, timezone

import pytest

from onyx.llm.well_known_providers.auto_update_models import (
    LLMProviderRecommendation,
    LLMRecommendations,
)
from onyx.llm.well_known_providers.constants import (
    OCI_PROVIDER_NAME,
    OPENAI_PROVIDER_NAME,
    VERTEXAI_PROVIDER_NAME,
)
from onyx.llm.well_known_providers.llm_provider_options import (
    get_oci_model_names,
    model_configurations_for_provider,
)
from onyx.llm.well_known_providers.models import SimpleKnownModel


def test_get_visible_models_dedupes_default_and_prefers_display_name() -> None:
    # The default is repeated in additional_visible_models (where it carries a
    # display name); get_visible_models must return it once, with the name.
    recommendations = LLMRecommendations(
        version="test",
        updated_at=datetime.now(timezone.utc),
        providers={
            "anthropic": LLMProviderRecommendation(
                default_model=SimpleKnownModel(name="claude-opus-4-8"),
                additional_visible_models=[
                    SimpleKnownModel(
                        name="claude-opus-4-8", display_name="Claude Opus 4.8"
                    ),
                    SimpleKnownModel(
                        name="claude-sonnet-4-6", display_name="Claude Sonnet 4.6"
                    ),
                ],
            )
        },
    )

    visible = recommendations.get_visible_models("anthropic")

    assert [(m.name, m.display_name) for m in visible] == [
        ("claude-opus-4-8", "Claude Opus 4.8"),
        ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
    ]


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


def test_model_configurations_oci_are_sorted_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # OCI hosts several vendors (meta., cohere., xai., ...); like Vertex the
    # list is alphabetised so vendors cluster together in the picker.
    monkeypatch.setattr(
        "onyx.llm.well_known_providers.llm_provider_options.fetch_models_for_provider",
        lambda _provider_name: ["xai.grok-4", "cohere.command-a-03-2025"],
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
        OCI_PROVIDER_NAME, ["meta.llama-3.3-70b-instruct"]
    )

    model_configurations = model_configurations_for_provider(
        OCI_PROVIDER_NAME, recommendations
    )

    assert [model.name for model in model_configurations] == [
        "cohere.command-a-03-2025",
        "meta.llama-3.3-70b-instruct",
        "xai.grok-4",
    ]


def test_get_oci_model_names_are_chat_models_without_prefix() -> None:
    """The list comes straight from LiteLLM's `oci/` catalog: chat models
    only (the catalog also carries embeddings), with the provider prefix
    stripped so names match what the OCI API expects."""
    import litellm

    model_names = get_oci_model_names()

    assert model_names
    assert model_names == sorted(model_names)
    for name in model_names:
        assert not name.startswith("oci/")
        assert litellm.model_cost[f"oci/{name}"]["mode"] == "chat"
    assert not any("embed" in name for name in model_names)


def test_model_configurations_carry_display_name_and_dedupe_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The default is repeated in additional_visible_models (where it carries a
    # display name); the result must be deduped and carry that display name.
    monkeypatch.setattr(
        "onyx.llm.well_known_providers.llm_provider_options.fetch_models_for_provider",
        lambda _provider_name: [],
    )
    monkeypatch.setattr(
        "onyx.llm.well_known_providers.llm_provider_options.get_max_input_tokens",
        lambda _model_name, _provider_name: None,
    )
    monkeypatch.setattr(
        "onyx.llm.well_known_providers.llm_provider_options.model_supports_image_input",
        lambda _model_name, _provider_name: False,
    )

    recommendations = LLMRecommendations(
        version="test",
        updated_at=datetime.now(timezone.utc),
        providers={
            "anthropic": LLMProviderRecommendation(
                default_model=SimpleKnownModel(name="claude-opus-4-8"),
                additional_visible_models=[
                    SimpleKnownModel(
                        name="claude-opus-4-8", display_name="Claude Opus 4.8"
                    ),
                    SimpleKnownModel(
                        name="claude-sonnet-4-6", display_name="Claude Sonnet 4.6"
                    ),
                ],
            )
        },
    )

    model_configurations = model_configurations_for_provider(
        "anthropic", recommendations
    )

    assert [m.name for m in model_configurations] == [
        "claude-opus-4-8",
        "claude-sonnet-4-6",
    ]
    by_name = {m.name: m for m in model_configurations}
    assert by_name["claude-opus-4-8"].display_name == "Claude Opus 4.8"
    assert all(m.is_visible for m in model_configurations)
    # Only the config's default model is flagged as the recommended default.
    assert by_name["claude-opus-4-8"].is_recommended_default is True
    assert by_name["claude-sonnet-4-6"].is_recommended_default is False


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
