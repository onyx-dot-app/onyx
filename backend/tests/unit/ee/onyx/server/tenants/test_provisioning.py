"""Tests for tenant provisioning helpers."""

from unittest.mock import MagicMock, patch

import pytest

_PROVISIONING_MODULE = "ee.onyx.server.tenants.provisioning"


def _patch_recommendations() -> MagicMock:
    """Build a MagicMock that imitates `LLMProviderRecommendations`.

    `configure_default_api_keys` calls `get_default_model(provider)` and
    `get_visible_models(provider)` on the recommendations object — return
    plausible stubs so the function reaches the env-var gating logic.
    """
    rec = MagicMock()
    default_model = MagicMock()
    default_model.name = "test-model"
    rec.get_default_model.return_value = default_model
    rec.get_visible_models.return_value = []
    return rec


def _run_configure(
    *,
    enabled: bool,
) -> tuple[MagicMock, MagicMock]:
    """Execute `configure_default_api_keys` with all four cloud key env vars
    set to non-empty placeholders and the auto-provision flag toggled.

    Returns the (upsert_llm_provider, create_default_image_gen_config_from_api_key)
    mocks so callers can assert call counts.
    """
    with (
        patch(f"{_PROVISIONING_MODULE}.AUTO_PROVISION_DEFAULT_LLM_PROVIDERS", enabled),
        patch(f"{_PROVISIONING_MODULE}.OPENAI_DEFAULT_API_KEY", "openai-key"),
        patch(f"{_PROVISIONING_MODULE}.ANTHROPIC_DEFAULT_API_KEY", "anthropic-key"),
        patch(f"{_PROVISIONING_MODULE}.OPENROUTER_DEFAULT_API_KEY", "openrouter-key"),
        patch(f"{_PROVISIONING_MODULE}.COHERE_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.VERTEXAI_DEFAULT_CREDENTIALS", None),
        patch(
            f"{_PROVISIONING_MODULE}.get_recommendations",
            return_value=_patch_recommendations(),
        ),
        patch(
            f"{_PROVISIONING_MODULE}.fetch_existing_llm_provider_by_name_and_type",
            return_value=None,
        ),
        patch(
            f"{_PROVISIONING_MODULE}.fetch_existing_llm_provider_by_type_nameless",
            return_value=None,
        ),
        patch(f"{_PROVISIONING_MODULE}.upsert_llm_provider") as upsert_mock,
        patch(f"{_PROVISIONING_MODULE}.update_default_model"),
        patch(
            f"{_PROVISIONING_MODULE}.create_default_image_gen_config_from_api_key"
        ) as image_gen_mock,
        patch(
            f"{_PROVISIONING_MODULE}._build_model_configuration_upsert_requests",
            return_value=[],
        ),
    ):
        upsert_mock.return_value = MagicMock(id=1)
        from ee.onyx.server.tenants.provisioning import configure_default_api_keys

        configure_default_api_keys(MagicMock())
        return upsert_mock, image_gen_mock


def test_auto_provision_enabled_creates_default_providers() -> None:
    upsert_mock, image_gen_mock = _run_configure(enabled=True)
    # OpenAI + Anthropic + OpenRouter all auto-provisioned.
    assert upsert_mock.call_count == 3
    # Image generation default config is seeded from the OpenAI key.
    assert image_gen_mock.call_count == 1


def test_auto_provision_disabled_skips_default_providers() -> None:
    upsert_mock, image_gen_mock = _run_configure(enabled=False)
    # Cloud opt-out: no LLMProvider rows created and no default image-gen
    # config seeded with the cloud OpenAI key.
    assert upsert_mock.call_count == 0
    assert image_gen_mock.call_count == 0


def test_playground_skips_vertex_and_uses_the_playground_default() -> None:
    """On the playground, Vertex is not created (its cost is not counted), and
    the chat default comes from the playground's price rule."""
    with (
        patch(f"{_PROVISIONING_MODULE}.IS_PLAYGROUND", True),
        patch(f"{_PROVISIONING_MODULE}.AUTO_PROVISION_DEFAULT_LLM_PROVIDERS", True),
        patch(f"{_PROVISIONING_MODULE}.OPENAI_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.ANTHROPIC_DEFAULT_API_KEY", "anthropic-key"),
        patch(f"{_PROVISIONING_MODULE}.OPENROUTER_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.COHERE_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.VERTEXAI_DEFAULT_CREDENTIALS", "{}"),
        patch(
            f"{_PROVISIONING_MODULE}.get_recommendations",
            return_value=_patch_recommendations(),
        ),
        patch(
            f"{_PROVISIONING_MODULE}.playground_default_model",
            return_value="playground-default",
        ),
        patch(
            f"{_PROVISIONING_MODULE}.fetch_existing_llm_provider_by_name_and_type",
            return_value=None,
        ),
        patch(f"{_PROVISIONING_MODULE}.upsert_llm_provider") as upsert_mock,
        patch(f"{_PROVISIONING_MODULE}.update_default_model") as default_mock,
        patch(
            f"{_PROVISIONING_MODULE}._build_model_configuration_upsert_requests",
            return_value=[],
        ),
    ):
        upsert_mock.return_value = MagicMock(id=1)
        from ee.onyx.server.tenants.provisioning import configure_default_api_keys

        configure_default_api_keys(MagicMock())

    created = [call.args[0].provider for call in upsert_mock.call_args_list]
    assert created == ["anthropic"]
    assert default_mock.call_args.kwargs["model"] == "playground-default"


def test_playground_shows_only_the_models_its_price_rule_offers() -> None:
    from ee.onyx.server.tenants.provisioning import (
        _build_model_configuration_upsert_requests,
    )

    models = []
    for name in ("cheap", "pricey"):
        model = MagicMock(is_visible=True, max_input_tokens=None)
        model.name = name
        model.supports_image_input = False
        models.append(model)
    with (
        patch(
            f"{_PROVISIONING_MODULE}.model_configurations_for_provider",
            return_value=models,
        ),
        patch(
            f"{_PROVISIONING_MODULE}.is_offered_on_playground",
            side_effect=lambda _provider, name, _rec: name == "cheap",
        ),
    ):
        with patch(f"{_PROVISIONING_MODULE}.IS_PLAYGROUND", True):
            playground = _build_model_configuration_upsert_requests(
                "openai", MagicMock()
            )
        with patch(f"{_PROVISIONING_MODULE}.IS_PLAYGROUND", False):
            cloud = _build_model_configuration_upsert_requests("openai", MagicMock())

    assert {m.name: m.is_visible for m in playground} == {
        "cheap": True,
        "pricey": False,
    }
    assert {m.name: m.is_visible for m in cloud} == {"cheap": True, "pricey": True}


@pytest.mark.parametrize(
    ("playground", "vertex_created"), [(True, False), (False, True)]
)
def test_vertex_is_skipped_only_on_the_playground(
    playground: bool, vertex_created: bool
) -> None:
    with (
        patch(f"{_PROVISIONING_MODULE}.IS_PLAYGROUND", playground),
        patch(f"{_PROVISIONING_MODULE}.AUTO_PROVISION_DEFAULT_LLM_PROVIDERS", True),
        patch(f"{_PROVISIONING_MODULE}.OPENAI_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.ANTHROPIC_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.OPENROUTER_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.COHERE_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.VERTEXAI_DEFAULT_CREDENTIALS", "{}"),
        patch(
            f"{_PROVISIONING_MODULE}.get_recommendations",
            return_value=_patch_recommendations(),
        ),
        patch(
            f"{_PROVISIONING_MODULE}.fetch_existing_llm_provider_by_name_and_type",
            return_value=None,
        ),
        patch(f"{_PROVISIONING_MODULE}.upsert_llm_provider") as upsert_mock,
        patch(f"{_PROVISIONING_MODULE}.update_default_model"),
        patch(
            f"{_PROVISIONING_MODULE}._build_model_configuration_upsert_requests",
            return_value=[],
        ),
    ):
        upsert_mock.return_value = MagicMock(id=1)
        from ee.onyx.server.tenants.provisioning import configure_default_api_keys

        configure_default_api_keys(MagicMock())

    assert (upsert_mock.call_count == 1) is vertex_created


@pytest.mark.parametrize(
    ("playground", "rule_default", "recommended", "expected"),
    [
        (True, "rule-pick", "recommended-pick", "rule-pick"),
        (True, None, "recommended-pick", None),  # never a default the rule refuses
        (False, "rule-pick", "recommended-pick", "recommended-pick"),
        (False, None, None, "fallback"),
    ],
)
def test_default_model_name(
    playground: bool,
    rule_default: str | None,
    recommended: str | None,
    expected: str | None,
) -> None:
    from ee.onyx.server.tenants.provisioning import _default_model_name

    recommendations = MagicMock()
    if recommended is None:
        recommendations.get_default_model.return_value = None
    else:
        recommended_model = MagicMock()
        recommended_model.name = recommended
        recommendations.get_default_model.return_value = recommended_model
    with (
        patch(f"{_PROVISIONING_MODULE}.IS_PLAYGROUND", playground),
        patch(
            f"{_PROVISIONING_MODULE}.playground_default_model",
            return_value=rule_default,
        ),
    ):
        assert _default_model_name("anthropic", recommendations, "fallback") == expected


def test_playground_shows_only_the_openrouter_models_its_price_rule_offers() -> None:
    """OpenRouter builds its model list from the recommendations, not the
    catalog, so the rule is applied there separately."""
    recommendations = _patch_recommendations()
    visible = []
    for name in ("cheap", "pricey"):
        model = MagicMock(display_name=None)
        model.name = name
        visible.append(model)
    recommendations.get_visible_models.return_value = visible
    with (
        patch(f"{_PROVISIONING_MODULE}.IS_PLAYGROUND", True),
        patch(f"{_PROVISIONING_MODULE}.AUTO_PROVISION_DEFAULT_LLM_PROVIDERS", True),
        patch(f"{_PROVISIONING_MODULE}.OPENAI_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.ANTHROPIC_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.OPENROUTER_DEFAULT_API_KEY", "openrouter-key"),
        patch(f"{_PROVISIONING_MODULE}.COHERE_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.VERTEXAI_DEFAULT_CREDENTIALS", None),
        patch(
            f"{_PROVISIONING_MODULE}.get_recommendations", return_value=recommendations
        ),
        patch(f"{_PROVISIONING_MODULE}.playground_default_model", return_value="cheap"),
        patch(
            f"{_PROVISIONING_MODULE}.is_offered_on_playground",
            side_effect=lambda _provider, name, _rec: name == "cheap",
        ),
        patch(
            f"{_PROVISIONING_MODULE}.fetch_existing_llm_provider_by_name_and_type",
            return_value=None,
        ),
        patch(f"{_PROVISIONING_MODULE}.upsert_llm_provider") as upsert_mock,
        patch(f"{_PROVISIONING_MODULE}.update_default_model"),
    ):
        upsert_mock.return_value = MagicMock(id=1)
        from ee.onyx.server.tenants.provisioning import configure_default_api_keys

        configure_default_api_keys(MagicMock())

    request = upsert_mock.call_args.args[0]
    assert {m.name: m.is_visible for m in request.model_configurations} == {
        "cheap": True,
        "pricey": False,
    }


def test_a_provider_without_a_playground_default_does_not_set_the_chat_default() -> (
    None
):
    """Anthropic has no model within the default price limit, so OpenRouter,
    created after it, sets the tenant's chat default."""
    with (
        patch(f"{_PROVISIONING_MODULE}.IS_PLAYGROUND", True),
        patch(f"{_PROVISIONING_MODULE}.AUTO_PROVISION_DEFAULT_LLM_PROVIDERS", True),
        patch(f"{_PROVISIONING_MODULE}.OPENAI_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.ANTHROPIC_DEFAULT_API_KEY", "anthropic-key"),
        patch(f"{_PROVISIONING_MODULE}.OPENROUTER_DEFAULT_API_KEY", "openrouter-key"),
        patch(f"{_PROVISIONING_MODULE}.COHERE_DEFAULT_API_KEY", None),
        patch(f"{_PROVISIONING_MODULE}.VERTEXAI_DEFAULT_CREDENTIALS", None),
        patch(
            f"{_PROVISIONING_MODULE}.get_recommendations",
            return_value=_patch_recommendations(),
        ),
        patch(
            f"{_PROVISIONING_MODULE}.playground_default_model",
            side_effect=lambda provider, _rec: (
                None if provider == "anthropic" else "glm-cheap"
            ),
        ),
        patch(
            f"{_PROVISIONING_MODULE}.fetch_existing_llm_provider_by_name_and_type",
            return_value=None,
        ),
        patch(f"{_PROVISIONING_MODULE}.upsert_llm_provider") as upsert_mock,
        patch(f"{_PROVISIONING_MODULE}.update_default_model") as default_mock,
        patch(
            f"{_PROVISIONING_MODULE}._build_model_configuration_upsert_requests",
            return_value=[],
        ),
    ):
        upsert_mock.side_effect = [MagicMock(id=1), MagicMock(id=2)]
        from ee.onyx.server.tenants.provisioning import configure_default_api_keys

        configure_default_api_keys(MagicMock())

    assert upsert_mock.call_count == 2
    default_mock.assert_called_once()
    assert default_mock.call_args.kwargs["provider_id"] == 2
    assert default_mock.call_args.kwargs["model"] == "glm-cheap"
