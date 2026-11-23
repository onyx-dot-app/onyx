from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from onyx.db.enums import LLMModelFlowType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.constants import (
    PROVIDER_DISPLAY_NAMES,
    WELL_KNOWN_PROVIDER_NAMES,
    LlmProviderNames,
)
from onyx.llm.factory import get_llm
from onyx.llm.model_catalog import iter_models
from onyx.llm.well_known_providers.typesafe import (
    fetch_typesafe_models,
)
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
    TypeSafeModelsRequest,
)
from onyx.server.manage.llm.models import (
    TestDecisionProviderRequest as DecisionTestRequest,
)


def test_catalog_registers_decision_provider_without_chat_models() -> None:
    assert LlmProviderNames.TYPESAFE in WELL_KNOWN_PROVIDER_NAMES
    assert iter_models("typesafe", mode="decisions") == ["jev-latest", "jev-preview"]
    assert iter_models("typesafe", mode="chat") == []


def test_configuration_has_no_auto_mode_or_model_rows() -> None:
    request = LLMProviderUpsertRequest(provider=" TypeSafe ", is_auto_mode=True)
    assert request.provider == "typesafe"
    assert request.is_auto_mode is False
    assert request.model_configurations == []
    with pytest.raises(ValidationError, match="chat model configuration"):
        LLMProviderUpsertRequest(
            provider="typesafe",
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name="jev-latest", is_visible=True, supports_chat=True
                )
            ],
        )
    request = LLMProviderUpsertRequest(
        provider="typesafe",
        keep_existing_models=True,
        model_configurations=[
            ModelConfigurationUpsertRequest(
                name="jev-preview",
                is_visible=True,
                supports_decisions=True,
                supports_chat=False,
            )
        ],
    )
    assert request.model_configurations[0].name == "jev-preview"


def test_typesafe_cannot_construct_chat_client() -> None:
    with pytest.raises(ValueError, match="does not support chat"):
        get_llm(
            provider="typesafe",
            model="jev-latest",
            max_input_tokens=100,
            deployment_name=None,
        )


def test_discovery_parses_native_model_names() -> None:
    with patch("onyx.llm.well_known_providers.typesafe.httpx.Client") as client:
        get = client.return_value.__enter__.return_value.get
        get.return_value.json.return_value = {
            "models": [
                {
                    "name": "jev-latest",
                    "description": "Latest",
                    "release_date": "2026-01-01",
                },
                {"name": "jev-preview", "description": "Preview"},
            ]
        }
        assert [model.name for model in fetch_typesafe_models("secret")] == [
            "jev-latest",
            "jev-preview",
        ]
        get.assert_called_once_with(
            "https://api.typesafe.ai/v1/models",
            headers={"Authorization": "Bearer secret"},
        )


def test_discovery_uses_saved_credentials_and_syncs_decision_models() -> None:
    from onyx.llm.well_known_providers.models import TypeSafeModel
    from onyx.server.manage.llm import api

    stored = MagicMock(provider="typesafe")
    stored.api_key.get_value.return_value = "saved-secret"
    with (
        patch.object(api, "fetch_existing_llm_provider_by_id", return_value=stored),
        patch.object(
            api,
            "fetch_typesafe_models",
            return_value=[TypeSafeModel(name="jev-preview")],
        ) as fetch,
        patch.object(api, "_sync_fetched_models") as sync,
    ):
        models = api.get_typesafe_available_models(
            TypeSafeModelsRequest(provider_id=7), MagicMock(), MagicMock()
        )
        fetch.assert_called_once_with("saved-secret")
        assert models[0].name == "jev-preview"
        assert models[0].supports_decisions is True
        assert models[0].supports_chat is False
        assert sync.call_args.kwargs["models"][0].supports_chat is False
        assert sync.call_args.kwargs["expected_provider"] == "typesafe"


def test_discovery_does_not_store_models_when_provider_type_changes() -> None:
    from onyx.llm.well_known_providers.models import TypeSafeModel
    from onyx.server.manage.llm import api

    stored = MagicMock(provider="typesafe")
    stored.api_key.get_value.return_value = "saved-secret"
    changed = MagicMock(provider="openai", id=7, model_configurations=[])
    session = MagicMock()
    locked = session.query.return_value.populate_existing.return_value.filter.return_value.with_for_update.return_value
    locked.first.return_value = changed
    with (
        patch.object(api, "fetch_existing_llm_provider_by_id", return_value=stored),
        patch.object(
            api,
            "fetch_typesafe_models",
            return_value=[TypeSafeModel(name="jev-preview")],
        ),
    ):
        models = api.get_typesafe_available_models(
            TypeSafeModelsRequest(provider_id=7), MagicMock(), session
        )
    assert models[0].name == "jev-preview"
    locked.first.assert_called_once()
    session.execute.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_called_once()


def test_discovery_rejects_another_provider_before_reading_credentials() -> None:
    from onyx.server.manage.llm import api

    stored = MagicMock(provider="openai", zoom_voice_provider_id=None)
    with patch.object(api, "fetch_existing_llm_provider_by_id", return_value=stored):
        with pytest.raises(OnyxError, match="requires a TypeSafe"):
            api.get_typesafe_available_models(
                TypeSafeModelsRequest(provider_id=7), MagicMock(), MagicMock()
            )
    stored.api_key.get_value.assert_not_called()


def test_update_cannot_reuse_another_providers_key() -> None:
    from onyx.server.manage.llm.api import put_llm_provider

    stored = MagicMock(provider="openai", zoom_voice_provider_id=None)
    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
            return_value=stored,
        ),
        patch("onyx.server.manage.llm.api.upsert_llm_provider") as save,
    ):
        with pytest.raises(OnyxError, match="requires a new API key"):
            put_llm_provider(
                LLMProviderUpsertRequest(id=7, provider="typesafe"),
                False,
                MagicMock(),
                MagicMock(),
            )
        stored.api_key.get_value.assert_not_called()
        save.assert_not_called()


def _stored_openai_provider(*flow_types: LLMModelFlowType) -> MagicMock:
    stored = MagicMock(
        id=7,
        provider="openai",
        name="Workspace OpenAI",
        zoom_voice_provider_id=None,
        api_base=None,
        custom_config=None,
        api_key=None,
        is_auto_mode=False,
    )
    models: list[MagicMock] = []
    for flow_type in flow_types:
        model = MagicMock()
        model.llm_model_flow_types = [flow_type]
        models.append(model)
    stored.model_configurations = models
    return stored


def _hosted_decision_change(provider: str) -> LLMProviderUpsertRequest:
    return LLMProviderUpsertRequest(
        id=7,
        provider=provider,
        api_key="new-secret",
        api_key_changed=True,
        keep_existing_models=True,
        model_configurations=[
            ModelConfigurationUpsertRequest(
                name="decision-model",
                is_visible=True,
                supports_chat=False,
                supports_decisions=True,
            )
        ],
    )


@pytest.mark.parametrize("provider", ["typesafe", "nace"])
@pytest.mark.parametrize(
    ("flow_types", "default_provider_id"),
    [((LLMModelFlowType.CHAT,), None), ((), 7)],
)
def test_change_to_hosted_decision_rejects_remaining_chat_use(
    provider: str,
    flow_types: tuple[LLMModelFlowType, ...],
    default_provider_id: int | None,
) -> None:
    from onyx.server.manage.llm.api import put_llm_provider

    stored = _stored_openai_provider(*flow_types)
    chat_default = (
        None
        if default_provider_id is None
        else MagicMock(llm_provider_id=default_provider_id)
    )
    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
            return_value=stored,
        ),
        patch(
            "onyx.server.manage.llm.api.fetch_default_model",
            return_value=chat_default,
        ) as fetch_default,
        patch("onyx.server.manage.llm.api.upsert_llm_provider") as save,
    ):
        with pytest.raises(OnyxError, match="Remove the chat models") as error:
            put_llm_provider(
                _hosted_decision_change(provider),
                False,
                MagicMock(),
                MagicMock(),
            )
    assert error.value.error_code == OnyxErrorCode.VALIDATION_ERROR
    assert PROVIDER_DISPLAY_NAMES[provider] in error.value.detail
    assert "chat default" in error.value.detail
    if not flow_types:
        assert fetch_default.call_args.args[1] == LLMModelFlowType.CHAT
    save.assert_not_called()


@pytest.mark.parametrize("provider", ["typesafe", "nace"])
@pytest.mark.parametrize(
    ("stored_config", "rejected"),
    [(None, False), ({}, False), ({"region": "us-east-1"}, True)],
)
def test_hosted_conversion_checks_restored_custom_config(
    provider: str, stored_config: dict[str, str] | None, rejected: bool
) -> None:
    """An unchanged custom config is restored after request validation."""
    from onyx.server.manage.llm.api import put_llm_provider

    stored = _stored_openai_provider(LLMModelFlowType.DECISION)
    stored.custom_config = stored_config
    saved = MagicMock(
        id=7,
        name="Workspace OpenAI",
        provider=provider,
        api_key=None,
        custom_config=None,
    )
    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
            return_value=stored,
        ),
        patch(
            "onyx.server.manage.llm.api.fetch_default_model",
            return_value=MagicMock(llm_provider_id=99),
        ),
        patch(
            "onyx.server.manage.llm.api.upsert_llm_provider",
            return_value=saved,
        ) as save,
        patch("onyx.server.manage.llm.api.invalidate_provider_listing_cache"),
    ):
        if rejected:
            with pytest.raises(OnyxError, match="hosted System One API") as error:
                put_llm_provider(
                    _hosted_decision_change(provider), False, MagicMock(), MagicMock()
                )
            assert error.value.error_code == OnyxErrorCode.VALIDATION_ERROR
            save.assert_not_called()
            return
        result = put_llm_provider(
            _hosted_decision_change(provider), False, MagicMock(), MagicMock()
        )
    assert result is saved
    request = save.call_args.kwargs["llm_provider_upsert_request"]
    assert request.custom_config == stored_config


@pytest.mark.parametrize("provider", ["typesafe", "nace"])
def test_change_to_hosted_decision_allows_provider_without_chat_rows(
    provider: str,
) -> None:
    from onyx.server.manage.llm.api import put_llm_provider

    stored = _stored_openai_provider(LLMModelFlowType.DECISION)
    saved = MagicMock(
        id=7,
        name="Workspace OpenAI",
        provider=provider,
        api_key=None,
        custom_config=None,
    )
    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
            return_value=stored,
        ),
        patch(
            "onyx.server.manage.llm.api.fetch_default_model",
            return_value=MagicMock(llm_provider_id=99),
        ),
        patch(
            "onyx.server.manage.llm.api.upsert_llm_provider",
            return_value=saved,
        ) as save,
        patch("onyx.server.manage.llm.api.invalidate_provider_listing_cache"),
    ):
        result = put_llm_provider(
            _hosted_decision_change(provider), False, MagicMock(), MagicMock()
        )
    assert result is saved
    request = save.call_args.kwargs["llm_provider_upsert_request"]
    assert request.keep_existing_models is True
    save.assert_called_once()


def test_admin_test_dispatch_restores_key_without_chat_client() -> None:
    from onyx.server.manage.llm.api import test_decision_provider as test_configuration

    stored = MagicMock(
        provider="typesafe",
        api_base=None,
        custom_config=None,
        zoom_voice_provider_id=None,
    )
    stored.api_key.get_value.return_value = "stored-secret"
    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
            return_value=stored,
        ),
        patch(
            "onyx.server.manage.llm.api._decision_provider_catalog",
            return_value={"jev-latest": False},
        ),
        patch("onyx.server.manage.llm.api.build_decision_client") as check,
        patch("onyx.server.manage.llm.api.get_llm") as chat,
    ):
        test_configuration(
            DecisionTestRequest(
                id=7,
                provider="typesafe",
                model="jev-latest",
                api_key_changed=False,
                custom_config_changed=False,
            ),
            MagicMock(),
            MagicMock(),
        )
        assert check.call_args.kwargs["api_key"] == "stored-secret"
        assert check.call_args.kwargs["model"] == "jev-latest"
        check.return_value.decide.assert_called_once()
        chat.assert_not_called()


@pytest.mark.parametrize(
    "stored_provider,requested_provider",
    [("openai", "typesafe"), ("typesafe", "openai")],
)
def test_saved_credentials_cannot_move_between_providers(
    stored_provider: str, requested_provider: str
) -> None:
    from onyx.server.manage.llm.api import test_decision_provider as test_configuration

    stored = MagicMock(provider=stored_provider)
    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
            return_value=stored,
        ),
        patch("onyx.server.manage.llm.api.build_decision_client") as check,
        patch("onyx.server.manage.llm.api.get_llm") as chat,
    ):
        with pytest.raises(OnyxError, match="must match"):
            test_configuration(
                DecisionTestRequest(
                    id=7,
                    provider=requested_provider,
                    model="jev-latest",
                    api_key_changed=False,
                    custom_config_changed=False,
                ),
                MagicMock(),
                MagicMock(),
            )
        stored.api_key.get_value.assert_not_called()
        check.assert_not_called()
        chat.assert_not_called()
