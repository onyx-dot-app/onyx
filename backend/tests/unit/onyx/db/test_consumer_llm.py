from types import SimpleNamespace
from unittest.mock import Mock

from onyx.db.consumer_llm import ConsumerDefaultLLMConfig
from onyx.db.consumer_llm import build_consumer_llm_provider_request
from onyx.db.consumer_llm import seed_consumer_default_llm_provider


def _config(
    *,
    enabled: bool = True,
    api_base: str | None = "https://example.test/v1",
    api_key: str | None = "test-key",
    model_name: str | None = "qwen-plus",
    auto_provision_enabled: bool = True,
) -> ConsumerDefaultLLMConfig:
    return ConsumerDefaultLLMConfig(
        enabled=enabled,
        api_base=api_base,
        api_key=api_key,
        model_name=model_name,
        auto_provision_enabled=auto_provision_enabled,
    )


def test_build_consumer_llm_provider_request_uses_single_main_model() -> None:
    request = build_consumer_llm_provider_request(_config())

    assert request.name == "Glomi Default"
    assert request.provider == "openai_compatible"
    assert request.api_base == "https://example.test/v1"
    assert request.api_key == "test-key"
    assert request.api_key_changed is True
    assert request.is_public is True
    assert request.is_auto_mode is False
    assert [model.name for model in request.model_configurations] == ["qwen-plus"]
    assert request.model_configurations[0].is_visible is True


def test_seed_skips_when_disabled() -> None:
    result = seed_consumer_default_llm_provider(Mock(), _config(enabled=False))

    assert result.seeded is False
    assert result.reason == "disabled"


def test_seed_skips_when_auto_provisioning_disabled() -> None:
    result = seed_consumer_default_llm_provider(
        Mock(), _config(auto_provision_enabled=False)
    )

    assert result.seeded is False
    assert result.reason == "auto_provision_disabled"


def test_seed_skips_when_api_key_missing() -> None:
    result = seed_consumer_default_llm_provider(Mock(), _config(api_key=None))

    assert result.seeded is False
    assert result.reason == "missing_api_key"


def test_seed_skips_when_api_base_missing() -> None:
    result = seed_consumer_default_llm_provider(Mock(), _config(api_base=""))

    assert result.seeded is False
    assert result.reason == "missing_api_base"


def test_seed_skips_when_model_name_missing() -> None:
    result = seed_consumer_default_llm_provider(Mock(), _config(model_name=""))

    assert result.seeded is False
    assert result.reason == "missing_model_name"


def test_seed_upserts_provider_and_sets_default_when_missing(monkeypatch) -> None:
    upsert_llm_provider = Mock(return_value=SimpleNamespace(id=7))
    update_default_provider = Mock()

    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_existing_llm_provider_by_name_and_type",
        Mock(return_value=None),
    )
    monkeypatch.setattr("onyx.db.consumer_llm.upsert_llm_provider", upsert_llm_provider)
    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_default_llm_model", Mock(return_value=None)
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.update_default_provider", update_default_provider
    )

    db_session = Mock()
    result = seed_consumer_default_llm_provider(db_session, _config())

    request = upsert_llm_provider.call_args.args[0]
    assert result.seeded is True
    assert result.reason == "seeded"
    assert request.id is None
    update_default_provider.assert_called_once_with(7, "qwen-plus", db_session)


def test_seed_preserves_existing_extra_models(monkeypatch) -> None:
    existing_provider = SimpleNamespace(
        id=7,
        model_configurations=[
            SimpleNamespace(
                name="legacy-model",
                is_visible=True,
                max_input_tokens=1234,
                supports_image_input=False,
                display_name="Legacy Model",
                custom_display_name=None,
            )
        ],
    )
    upsert_llm_provider = Mock(return_value=SimpleNamespace(id=7))

    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_existing_llm_provider_by_name_and_type",
        Mock(return_value=existing_provider),
    )
    monkeypatch.setattr("onyx.db.consumer_llm.upsert_llm_provider", upsert_llm_provider)
    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_default_llm_model", Mock(return_value=None)
    )
    monkeypatch.setattr("onyx.db.consumer_llm.update_default_provider", Mock())

    seed_consumer_default_llm_provider(Mock(), _config())

    request = upsert_llm_provider.call_args.args[0]
    assert request.id == 7
    assert {model.name for model in request.model_configurations} == {
        "qwen-plus",
        "legacy-model",
    }
    legacy = next(
        model for model in request.model_configurations if model.name == "legacy-model"
    )
    assert legacy.is_visible is True
    assert legacy.max_input_tokens == 1234


def test_seed_updates_default_when_current_default_is_same_provider(
    monkeypatch,
) -> None:
    existing_provider = SimpleNamespace(id=7, model_configurations=[])
    current_default = SimpleNamespace(llm_provider_id=7, name="old-main-model")
    update_default_provider = Mock()

    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_existing_llm_provider_by_name_and_type",
        Mock(return_value=existing_provider),
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.upsert_llm_provider",
        Mock(return_value=SimpleNamespace(id=7)),
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_default_llm_model",
        Mock(return_value=current_default),
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.update_default_provider", update_default_provider
    )

    seed_consumer_default_llm_provider(Mock(), _config(model_name="qwen-max"))

    update_default_provider.assert_called_once()
    assert update_default_provider.call_args.args[1] == "qwen-max"


def test_seed_does_not_override_other_provider_default(monkeypatch) -> None:
    existing_provider = SimpleNamespace(id=7, model_configurations=[])
    current_default = SimpleNamespace(llm_provider_id=99, name="admin-model")
    update_default_provider = Mock()

    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_existing_llm_provider_by_name_and_type",
        Mock(return_value=existing_provider),
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.upsert_llm_provider",
        Mock(return_value=SimpleNamespace(id=7)),
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_default_llm_model",
        Mock(return_value=current_default),
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.update_default_provider", update_default_provider
    )

    seed_consumer_default_llm_provider(Mock(), _config(model_name="qwen-max"))

    update_default_provider.assert_not_called()
