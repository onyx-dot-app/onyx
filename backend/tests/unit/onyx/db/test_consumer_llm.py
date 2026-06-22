from types import SimpleNamespace
from unittest.mock import Mock

from onyx.db.consumer_llm import build_consumer_llm_provider_request
from onyx.db.consumer_llm import ConsumerDefaultLLMConfig
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


def test_seed_allows_minimax_when_legacy_gpt_provider_disabled(monkeypatch) -> None:
    monkeypatch.setattr("onyx.db.consumer_llm.GLOMI_MINIMAX_LLM_ENABLED", True)
    sync_mock = Mock(return_value=SimpleNamespace(synced=True, reason="synced"))
    monkeypatch.setattr(
        "onyx.db.glomi_model_catalog.sync_glomi_platform_model_catalog",
        sync_mock,
    )

    result = seed_consumer_default_llm_provider(Mock(), _config(enabled=False))

    assert result.seeded is True
    assert result.reason == "synced"


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


def test_seed_does_not_require_legacy_single_model_name(monkeypatch) -> None:
    sync_mock = Mock(return_value=SimpleNamespace(synced=True, reason="synced"))
    monkeypatch.setattr(
        "onyx.db.glomi_model_catalog.sync_glomi_platform_model_catalog",
        sync_mock,
    )

    result = seed_consumer_default_llm_provider(Mock(), _config(model_name=""))

    assert result.seeded is True
    assert result.reason == "synced"


def test_seed_delegates_to_glomi_platform_catalog(monkeypatch) -> None:
    sync_mock = Mock(return_value=SimpleNamespace(synced=True, reason="synced"))
    monkeypatch.setattr(
        "onyx.db.glomi_model_catalog.sync_glomi_platform_model_catalog",
        sync_mock,
    )

    db_session = Mock()
    result = seed_consumer_default_llm_provider(db_session, _config())

    assert result.seeded is True
    assert result.reason == "synced"
    sync_mock.assert_called_once()
    assert sync_mock.call_args.args[0] is db_session
