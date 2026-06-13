from types import SimpleNamespace
from unittest.mock import Mock

from onyx.db.consumer_llm import ConsumerDefaultLLMConfig
from onyx.db.consumer_llm import build_consumer_llm_provider_request
from onyx.db.consumer_llm import seed_consumer_default_llm_provider


def test_build_consumer_llm_provider_request_uses_catalog_models() -> None:
    request = build_consumer_llm_provider_request(
        ConsumerDefaultLLMConfig(
            enabled=True,
            provider_name="Qwen",
            provider_type="openai_compatible",
            api_base="https://example.test/v1",
            api_key="test-key",
            default_profile_id="balanced",
            auto_provision_enabled=True,
        )
    )

    assert request.name == "Qwen"
    assert request.provider == "openai_compatible"
    assert request.api_base == "https://example.test/v1"
    assert request.api_key == "test-key"
    assert request.api_key_changed is True
    assert {model.name for model in request.model_configurations} == {
        "qwen-turbo",
        "qwen-plus",
        "qwen-max",
        "qwen3-coder-plus",
        "qwen-vl-plus",
    }
    vision_model = next(
        model
        for model in request.model_configurations
        if model.name == "qwen-vl-plus"
    )
    assert vision_model.supports_image_input is True


def test_seed_skips_when_consumer_default_is_disabled() -> None:
    result = seed_consumer_default_llm_provider(
        Mock(),
        ConsumerDefaultLLMConfig(
            enabled=False,
            provider_name="Qwen",
            provider_type="openai_compatible",
            api_base="https://example.test/v1",
            api_key="test-key",
            default_profile_id="balanced",
            auto_provision_enabled=True,
        ),
    )

    assert result.seeded is False
    assert result.reason == "disabled"


def test_seed_upserts_provider_and_sets_default_when_missing(monkeypatch) -> None:
    upsert_llm_provider = Mock(return_value=SimpleNamespace(id=7))
    update_default_provider = Mock()
    fetch_default_llm_model = Mock(return_value=None)
    fetch_default_vision_model = Mock(return_value=None)
    update_default_vision_provider = Mock()

    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_existing_llm_provider_by_name_and_type",
        Mock(return_value=SimpleNamespace(id=7, model_configurations=[])),
    )
    monkeypatch.setattr("onyx.db.consumer_llm.upsert_llm_provider", upsert_llm_provider)
    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_default_llm_model", fetch_default_llm_model
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.update_default_provider", update_default_provider
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_default_vision_model", fetch_default_vision_model
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.update_default_vision_provider",
        update_default_vision_provider,
    )

    result = seed_consumer_default_llm_provider(
        Mock(),
        ConsumerDefaultLLMConfig(
            enabled=True,
            provider_name="Qwen",
            provider_type="openai_compatible",
            api_base="https://example.test/v1",
            api_key="test-key",
            default_profile_id="balanced",
            auto_provision_enabled=True,
        ),
    )

    request = upsert_llm_provider.call_args.args[0]
    assert result.seeded is True
    assert request.id == 7
    update_default_provider.assert_called_once_with(
        7, "qwen-plus", upsert_llm_provider.call_args.args[1]
    )
    update_default_vision_provider.assert_called_once_with(
        7, "qwen-vl-plus", upsert_llm_provider.call_args.args[1]
    )
