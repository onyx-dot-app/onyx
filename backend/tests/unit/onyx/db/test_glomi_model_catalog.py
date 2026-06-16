from types import SimpleNamespace
from unittest.mock import Mock

from onyx.db.glomi_model_catalog import get_glomi_platform_model_catalog
from onyx.db.glomi_model_catalog import GLOMI_PLATFORM_MODELS
from onyx.db.glomi_model_catalog import GlomiPlatformModelCatalog
from onyx.db.glomi_model_catalog import sync_glomi_platform_model_catalog


def test_catalog_contains_phase_a_models() -> None:
    catalog = get_glomi_platform_model_catalog()
    model_names = {model.model_name for model in catalog.models}

    assert model_names == {
        "gpt-5.5",
        "qwen3.7-plus",
        "deepseek-v4-pro",
        "glm-5.2",
    }


def test_phase_a_model_capabilities_are_explicit() -> None:
    models = {model.model_name: model for model in GLOMI_PLATFORM_MODELS}

    assert models["gpt-5.5"].supports_image_input is True
    assert models["gpt-5.5"].supports_reasoning is True
    assert "vision" in models["gpt-5.5"].roles

    assert models["qwen3.7-plus"].supports_image_input is True
    assert models["qwen3.7-plus"].supports_reasoning is True
    assert "vision" in models["qwen3.7-plus"].roles

    assert models["deepseek-v4-pro"].supports_image_input is False
    assert models["deepseek-v4-pro"].supports_reasoning is True

    assert models["glm-5.2"].supports_image_input is False
    assert models["glm-5.2"].supports_reasoning is True
    assert "coding" in models["glm-5.2"].roles


def test_sync_skips_when_credentials_missing() -> None:
    catalog = GlomiPlatformModelCatalog(
        provider_name="Glomi Default",
        provider_type="openai_compatible",
        api_base="https://example.test/v1",
        api_key=None,
        enabled=True,
        models=GLOMI_PLATFORM_MODELS,
    )

    result = sync_glomi_platform_model_catalog(Mock(), catalog)

    assert result.synced is False
    assert result.reason == "missing_api_key"


def test_sync_builds_four_visible_model_configurations(mocker) -> None:
    db_session = Mock()
    provider = SimpleNamespace(id=7)
    mocker.patch(
        "onyx.db.glomi_model_catalog.fetch_existing_llm_provider_by_name_and_type",
        return_value=None,
    )
    upsert_mock = mocker.patch(
        "onyx.db.glomi_model_catalog.upsert_llm_provider",
        return_value=provider,
    )
    mocker.patch("onyx.db.glomi_model_catalog.fetch_default_llm_model", return_value=None)
    update_default_mock = mocker.patch(
        "onyx.db.glomi_model_catalog.update_default_provider"
    )
    catalog = GlomiPlatformModelCatalog(
        provider_name="Glomi Default",
        provider_type="openai_compatible",
        api_base="https://example.test/v1",
        api_key="test-key",
        enabled=True,
        models=GLOMI_PLATFORM_MODELS,
    )

    result = sync_glomi_platform_model_catalog(db_session, catalog)

    request = upsert_mock.call_args.args[0]
    assert result.synced is True
    assert [m.name for m in request.model_configurations] == [
        "gpt-5.5",
        "qwen3.7-plus",
        "deepseek-v4-pro",
        "glm-5.2",
    ]
    assert all(m.is_visible for m in request.model_configurations)
    assert request.model_configurations[0].supports_image_input is True
    assert request.model_configurations[2].supports_image_input is False
    update_default_mock.assert_called_once_with(7, "gpt-5.5", db_session)


def test_sync_preserves_existing_extra_models_and_provider_settings(mocker) -> None:
    db_session = Mock()
    existing_provider = SimpleNamespace(
        id=7,
        api_key="existing-key",
        api_base="https://existing.test/v1",
        api_version="2026-06-16",
        custom_config={"tenant": "existing"},
        deployment_name="existing-deployment",
        model_configurations=[
            SimpleNamespace(
                name="legacy-model",
                is_visible=True,
                max_input_tokens=1234,
                supports_image_input=False,
                llm_model_flow_types=[],
                display_name="Legacy Model",
                custom_display_name=None,
            )
        ],
    )
    provider = SimpleNamespace(id=7)
    mocker.patch(
        "onyx.db.glomi_model_catalog.fetch_existing_llm_provider_by_name_and_type",
        return_value=existing_provider,
    )
    upsert_mock = mocker.patch(
        "onyx.db.glomi_model_catalog.upsert_llm_provider",
        return_value=provider,
    )
    mocker.patch("onyx.db.glomi_model_catalog.fetch_default_llm_model", return_value=None)
    mocker.patch("onyx.db.glomi_model_catalog.update_default_provider")
    catalog = GlomiPlatformModelCatalog(
        provider_name="Glomi Default",
        provider_type="openai_compatible",
        api_base="https://new.test/v1",
        api_key="new-key",
        enabled=True,
        models=GLOMI_PLATFORM_MODELS,
    )

    sync_glomi_platform_model_catalog(db_session, catalog)

    request = upsert_mock.call_args.args[0]
    assert request.id == 7
    assert request.api_key == "existing-key"
    assert request.api_base == "https://existing.test/v1"
    assert request.api_version == "2026-06-16"
    assert request.custom_config == {"tenant": "existing"}
    assert request.deployment_name == "existing-deployment"
    assert {model.name for model in request.model_configurations} == {
        "gpt-5.5",
        "qwen3.7-plus",
        "deepseek-v4-pro",
        "glm-5.2",
        "legacy-model",
    }


def test_sync_does_not_override_existing_default_model(mocker) -> None:
    db_session = Mock()
    provider = SimpleNamespace(id=7)
    existing_default = SimpleNamespace(llm_provider_id=99, name="admin-model")
    mocker.patch(
        "onyx.db.glomi_model_catalog.fetch_existing_llm_provider_by_name_and_type",
        return_value=None,
    )
    mocker.patch(
        "onyx.db.glomi_model_catalog.upsert_llm_provider",
        return_value=provider,
    )
    mocker.patch(
        "onyx.db.glomi_model_catalog.fetch_default_llm_model",
        return_value=existing_default,
    )
    update_default_mock = mocker.patch(
        "onyx.db.glomi_model_catalog.update_default_provider"
    )
    catalog = GlomiPlatformModelCatalog(
        provider_name="Glomi Default",
        provider_type="openai_compatible",
        api_base="https://example.test/v1",
        api_key="test-key",
        enabled=True,
        models=GLOMI_PLATFORM_MODELS,
    )

    sync_glomi_platform_model_catalog(db_session, catalog)

    update_default_mock.assert_not_called()
