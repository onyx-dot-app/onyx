from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from onyx.db.models import LLMProvider, ModelConfiguration
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm import api
from onyx.server.manage.llm.models import DecisionProviderUpsertRequest
from onyx.server.manage.llm.models import TestDecisionProviderRequest as LLMTestRequest


def test_decision_scope_tests_shared_model_with_decision_protocol() -> None:
    with (
        patch.object(api, "build_decision_client") as decision,
        patch.object(api, "get_llm") as chat,
    ):
        api.test_decision_provider(
            LLMTestRequest(
                provider="openai",
                model="gpt-6-luna",
                api_key="test-key",
                api_key_changed=True,
                custom_config_changed=True,
            ),
            MagicMock(),
            MagicMock(),
        )
    decision.assert_called_once_with(
        provider="openai",
        model="gpt-6-luna",
        api_key="test-key",
        api_base=None,
        zoom_voice_provider_id=None,
    )
    decision.return_value.decide.assert_called_once()
    chat.assert_not_called()


def test_decision_scope_rejects_client_claim_for_chat_only_model() -> None:
    with patch.object(api, "build_decision_client") as decision:
        with pytest.raises(OnyxError, match="does not support decisions"):
            api.test_decision_provider(
                LLMTestRequest(
                    provider="openai",
                    model="gpt-6-sol",
                    api_key="test-key",
                    api_key_changed=True,
                    custom_config_changed=True,
                ),
                MagicMock(),
                MagicMock(),
            )
    decision.assert_not_called()


def test_catalog_does_not_select_a_model() -> None:
    with (
        patch.object(api, "fetch_existing_models", return_value=[]),
        patch.object(api, "fetch_default_model", return_value=None),
    ):
        response = api.get_decision_model_configuration(MagicMock(), MagicMock())
    assert response.model is None
    assert response.providers == []
    assert set(response.supported_providers) == {
        "typesafe",
        "nace",
        "openai",
        "openrouter",
        "zoom_ai",
        "vercel_ai_gateway",
    }


def test_decision_request_rejects_chat_settings() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DecisionProviderUpsertRequest.model_validate(
            {
                "provider": "openai",
                "selected_model_names": [],
                "is_public": True,
            }
        )


def test_decision_update_rejects_redirect_with_stored_credentials() -> None:
    stored = SimpleNamespace(
        provider="openai",
        zoom_voice_provider_id=None,
        api_base=None,
        api_version=None,
        custom_config=None,
        api_key=MagicMock(),
    )
    request = DecisionProviderUpsertRequest(
        id=7,
        provider="openai",
        api_base="https://attacker.example/v1",
        selected_model_names=["gpt-6-luna"],
    )
    with (
        patch.object(api, "MULTI_TENANT", True),
        patch.object(api, "fetch_existing_llm_provider_by_id", return_value=stored),
        patch.object(api, "upsert_decision_provider") as save,
    ):
        with pytest.raises(OnyxError):
            api.put_decision_provider(request, MagicMock(), MagicMock())
    stored.api_key.get_value.assert_not_called()
    save.assert_not_called()


def test_decision_update_preserves_omitted_connection_fields() -> None:
    stored = SimpleNamespace(
        provider="openai",
        zoom_voice_provider_id=None,
        api_base="https://gateway.example/v1",
        api_version="v1",
        custom_config={"header": "saved"},
        api_key=MagicMock(),
    )
    stored.api_key.get_value.return_value = "stored-secret"
    request = DecisionProviderUpsertRequest(
        id=7, provider="openai", selected_model_names=[]
    )
    with patch.object(api, "fetch_existing_llm_provider_by_id", return_value=stored):
        api._resolve_decision_connection(request, MagicMock(), MagicMock())
    assert request.api_key == "stored-secret"
    assert request.api_base == "https://gateway.example/v1"
    assert request.api_version == "v1"
    assert request.custom_config == {"header": "saved"}


@pytest.mark.parametrize("force", [False, True])
def test_selected_decision_model_blocks_provider_removal(force: bool) -> None:
    session = MagicMock()
    session.scalar.return_value = LLMProvider(id=7, zoom_voice_provider_id=None)
    with (
        patch.object(
            api,
            "fetch_default_model",
            return_value=ModelConfiguration(llm_provider_id=7),
        ),
        patch.object(api, "remove_llm_provider") as remove,
    ):
        with pytest.raises(OnyxError, match="Clear the selected decision model"):
            api.delete_llm_provider(7, force, MagicMock(), session)
    remove.assert_not_called()
