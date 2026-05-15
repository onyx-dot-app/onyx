"""Tests for tenant provisioning helpers."""

from unittest.mock import MagicMock
from unittest.mock import patch

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
        patch(f"{_PROVISIONING_MODULE}.update_default_provider"),
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
