from unittest.mock import MagicMock, call, patch

import pytest

from onyx.db.enums import LLMModelFlowType
from onyx.db.models import LLMModelFlow, LLMProvider, ModelConfiguration, Persona
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.decisions.models import (
    DecisionProvider,
    DecisionRequest,
    PredicateQuestion,
)
from onyx.server.manage.llm import api
from onyx.server.manage.llm.models import OpenRouterModelsRequest
from onyx.server.manage.llm.models import TestLLMRequest as LLMTestRequest
from onyx.tracing.flows import LLMFlow


def _catalog_model(name: str, modalities: list[str]) -> dict[str, object]:
    return {
        "id": name,
        "name": name,
        "context_length": 8192,
        "architecture": {
            "input_modalities": ["text"],
            "output_modalities": modalities,
        },
    }


def test_openrouter_discovery_syncs_chat_and_decision_capabilities() -> None:
    session = MagicMock()
    with (
        patch.object(api, "_resolve_api_key", return_value="test-key"),
        patch.object(
            api,
            "fetch_existing_llm_provider_by_id",
            return_value=LLMProvider(id=7, provider="openrouter"),
        ),
        patch.object(
            api,
            "_get_openrouter_models_response",
            side_effect=[
                {"data": [_catalog_model("vendor/chat", ["text"])]},
                {
                    "data": [
                        _catalog_model("vendor/decision", ["decisions"]),
                        _catalog_model("vendor/dual", ["text", "decisions"]),
                    ]
                },
            ],
        ) as discover,
        patch.object(api, "_sync_fetched_models") as sync,
    ):
        models = api.get_openrouter_available_models(
            OpenRouterModelsRequest(
                api_base="https://openrouter.ai/api/v1",
                api_key="test-key",
                provider_id=7,
            ),
            MagicMock(),
            session,
        )

    assert discover.call_args_list == [
        call(api_base="https://openrouter.ai/api/v1", api_key="test-key"),
        call(
            api_base="https://openrouter.ai/api/v1",
            api_key="test-key",
            decisions_only=True,
        ),
    ]
    expected = [
        ("vendor/chat", True, False),
        ("vendor/decision", False, True),
        ("vendor/dual", True, True),
    ]
    assert [(m.name, m.supports_chat, m.supports_decisions) for m in models] == expected
    sync.assert_called_once()
    assert sync.call_args.kwargs["provider_id"] == 7
    assert [
        (m.name, m.supports_chat, m.supports_decisions)
        for m in sync.call_args.kwargs["models"]
    ] == expected


def test_optional_decision_discovery_failure_preserves_chat_models() -> None:
    with patch.object(
        api,
        "_get_openrouter_models_response",
        side_effect=[
            {"data": [_catalog_model("vendor/chat", ["text"])]},
            OnyxError(OnyxErrorCode.BAD_GATEWAY, "Decision catalog unavailable"),
        ],
    ):
        models = api.get_openrouter_available_models(
            OpenRouterModelsRequest(
                api_base="https://openrouter.ai/api/v1", api_key="test-key"
            ),
            MagicMock(),
            MagicMock(),
        )

    assert [(m.name, m.supports_chat, m.supports_decisions) for m in models] == [
        ("vendor/chat", True, False)
    ]


@pytest.mark.parametrize("provider", [None, LLMProvider(id=7, provider="openai")])
def test_openrouter_discovery_rejects_other_provider(
    provider: LLMProvider | None,
) -> None:
    with (
        patch.object(api, "fetch_existing_llm_provider_by_id", return_value=provider),
        patch.object(api, "_get_openrouter_models_response") as discover,
        patch.object(api, "_sync_fetched_models") as sync,
    ):
        with pytest.raises(OnyxError, match="requires an OpenRouter provider"):
            api.get_openrouter_available_models(
                OpenRouterModelsRequest(
                    api_base="https://openrouter.ai/api/v1",
                    api_key="test-key",
                    provider_id=7,
                ),
                MagicMock(),
                MagicMock(),
            )
    discover.assert_not_called()
    sync.assert_not_called()


def test_ordinary_openrouter_validation_does_not_fetch_decision_catalog() -> None:
    with (
        patch.object(api, "_get_openrouter_models_response") as discover,
        patch.object(api, "build_decision_client") as decision_client,
        patch.object(api, "get_llm") as get_llm,
        patch.object(api, "test_llm", return_value=None) as probe,
    ):
        api.test_llm_configuration(
            LLMTestRequest(
                provider="openrouter",
                model="vendor/chat",
                api_key="test-key",
                api_key_changed=True,
                custom_config_changed=True,
            ),
            MagicMock(),
            MagicMock(),
        )

    discover.assert_not_called()
    decision_client.assert_not_called()
    probe.assert_called_once_with(get_llm.return_value)


@pytest.mark.parametrize(
    ("catalog_modalities", "uses_decision_api"),
    [(["decisions"], True), (["text"], False), (["text", "decisions"], False)],
)
def test_openrouter_validation_uses_authoritative_capabilities(
    catalog_modalities: list[str], uses_decision_api: bool
) -> None:
    with (
        patch.object(
            api,
            "_get_openrouter_models_response",
            return_value={"data": [_catalog_model("vendor/model", catalog_modalities)]},
        ) as discover,
        patch.object(api, "build_decision_client") as decision_client,
        patch.object(api, "get_llm") as get_llm,
        patch.object(api, "test_llm", return_value=None) as probe,
    ):
        api.test_llm_configuration(
            LLMTestRequest(
                provider="openrouter",
                model="vendor/model",
                api_key="test-key",
                supports_decisions=True,
                api_key_changed=True,
                custom_config_changed=True,
            ),
            MagicMock(),
            MagicMock(),
        )

    discover.assert_called_once_with(
        "https://openrouter.ai/api/v1", "test-key", decisions_only=True
    )
    if uses_decision_api:
        decision_client.assert_called_once_with(
            provider=DecisionProvider.OPENROUTER,
            model="vendor/model",
            api_key="test-key",
            api_base=None,
            zoom_voice_provider_id=None,
        )
        decision_client.return_value.decide.assert_called_once_with(
            DecisionRequest(
                input="The sky is blue.",
                questions=[
                    PredicateQuestion(
                        name="check", instructions="Does the input mention the sky?"
                    )
                ],
            ),
            flow=LLMFlow.MODEL_VALIDATION,
        )
        get_llm.assert_not_called()
        probe.assert_not_called()
    else:
        decision_client.assert_not_called()
        probe.assert_called_once_with(get_llm.return_value)


def test_persona_model_options_exclude_decision_only_siblings() -> None:
    provider = LLMProvider(
        id=7,
        name="OpenRouter",
        provider="openrouter",
        model_configurations=[
            ModelConfiguration(
                id=model_id,
                name=name,
                is_visible=visible,
                llm_model_flows=[
                    LLMModelFlow(llm_model_flow_type=flow) for flow in flows
                ],
            )
            for model_id, name, visible, flows in [
                (1, "vendor/chat", True, [LLMModelFlowType.CHAT]),
                (2, "vendor/decision", True, [LLMModelFlowType.DECISION]),
                (
                    3,
                    "vendor/dual",
                    True,
                    [LLMModelFlowType.CHAT, LLMModelFlowType.DECISION],
                ),
                (4, "vendor/hidden", False, [LLMModelFlowType.CHAT]),
            ]
        ],
    )
    persona = Persona(id=1)
    with (
        patch.object(api, "fetch_persona_with_groups", return_value=persona),
        patch.object(api, "has_global_permission", return_value=True),
        patch.object(api, "fetch_existing_llm_providers", return_value=[provider]),
        patch.object(api, "can_user_access_llm_provider", return_value=True),
    ):
        names = api.get_valid_model_names_for_persona(1, MagicMock(), MagicMock())
        ids = api.get_valid_model_configuration_ids_for_persona(
            persona, MagicMock(), MagicMock()
        )

    assert names == ["vendor/chat", "vendor/dual"]
    assert ids == {1, 3}
