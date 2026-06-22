from types import SimpleNamespace
from unittest.mock import Mock

from onyx.db.glomi_model_catalog import get_glomi_supplier_metadata_for_provider
from onyx.db.glomi_model_catalog import get_glomi_platform_model_catalog
from onyx.db.glomi_model_catalog import GLOMI_GPT_PLATFORM_MODELS
from onyx.db.glomi_model_catalog import GLOMI_MINIMAX_PLATFORM_MODELS
from onyx.db.glomi_model_catalog import GlomiPlatformProviderCatalog
from onyx.db.glomi_model_catalog import GlomiPlatformModelCatalog
from onyx.db.glomi_model_catalog import sync_glomi_platform_model_catalog


def test_catalog_contains_supplier_grouped_gpt_models() -> None:
    catalog = get_glomi_platform_model_catalog()
    gpt_provider = next(
        provider
        for provider in catalog.providers
        if provider.supplier_id == "gpt"
    )
    model_names = {model.model_name for model in gpt_provider.models}

    assert gpt_provider.supplier_display_name == "GPT"
    assert model_names == {"gpt-5.5"}


def test_catalog_can_include_minimax_provider_when_configured(mocker) -> None:
    mocker.patch("onyx.db.glomi_model_catalog.GLOMI_MINIMAX_LLM_ENABLED", True)
    mocker.patch(
        "onyx.db.glomi_model_catalog.GLOMI_MINIMAX_LLM_API_BASE",
        "https://api.minimax.io/v1",
    )
    mocker.patch(
        "onyx.db.glomi_model_catalog.GLOMI_MINIMAX_LLM_API_KEY",
        "minimax-key",
    )
    mocker.patch(
        "onyx.db.glomi_model_catalog.GLOMI_MINIMAX_LLM_MODEL_NAMES",
        ("MiniMax-M3", "MiniMax-M2"),
    )

    catalog = get_glomi_platform_model_catalog()
    minimax_provider = next(
        provider
        for provider in catalog.providers
        if provider.supplier_id == "minimax"
    )

    assert catalog.enabled is True
    assert minimax_provider.provider_name == "Glomi MiniMax"
    assert minimax_provider.supplier_display_name == "MiniMax"
    assert minimax_provider.api_base == "https://api.minimax.io/v1"
    assert [model.model_name for model in minimax_provider.models] == [
        "MiniMax-M3",
        "MiniMax-M2",
    ]


def test_phase_a_model_capabilities_are_explicit() -> None:
    models = {model.model_name: model for model in GLOMI_GPT_PLATFORM_MODELS}

    assert models["gpt-5.5"].supports_image_input is True
    assert models["gpt-5.5"].supports_reasoning is True
    assert "vision" in models["gpt-5.5"].roles

    minimax_models = {
        model.model_name: model for model in GLOMI_MINIMAX_PLATFORM_MODELS
    }
    assert minimax_models["MiniMax-M3"].supports_image_input is True
    assert minimax_models["MiniMax-M3"].supports_reasoning is True
    assert "research" in minimax_models["MiniMax-M3"].roles


def test_sync_skips_when_credentials_missing() -> None:
    provider_catalog = GlomiPlatformProviderCatalog(
        provider_name="Glomi Default",
        provider_type="openai_compatible",
        supplier_id="gpt",
        supplier_display_name="GPT",
        api_base="https://example.test/v1",
        api_key=None,
        enabled=True,
        models=GLOMI_GPT_PLATFORM_MODELS,
    )
    catalog = GlomiPlatformModelCatalog(
        enabled=True,
        providers=(provider_catalog,),
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
    provider_catalog = GlomiPlatformProviderCatalog(
        provider_name="Glomi Default",
        provider_type="openai_compatible",
        supplier_id="gpt",
        supplier_display_name="GPT",
        api_base="https://example.test/v1",
        api_key="test-key",
        enabled=True,
        models=GLOMI_GPT_PLATFORM_MODELS,
    )
    catalog = GlomiPlatformModelCatalog(
        enabled=True,
        providers=(provider_catalog,),
    )

    result = sync_glomi_platform_model_catalog(db_session, catalog)

    request = upsert_mock.call_args.args[0]
    assert result.synced is True
    assert request.name == "Glomi Default"
    assert [m.name for m in request.model_configurations] == ["gpt-5.5"]
    assert all(m.is_visible for m in request.model_configurations)
    assert request.model_configurations[0].supports_image_input is True
    update_default_mock.assert_called_once_with(7, "gpt-5.5", db_session)


def test_sync_builds_multiple_provider_requests(mocker) -> None:
    db_session = Mock()
    gpt_provider = SimpleNamespace(id=7)
    minimax_provider = SimpleNamespace(id=8)
    mocker.patch(
        "onyx.db.glomi_model_catalog.fetch_existing_llm_provider_by_name_and_type",
        return_value=None,
    )
    upsert_mock = mocker.patch(
        "onyx.db.glomi_model_catalog.upsert_llm_provider",
        side_effect=[gpt_provider, minimax_provider],
    )
    mocker.patch("onyx.db.glomi_model_catalog.fetch_default_llm_model", return_value=None)
    update_default_mock = mocker.patch(
        "onyx.db.glomi_model_catalog.update_default_provider"
    )
    catalog = GlomiPlatformModelCatalog(
        enabled=True,
        providers=(
            GlomiPlatformProviderCatalog(
                provider_name="Glomi Default",
                provider_type="openai_compatible",
                supplier_id="gpt",
                supplier_display_name="GPT",
                api_base="https://gpt.test/v1",
                api_key="gpt-key",
                enabled=True,
                models=GLOMI_GPT_PLATFORM_MODELS,
            ),
            GlomiPlatformProviderCatalog(
                provider_name="Glomi MiniMax",
                provider_type="openai_compatible",
                supplier_id="minimax",
                supplier_display_name="MiniMax",
                api_base="https://api.minimax.io/v1",
                api_key="minimax-key",
                enabled=True,
                models=GLOMI_MINIMAX_PLATFORM_MODELS,
            ),
        ),
    )

    result = sync_glomi_platform_model_catalog(db_session, catalog)

    requests = [call.args[0] for call in upsert_mock.call_args_list]
    assert result.synced is True
    assert result.model_count == 2
    assert [request.name for request in requests] == [
        "Glomi Default",
        "Glomi MiniMax",
    ]
    assert [model.name for model in requests[1].model_configurations] == [
        "MiniMax-M3"
    ]
    update_default_mock.assert_called_once_with(7, "gpt-5.5", db_session)


def test_supplier_metadata_lookup_for_catalog_provider() -> None:
    metadata = get_glomi_supplier_metadata_for_provider(
        provider_name="Glomi MiniMax",
        provider_type="openai_compatible",
    )

    assert metadata is not None
    assert metadata.supplier_id == "minimax"
    assert metadata.supplier_display_name == "MiniMax"


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
    provider_catalog = GlomiPlatformProviderCatalog(
        provider_name="Glomi Default",
        provider_type="openai_compatible",
        supplier_id="gpt",
        supplier_display_name="GPT",
        api_base="https://new.test/v1",
        api_key="new-key",
        enabled=True,
        models=GLOMI_GPT_PLATFORM_MODELS,
    )
    catalog = GlomiPlatformModelCatalog(
        enabled=True,
        providers=(provider_catalog,),
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
    provider_catalog = GlomiPlatformProviderCatalog(
        provider_name="Glomi Default",
        provider_type="openai_compatible",
        supplier_id="gpt",
        supplier_display_name="GPT",
        api_base="https://example.test/v1",
        api_key="test-key",
        enabled=True,
        models=GLOMI_GPT_PLATFORM_MODELS,
    )
    catalog = GlomiPlatformModelCatalog(
        enabled=True,
        providers=(provider_catalog,),
    )

    sync_glomi_platform_model_catalog(db_session, catalog)

    update_default_mock.assert_not_called()
