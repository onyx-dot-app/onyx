from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.constants import WELL_KNOWN_PROVIDER_NAMES, LlmProviderNames
from onyx.llm.factory import get_llm
from onyx.llm.model_catalog import iter_models
from onyx.llm.well_known_providers.nace import fetch_nace_models
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
    NaceModelsRequest,
)


def test_catalog_registers_decision_provider_without_chat_models() -> None:
    assert LlmProviderNames.NACE in WELL_KNOWN_PROVIDER_NAMES
    assert iter_models("nace", mode="decisions") == ["drex-max", "drex-v2.0"]
    assert iter_models("nace", mode="chat") == []


def test_configuration_has_no_auto_mode_or_api_base() -> None:
    request = LLMProviderUpsertRequest(provider=" Nace ", is_auto_mode=True)
    assert request.provider == "nace"
    assert request.is_auto_mode is False
    assert request.model_configurations == []
    with pytest.raises(ValidationError, match="chat model configuration"):
        LLMProviderUpsertRequest(
            provider="nace",
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name="drex-max", is_visible=True, supports_chat=True
                )
            ],
        )
    with pytest.raises(ValidationError, match="hosted System One API"):
        LLMProviderUpsertRequest(provider="nace", api_base="https://proxy.example")


def test_nace_cannot_construct_chat_client() -> None:
    with pytest.raises(ValueError, match="does not support chat"):
        get_llm(
            provider="nace",
            model="drex-max",
            max_input_tokens=100,
            deployment_name=None,
        )


def test_discovery_lists_models_once_without_catalog_aliases() -> None:
    with patch("onyx.llm.well_known_providers.nace.httpx.Client") as client:
        get = client.return_value.__enter__.return_value.get
        get.return_value.json.return_value = {
            "models": [
                {
                    "name": "drex-v2.0",
                    "description": "Drex 2.0 decision model.",
                    "release_date": "2026-10-06",
                    "alias_for": None,
                },
                {"name": "drex-max", "description": "Drex Max", "alias_for": None},
                {
                    "name": "drex-latest",
                    "description": "Points to drex-v2.0.",
                    "alias_for": "drex-v2.0",
                },
                {
                    "name": "drex-v1.0",
                    "description": "Retired; served by drex-max.",
                    "alias_for": "drex-max",
                },
            ],
            "request_id": "req_test",
        }
        assert [model.name for model in fetch_nace_models("secret")] == [
            "drex-v2.0",
            "drex-max",
        ]
        client.assert_called_once_with(timeout=30.0, follow_redirects=False)
        get.assert_called_once_with(
            "https://console.nace.ai/v1/models",
            headers={"Authorization": "Bearer secret"},
        )


@pytest.mark.parametrize("payload", [{}, {"models": [{"name": ""}]}, {"models": None}])
def test_discovery_rejects_malformed_catalog(payload: object) -> None:
    with patch("onyx.llm.well_known_providers.nace.httpx.Client") as client:
        client.return_value.__enter__.return_value.get.return_value.json.return_value = payload
        with pytest.raises(OnyxError, match="invalid catalog") as failure:
            fetch_nace_models("secret")
    assert failure.value.error_code is OnyxErrorCode.BAD_GATEWAY


@pytest.mark.parametrize("status", [401, 403, 429, 500, 529])
def test_discovery_separates_credentials_from_upstream_failures(status: int) -> None:
    """Upstream outages must not tell an admin to replace a valid API key."""
    response = httpx.Response(
        status,
        request=httpx.Request("GET", "https://console.nace.ai/v1/models"),
        text="private upstream detail",
    )
    with patch("onyx.llm.well_known_providers.nace.httpx.Client") as client:
        client.return_value.__enter__.return_value.get.return_value = response
        with pytest.raises(OnyxError) as failure:
            fetch_nace_models("secret")
    error = failure.value
    if status in (401, 403):
        assert error.error_code is OnyxErrorCode.VALIDATION_ERROR
        assert "Check the API key" in error.detail
    else:
        assert error.error_code is OnyxErrorCode.BAD_GATEWAY
        assert error.status_code == status
        assert "Try again later" in error.detail
        assert "API key" not in error.detail
    assert "private upstream detail" not in error.detail


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_discovery_reports_transport_failures_as_gateway_errors(
    error_type: type[httpx.RequestError],
) -> None:
    """Connection and timeout failures keep credential advice out of the response."""
    with patch("onyx.llm.well_known_providers.nace.httpx.Client") as client:
        client.return_value.__enter__.return_value.get.side_effect = error_type(
            "private transport detail"
        )
        with pytest.raises(OnyxError) as failure:
            fetch_nace_models("secret")
    assert failure.value.error_code is OnyxErrorCode.BAD_GATEWAY
    assert "Try again later" in failure.value.detail
    assert "API key" not in failure.value.detail
    assert "private transport detail" not in failure.value.detail


def test_discovery_uses_saved_credentials_and_syncs_decision_models() -> None:
    from onyx.llm.well_known_providers.models import NaceModel
    from onyx.server.manage.llm import api

    stored = MagicMock(provider="nace")
    stored.api_key.get_value.return_value = "saved-secret"
    with (
        patch.object(api, "fetch_existing_llm_provider_by_id", return_value=stored),
        patch.object(
            api, "fetch_nace_models", return_value=[NaceModel(name="drex-max")]
        ) as fetch,
        patch.object(api, "_sync_fetched_models") as sync,
    ):
        models = api.get_nace_available_models(
            NaceModelsRequest(provider_id=7), MagicMock(), MagicMock()
        )
        fetch.assert_called_once_with("saved-secret")
        assert models[0].name == "drex-max"
        assert models[0].supports_decisions is True
        assert models[0].supports_chat is False
        assert sync.call_args.kwargs["models"][0].supports_chat is False


def test_discovery_rejects_another_provider_before_reading_credentials() -> None:
    from onyx.server.manage.llm import api

    stored = MagicMock(provider="typesafe", zoom_voice_provider_id=None)
    with patch.object(api, "fetch_existing_llm_provider_by_id", return_value=stored):
        with pytest.raises(OnyxError, match="requires a Nace"):
            api.get_nace_available_models(
                NaceModelsRequest(provider_id=7), MagicMock(), MagicMock()
            )
    stored.api_key.get_value.assert_not_called()


def test_decision_catalog_uses_discovered_models() -> None:
    from onyx.llm.well_known_providers.models import NaceModel
    from onyx.server.manage.llm import api
    from onyx.server.manage.llm.models import DecisionProviderConnection

    with patch.object(
        api,
        "fetch_nace_models",
        return_value=[NaceModel(name="drex-max"), NaceModel(name="drex-v2.0")],
    ) as fetch:
        catalog = api._decision_provider_catalog(
            DecisionProviderConnection(provider="nace", api_key="nace-key")
        )
    fetch.assert_called_once_with("nace-key")
    assert catalog == {"drex-max": False, "drex-v2.0": False}
