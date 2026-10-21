from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from onyx.error_handling.exceptions import OnyxError
from onyx.llm.constants import WELL_KNOWN_PROVIDER_NAMES, LlmProviderNames
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


def test_discovery_rejects_another_provider_before_reading_credentials() -> None:
    from onyx.server.manage.llm import api

    stored = MagicMock(provider="openai")
    with patch.object(api, "fetch_existing_llm_provider_by_id", return_value=stored):
        with pytest.raises(OnyxError, match="requires a TypeSafe"):
            api.get_typesafe_available_models(
                TypeSafeModelsRequest(provider_id=7), MagicMock(), MagicMock()
            )
    stored.api_key.get_value.assert_not_called()


def test_update_cannot_reuse_another_providers_key() -> None:
    from onyx.server.manage.llm.api import put_llm_provider

    stored = MagicMock(provider="openai")
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


def test_admin_test_dispatch_restores_key_without_chat_client() -> None:
    from onyx.server.manage.llm.api import test_decision_provider as test_configuration

    stored = MagicMock(provider="typesafe", api_base=None, custom_config=None)
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
        patch("onyx.server.manage.llm.api.DecisionClient") as check,
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
        patch("onyx.server.manage.llm.api.DecisionClient") as check,
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
